"""
修正节点（Extra）

两轮修正，每轮一次 LLM 调用：
  第1轮（条件）：所有越界违规一次性批量修正
  第2轮（始终）：质量检查，检测排版/密度/对比度/遮盖等问题
"""

import sys
import os
import re

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from llm_utils import ask_llm_json
from logger import logger
from nodes.generation_node import _precheck_boundary


BOUNDARY_FIX_PROMPT = \
"""你负责批量修正 SVG 坐标违规。

## 输入
以下列出所有有边界违规的区域，每个区域包含尺寸、当前 SVG 内容和违规明细。

## 修正原则
1. **不添加新元素** —— 只调整现有元素的坐标/尺寸，不添加新的 <rect>/<text>/<circle>
2. 可通过整体缩放使越界元素回到区域内
3. 文本可缩小字号适应边界
4. 可微调元素间距
5. 保持原有颜色、文字内容和视觉风格
6. 如果只超出边界一点（< 10px），只微调该元素位置即可

## 输出格式
{
  "regions": {
    "region_id": {
      "svg_content": "修正后的 SVG 内容",
      "fix_summary": "简要说明修正内容"
    }
  }
}
只输出有修正的区域。输出严格的 JSON，不要包含 markdown 代码块标记。
"""


QUALITY_FIX_PROMPT = \
"""你负责检查 SVG 质量并修正发现的缺陷。

## 检查项

### 1. 信息密度
内容是否充分利用了分配的区域空间？
- 大片空白区域说明密度过低——将现有元素在垂直方向上分散排列
- 文本过少时，适当增大字号或行距来填充空间
- **不要添加新的图形/文字元素**，只调整已有的元素

### 2. 排版
- 文字位置是否合理，字号是否合适
- 标题、正文、说明文字之间是否有清晰层级

### 3. 对比度
- 浅色文字在深色背景上，深色文字在浅色背景上
- 颜色搭配是否利于阅读

### 4. 遮盖
- 元素之间是否有重叠
- 文字是否被其他元素遮挡

### 5. 父级与子级对齐
- 父节点中的连接线/箭头是否与子节点的边缘对齐（子节点已在 prompt 中列出位置）
- 连接线是否进入了子节点的**禁画区**（子节点所占矩形区域）
- 多个子节点之间的间距是否均匀，连接线是否在间隙正中间

### 6. 父容器重复内容
- **父容器是否绘制了与子节点相似或重复的内容（如标题、层卡片、图形块等）**
- 检查方法：对比父容器 SVG 元素与子节点区域的位置和内容摘要
- 如果发现重复：**从父容器中删除重复元素**，只保留背景矩形容器和子区域之间的连接线/箭头
- 子节点已能正确绘制自己的内容，父容器无需重复绘制

### 7. 视觉平衡
- 整体布局是否协调
- 元素在区域中是否居中/对齐

## 重要限制
- **禁止**将 `<layoutText>` 替换为 `<text>`——layoutText 是系统自定义标签，
  渲染器会自动处理其换行逻辑，换成普通 text 会破坏布局
- **禁止**删除任何现有的 `<layoutText>` 元素
- 其他 SVG 标准元素（rect, text, circle, line, path 等）可以正常调整

## 输出格式
{
  "regions": {
    "region_id": {
      "svg_content": "修正后的 SVG 内容",
      "fix_summary": "修正内容说明，控制在 40 字以内"
    }
  }
}
只输出需要修正的区域。输出严格的 JSON，不要包含 markdown 代码块标记。
"""


def correction_node(generation_output, translation_output,
                    design_output=None) -> dict:
    """修正生成结果中的 SVG 质量问题。

    两轮修正，每轮一次 LLM 调用：
      1. 边界越界修正（如有违规才执行）
      2. 质量检查（始终执行，含重复内容检测）

    Args:
        generation_output: generation_node 的输出，含 "svg_tree"
        translation_output: 转译节点输出（用于 region_descriptions）
        design_output: 设计节点输出，含 description（用于给 LLM 更多上下文）

    Returns:
        dict: {"fixed_count": int, "llm_call_count": int, "fixes": {...}}
    """
    abs_tree = generation_output["svg_tree"]
    region_descriptions = translation_output.get("region_descriptions", {})
    design_description = (design_output or {}).get("description", "")

    call_count = 0
    fixes = {}

    # ============================================================
    # 第1轮：边界越界修正（条件执行）
    # ============================================================
    violations_map = _collect_violations(abs_tree)

    if violations_map:
        logger.info(f"修正节点: {len(violations_map)} 个区域有边界违规:")
        for rid, (_, v) in violations_map.items():
            for vl in v:
                logger.fail(f"  [{rid}] {vl}")

        prompt = _build_boundary_prompt(abs_tree, violations_map,
                                         region_descriptions)
        result = ask_llm_json(BOUNDARY_FIX_PROMPT, prompt)
        call_count += 1

        round1_fixes = _apply_fixes(abs_tree, result.get("regions", {}))
        fixes.update(round1_fixes)

        for rid, summary in round1_fixes.items():
            logger.ok(f"  [{rid}] 边界已修正: {summary[:60]}")
            # 验证
            node = _find_node(abs_tree, rid)
            if node:
                remaining = _precheck_boundary(
                    node.get("svg_content", ""),
                    node.get("w", 0), node.get("h", 0), rid)
                if remaining:
                    logger.warn(f"   修正后仍有 {len(remaining)} 项违规")
                    for rv in remaining:
                        logger.warn(f"     - {rv}")
                else:
                    logger.info(f"   验证通过")
    else:
        logger.info("修正节点: 无边界违规")

    # ============================================================
    # 第2轮：质量检查（始终执行）
    # ============================================================
    logger.info(f"修正节点: 质量检查...")

    prompt = _build_quality_prompt(abs_tree, region_descriptions,
                                   design_description)
    result = ask_llm_json(QUALITY_FIX_PROMPT, prompt)
    call_count += 1

    round2_fixes = _apply_fixes(abs_tree, result.get("regions", {}))
    fixes.update(round2_fixes)

    for rid, summary in round2_fixes.items():
        logger.ok(f"  [{rid}] 质量已优化: {summary[:60]}")

    logger.info(f"修正节点: 共修正 {len(fixes)} 个区域, "
                f"LLM 调用 {call_count} 次")

    return {"fixed_count": len(fixes), "llm_call_count": call_count,
            "fixes": fixes}


# ============================================================
#  内部函数
# ============================================================

def _collect_violations(abs_tree):
    """遍历 abs_tree，收集所有有边界违规的 region

    Returns:
        dict: {region_id: (region_node, [violation_strings])}
    """
    violations = {}
    for root in abs_tree:
        _walk_collect(root, violations)
    return violations


def _walk_collect(node, violations_map):
    svg = node.get("svg_content", "")
    w = node.get("w", 0)
    h = node.get("h", 0)
    rid = node.get("region_id", "")

    if svg:
        v = _precheck_boundary(svg, w, h, rid)
        if v:
            violations_map[rid] = (node, v)

    for child in node.get("children", []):
        _walk_collect(child, violations_map)


def _find_node(abs_tree, region_id):
    """在 abs_tree 中递归查找指定 region_id 的节点"""
    for root in abs_tree:
        result = _walk_find(root, region_id)
        if result:
            return result
    return None


def _walk_find(node, region_id):
    if node.get("region_id") == region_id:
        return node
    for child in node.get("children", []):
        result = _walk_find(child, region_id)
        if result:
            return result
    return None


def _apply_fixes(abs_tree, regions_data):
    """将 LLM 返回的修正应用到 abs_tree 上

    Returns:
        dict: {region_id: fix_summary}
    """
    fixes = {}
    for rid, data in regions_data.items():
        svg = data.get("svg_content", "")
        summary = data.get("fix_summary", "")
        if not svg:
            continue
        node = _find_node(abs_tree, rid)
        if node:
            node["svg_content"] = svg
            fixes[rid] = summary
    return fixes


def _build_boundary_prompt(abs_tree, violations_map, region_descriptions) -> str:
    """构建第1轮边界修正提示词（所有违规区域在一个 prompt 中）"""
    sections = []
    sections.append(f"以下 {len(violations_map)} 个区域有边界违规，请一次性修正：")
    sections.append("")

    for rid, (node, violations) in violations_map.items():
        desc = region_descriptions.get(rid, "")
        w = node.get("w", 0)
        h = node.get("h", 0)
        svg = node.get("svg_content", "")

        sections.append(f"### {rid}")
        sections.append(f"内容描述: {desc}")
        sections.append(f"区域尺寸: {w}x{h}px")
        sections.append("违规:")
        for v in violations:
            sections.append(f"  - {v}")
        sections.append("当前 SVG:")
        sections.append(svg)
        sections.append("")

    sections.append(
        "请修正以上所有区域的坐标违规。不添加新元素，只调整坐标/尺寸。"
        "仅输出需要修正的区域。")
    return "\n".join(sections)


def _build_quality_prompt(abs_tree, region_descriptions,
                          design_description="") -> str:
    """构建第2轮质量检查提示词（所有区域）"""
    sections = []
    sections.append("请检查以下所有区域的 SVG 质量并修正发现的缺陷：")
    sections.append("")
    if design_description:
        sections.append(f"原始设计描述（参考用）: {design_description}")
        sections.append("")

    all_regions = []
    for root in abs_tree:
        _walk_list(root, all_regions)

    for node in all_regions:
        rid = node.get("region_id", "?")
        desc = region_descriptions.get(rid, "")
        x = node.get("x", 0)
        y = node.get("y", 0)
        w = node.get("w", 0)
        h = node.get("h", 0)
        has_kids = len(node.get("children", [])) > 0
        svg = node.get("svg_content", "")

        if not svg:
            continue

        sections.append(f"### {rid}")
        sections.append(f"内容描述: {desc}")
        sections.append(f"相对父节点位置: x={x}, y={y}  尺寸: {w}x{h}px")
        if has_kids:
            sections.append("类型: 父容器（含有子区域，连接线/箭头应绘制在子区域之间的间隙中，不得进入子区域内部）")
        sections.append("SVG 内容:")
        sections.append(svg)
        sections.append("")

    sections.append(
        "检查以上所有区域的信息密度、排版、对比度、遮盖和视觉平衡问题。"
        "不添加新元素，只调整已有元素来改善质量。"
        "仅输出需要修正的区域。")
    return "\n".join(sections)


def _walk_list(node, result):
    """递归收集所有有 svg_content 的节点"""
    if node.get("svg_content"):
        result.append(node)
    for child in node.get("children", []):
        _walk_list(child, result)
