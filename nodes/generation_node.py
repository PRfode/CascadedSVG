"""
生成节点

后序生成：_sib_gen_node(node) 先递归所有子节点，再批量生成当前节点的子节点。
"""

import sys
import os
import re
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from llm_utils import ask_llm_json
from logger import logger

# ============================================================
#  系统提示词
# ============================================================

BATCH_GENERATION_SYSTEM_PROMPT = \
"""你负责为 SVG 图形批量生成具体内容。

## 你的角色
你收到同一父区域下的一组兄弟姐妹区域信息，需要为它们**一次性**生成所有 SVG 内容。
这些区域在最终图形中并列显示，因此视觉风格必须统一协调。

## 输入信息
你每次调用会收到：
1. 全局设计上下文（画布、主题色、设计描述等）
2. 父区域上下文（父节点内容摘要和位置尺寸）
3. 所有待生成区域的详细信息（每个区域的 region_id、大体样式描述、位置尺寸、样式标签）
4. 可用模板列表（可选使用）

## 核心要求

### 禁画区规则（最高优先级）
如果一个区域有子区域：
- **子区域已绘制了自己的内容，你绝对不得在子区域占据的矩形范围内绘制任何图形、文字或装饰**
- 子区域的精确像素坐标范围会在提示词中以"禁画区"形式列出，你必须严格遵守
- 有子区域的区域**只能**绘制以下三种内容之一：
  1. 背景矩形容器（以统一视觉风格）
  2. 在子区域之间的间隙中绘制连接线/箭头（见下方"层间连接"）
  3. 在所有子区域**上方**（即子区域顶部边界之上）绘制标题文字
- **禁止**在子区域内部绘制任何与子区域内容重复的元素
- 典型错误：父区域绘制了与子区域完全相同的层/卡片内容，导致画面重叠混乱

### 视觉统一
同一批次中的所有兄弟姐妹区域，必须：
- 使用**一致的**边框宽度、圆角大小、阴影效果
- 使用相同的配色体系（背景色、边框色、文字色等）
- 确保整体视觉效果和谐统一

### 禁止重叠
- 每个区域**内部**的元素之间必须保留至少 5px 间距
- 文字与其他图形元素不可重叠
- 合理安排垂直布局：标题 → 说明文字 → 可视化内容，每部分之间保留充足间距

### 层间连接
- 如果某个待生成区域有子区域，你需要在子区域之间的间隙中绘制连接线/箭头来串联它们，标明顺序或流向
- 水平排列的子区域之间画向右的箭头，垂直排列的子区域之间画向下的箭头
- 连接线必须画在子区域之间的间隙正中间，**不要进入子区域内部**
- 没有子区域的区域无需绘制连接线

### 填充区域自检
生成后请检查内容是否均匀分布在整个区域中。特别注意：
- 每个区域的实际视觉内容（图标、文字、图形）应覆盖至少 60% 的垂直空间
- 不能只有顶部一个图标 + 底部一行文字而中间全部空白
- 如果区域内只有少量内容（如一个图标和一行标题），必须添加更多说明性文字、示例或装饰图形来填充
- **具体检查标准**：
  - 高度 <= 200px 的区域：至少 3 个视觉元素（标题+图形+文字）
  - 高度 > 200px 的区域：至少 4~5 个元素，分多层布局，垂直覆盖 >= 60%
  - 最上方和最下方元素间距 >= 区域高度的 50%
- 好的例子：一个卡片有标题、图标/图形、说明文字、辅助详情，四部分均匀分布
- 差的例子：一个 400px 高的卡片只有一个 48px 图标和一行 20px 文字（共占不到 70px）

### 坐标系统
- 每个区域的 SVG 坐标相对于该区域**自身的左上角 (0,0)**
- **坐标边界必须遵守**：每个区域的 SVG 元素必须限制在该区域的尺寸范围内，不得越界。
  例如区域宽 200px，则所有元素的 x + width 不得超过 200。

### 合法 SVG 元素
- rect, text, circle, line, path, g, defs, linearGradient
- 对于需要自动换行的多行文本，使用 `<layoutText>` 替代 `<text>`：
  `<layoutText x="10" y="20" width="200" font-size="14" fill="#333">要显示的文字</layoutText>`
  渲染器会自动按 width 拆分文本为多行。支持属性: x, y, width(最大行宽), font-size,
  fill, line-height(行高倍数,默认1.5), font-weight(normal/bold), text-anchor(start/middle/end)
- 文本内容必须具体、有意义（不用 "标题文字" 之类的占位符）

## 输出格式
输出必须是 **严格的 JSON**（不要包含 markdown 代码块标记）：

{
  "regions": {
    "region_id_1": {
      "svg_content": "<rect x=\"0\" y=\"0\" .../>\\n<text ...>...</text>",
      "content_summary": "自然语言描述该区域画了什么，控制在 40-60 字以内，简洁明了"
    },
    "region_id_2": {
      "svg_content": "...",
      "content_summary": "..."
    }
  }
}

### svg_content 字段
- 使用相对于该区域左上角 (0,0) 的坐标
- ⚠ **如果当前区域有子区域，子区域是"禁画区"。具体禁画区坐标范围见上方各区域的"禁画区"标注**
- 有子区域的区域只应绘制：背景矩形 + 子区域间隙中的连接元素 + 子区域上方的标题

### content_summary 字段
- 自然语言描述该区域画了什么、用了什么颜色、写了什么文字
- 控制在 40-60 字以内，简洁明了
- 如果该区域有父区域，该字段会传递给父区域作为参考
"""


# ============================================================
#  入口
# ============================================================

def generation_node(design_output, translation_output, templates_output,
                    user_request="") -> dict:
    cascade = translation_output["cascade_structure"]
    canvas = translation_output["canvas"]
    region_descriptions = translation_output.get("region_descriptions", {})
    style_descriptions = translation_output.get("style_descriptions", {})

    abs_tree = _build_abs_tree(cascade, canvas["width"], canvas["height"],
                                region_descriptions, style_descriptions)

    global_ctx = {
        "description": design_output["description"],
        "themes": design_output["themes"],
        "canvas_w": canvas["width"],
        "canvas_h": canvas["height"],
        "color_scheme": translation_output["color_scheme"],
        "base_font_size": translation_output["base_font_size"],
        "grid_unit": translation_output["grid_unit"],
        "user_request": user_request,
    }

    templates = templates_output.get("templates", [])

    cw, ch = canvas["width"], canvas["height"]
    canvas_root = {
        "region_id": "canvas",
        "content_summary": "",
        "x": 0, "y": 0, "w": cw, "h": ch,
        "abs_x": 0, "abs_y": 0, "abs_w": cw, "abs_h": ch,
        "children": abs_tree,
    }

    call_count = _sib_gen_node(canvas_root, global_ctx, templates,
                                region_descriptions)
    return {"svg_tree": abs_tree, "llm_call_count": call_count}


# ============================================================
#  后序层级生成
# ============================================================

def _sib_gen_node(node, global_ctx, templates, region_descriptions, depth=0):
    """后序生成 node 的所有子节点

    先递归每个子节点，再批量生成本层所有子节点。
    node 没有子节点时直接返回。
    """
    if not node.get("children"):
        return 0

    call_count = 0

    # 后序递归
    for child in node["children"]:
        call_count += _sib_gen_node(child, global_ctx, templates,
                                     region_descriptions, depth + 1)

    # 批量生成当前节点的所有子节点
    children = node["children"]
    indent = "  " * depth
    child_ids = [c.get("region_id", "?") for c in children]
    logger.info(f"{indent}[批次] 生成 {len(children)} 个子区域: {', '.join(child_ids)}")

    batch_prompt = _build_batch_prompt(children, node, global_ctx,
                                        templates, region_descriptions)

    max_attempts = 3
    for attempt in range(max_attempts):
        try:
            result = ask_llm_json(BATCH_GENERATION_SYSTEM_PROMPT, batch_prompt)
            break
        except (ValueError, json.JSONDecodeError) as e:
            if attempt < max_attempts - 1:
                logger.warn(f"JSON 解析失败，第 {attempt+1} 次重试...")
                continue
            raise
    call_count += 1

    regions_data = result.get("regions", {})
    for child in children:
        rid = child["region_id"]
        if rid in regions_data:
            child["svg_content"] = regions_data[rid].get("svg_content", "")
            child["content_summary"] = regions_data[rid].get("content_summary", "")

    for child in children:
        cs = child.get("content_summary", "")
        logger.info(f"{indent}  -> {child['region_id']}: {cs[:80]}")

    for child in children:
        if child.get("svg_content"):
            violations = _precheck_boundary(
                child["svg_content"], child.get("w", 0), child.get("h", 0),
                child.get("region_id", ""))
            if violations:
                logger.warn(f"边界违规 ({child['region_id']}): "
                            f"{'; '.join(violations)}")

    return call_count


# ============================================================
#  Prompt 构建
# ============================================================

def _build_batch_prompt(children, parent_ctx, global_ctx, templates,
                        region_descriptions) -> str:
    sections = []

    cs = global_ctx["color_scheme"]
    sections.append("## 全局设计上下文")
    sections.append(f"设计描述: {global_ctx['description']}")
    if global_ctx.get("user_request"):
        sections.append(f"用户原始请求: {global_ctx['user_request']}")
    sections.append(f"主旨: {', '.join(global_ctx['themes'])}")
    sections.append(f"画布: {global_ctx['canvas_w']}x{global_ctx['canvas_h']}")
    sections.append(f"主题色: 主={cs['primary']}, 辅={cs['secondary']}, "
                    f"背景={cs['background']}, 文本={cs['text']}, 强调={cs['accent']}")
    sections.append(f"基准字号: {global_ctx['base_font_size']}px")
    sections.append(f"网格单位: {global_ctx['grid_unit']}px")
    sections.append("")

    sections.append("## 父区域上下文")
    sections.append(f"父区域: {parent_ctx['region_id']}")
    sections.append(f"父区域内容摘要: {parent_ctx.get('content_summary', '')}")
    sections.append(f"父区域位置: ({parent_ctx['abs_x']},{parent_ctx['abs_y']}) "
                    f"[{parent_ctx['abs_w']}x{parent_ctx['abs_h']}]")
    sections.append("")

    sections.append(f"## 待一次性生成的区域（共 {len(children)} 个）")
    sections.append("这些区域是同一父区域下的兄弟姐妹，请在**一次 LLM 调用**中为它们全部生成 SVG 内容。")
    sections.append("""
**重要要求（必须遵守）：**
1. 兄弟姐妹区域的**视觉风格必须统一**——相同的边框宽度、圆角大小、阴影效果
2. 每个区域内部的**元素之间不可以重叠**，同一区域内的任意两个元素保留至少 5px 间距
3. 文字与图形之间也要保留间距，不可重叠
4. 合理安排垂直布局：标题 → 说明文字 → 可视化内容，每部分保留充足间距
5. 每个区域的子节点区域已经完成绘制，**不允许在子节点绘制的区域再进行绘制**""")
    sections.append("")

    parent_w = parent_ctx.get("w", 0)
    parent_h = parent_ctx.get("h", 0)
    grid_unit = global_ctx.get("grid_unit", 8)
    sections.append(f"父区域尺寸: {parent_w}x{parent_h}px, 网格单位: {grid_unit}px")
    sections.append("")

    for i, child in enumerate(children):
        rid = child["region_id"]
        desc = region_descriptions.get(rid, "")
        style_tag = child.get("style_tag", "")
        pct_x = child.get("pct_x", 0)
        pct_y = child.get("pct_y", 0)
        pct_w = child.get("pct_w", 0)
        pct_h = child.get("pct_h", 0)
        px_x = round(parent_w * pct_x)
        px_y = round(parent_h * pct_y)
        px_w = round(parent_w * pct_w)
        px_h = round(parent_h * pct_h)
        sections.append(f"### 区域 {i+1}: {rid}")
        sections.append(f"  内容描述: {desc}")
        sections.append(f"  样式标签: {style_tag}")
        sections.append(f"  相对位置: x={pct_x*100:.0f}%, y={pct_y*100:.0f}%, "
                        f"w={pct_w*100:.0f}%, h={pct_h*100:.0f}%")
        sections.append(f"  推算像素: x≈{px_x}, y≈{px_y}, w≈{px_w}, h≈{px_h}")
        sections.append(f"  关键坐标: 左边缘={px_x}, 右边缘={px_x+px_w}, "
                        f"上边缘={px_y}, 下边缘={px_y+px_h}, "
                        f"水平中心={px_x+px_w//2}, 垂直中心={px_y+px_h//2}")
        if child.get("children"):
            sections.append(
                f"  该区域有 {len(child['children'])} 个子区域（已生成）：")
            sections.append(
                "  ⚠ **禁画区规则**：以下子区域矩形范围是禁画区，"
                "不得在其中绘制任何图形/文字/装饰。只能绘制连接元素在间隙中。")
            for gc in child["children"]:
                gc_desc = region_descriptions.get(gc["region_id"], "")
                gc_content = gc.get("content_summary", "")
                gc_x = round(child["w"] * gc.get("pct_x", 0))
                gc_y = round(child["h"] * gc.get("pct_y", 0))
                gc_w = round(child["w"] * gc.get("pct_w", 0))
                gc_h = round(child["h"] * gc.get("pct_h", 0))
                if gc_content:
                    sections.append(
                        f"    - 禁画区 {gc['region_id']}: "
                        f"x={gc_x} y={gc_y} w={gc_w} h={gc_h}")
                    sections.append(
                        f"      内容: {gc_content[:120]}")
                else:
                    sections.append(
                        f"    - 禁画区 {gc['region_id']}: "
                        f"x={gc_x} y={gc_y} w={gc_w} h={gc_h} — {gc_desc[:40]}")
            sections.append(
                "  你只能绘制：背景矩形 + 子区域之间的连接元素 + 子区域上方的标题")
        sections.append("")

    if templates:
        sections.append(f"## 可用模板（共 {len(templates)} 个）")
        sections.append("以下模板是可选的视觉积木，兄弟姐妹区域应尽量使用相同的模板。")
        sections.append("如果不匹配，请直接创建 SVG。")
        sections.append("")
        for tmpl in templates:
            tid = tmpl.get("template_id", "?")
            desc = tmpl.get("description", "")
            params_str = ", ".join(
                f"{k}:{v.get('type', '?')}"
                for k, v in tmpl.get("params", {}).items())
            sections.append(f"  [{tid}] {desc}")
            sections.append(f"    参数: {params_str}")
            sections.append(f"    SVG: {tmpl.get('svg_template', '')[:100]}...")
            sections.append("")
    else:
        sections.append("## 可用模板")
        sections.append("（无可用模板，请直接创建 SVG）")
        sections.append("")

    sections.append("""
## 输出格式
{
  "regions": {
    "区域ID_1": {
      "svg_content": "<rect x=\"0\" y=\"0\" ... />\\n<text ...>内容</text>",
      "content_summary": "我在这个区域画了..."
    },
    "区域ID_2": {
      "svg_content": "...",
      "content_summary": "..."
    }
  }
}
""")

    return "\n".join(sections)


# ============================================================
#  绝对位置树
# ============================================================

def _build_abs_tree(cascade, canvas_w, canvas_h, region_descriptions,
                    style_descriptions):
    tree = []
    for region in cascade:
        node = _walk_abs(region, canvas_w, canvas_h, 0, 0,
                         canvas_w, canvas_h, region_descriptions)
        tree.append(node)
    return tree


def _walk_abs(region, canvas_w, canvas_h, parent_x, parent_y,
              parent_w, parent_h, region_descriptions):
    pos = region["position"]
    rel_x = round(parent_w * pos["x"])
    rel_y = round(parent_h * pos["y"])
    rel_w = round(parent_w * pos["w"])
    rel_h = round(parent_h * pos["h"])
    abs_x = round(parent_x + parent_w * pos["x"])
    abs_y = round(parent_y + parent_h * pos["y"])
    abs_w = round(parent_w * pos["w"])
    abs_h = round(parent_h * pos["h"])
    rid = region["region_id"]
    desc = region_descriptions.get(rid, "")

    node = {
        "region_id": rid,
        "label": region.get("label", ""),
        "description": desc,
        "style_tag": region.get("style_tag", ""),
        "x": rel_x, "y": rel_y, "w": rel_w, "h": rel_h,
        "abs_x": abs_x, "abs_y": abs_y, "abs_w": abs_w, "abs_h": abs_h,
        "pct_x": pos["x"], "pct_y": pos["y"],
        "pct_w": pos["w"], "pct_h": pos["h"],
        "children": [],
    }

    for child in region.get("children", []):
        child_node = _walk_abs(child, canvas_w, canvas_h,
                                abs_x, abs_y, abs_w, abs_h,
                                region_descriptions)
        node["children"].append(child_node)

    return node


# ============================================================
#  边界预检
# ============================================================

def _precheck_boundary(svg_content, region_w, region_h, region_id=""):
    violations = []
    tol = 5
    if not svg_content or not isinstance(svg_content, str):
        return violations

    for tag_match in re.finditer(
            r'<(rect|circle|text|line|path)(\s+[^>]*?)\s*(/?)>', svg_content):
        elem_type = tag_match.group(1)
        attrs_str = tag_match.group(2)

        attrs = {}
        for name, val in re.findall(r'([\w-]+)="([^"]*?)"', attrs_str):
            try:
                attrs[name] = float(val)
            except ValueError:
                pass

        if elem_type == 'rect':
            x = attrs.get('x', 0)
            y = attrs.get('y', 0)
            w = attrs.get('width', 0)
            h = attrs.get('height', 0)
            if x + w > region_w + tol:
                violations.append(
                    f"rect x({x})+w({w})={x+w} > 区域宽({region_w})")
            if y + h > region_h + tol:
                violations.append(
                    f"rect y({y})+h({h})={y+h} > 区域高({region_h})")

        elif elem_type == 'circle':
            cx = attrs.get('cx', 0)
            cy = attrs.get('cy', 0)
            r = attrs.get('r', 0)
            if cx + r > region_w + tol:
                violations.append(
                    f"circle cx({cx})+r({r})={cx+r} > 区域宽({region_w})")
            if cy + r > region_h + tol:
                violations.append(
                    f"circle cy({cy})+r({r})={cy+r} > 区域高({region_h})")

        elif elem_type == 'text':
            x = attrs.get('x', 0)
            y = attrs.get('y', 0)
            if x > region_w + tol:
                violations.append(
                    f"text x({x}) > 区域宽({region_w})")
            if y > region_h + tol:
                violations.append(
                    f"text y({y}) > 区域高({region_h})")

        elif elem_type == 'line':
            x1 = attrs.get('x1', 0)
            y1 = attrs.get('y1', 0)
            x2 = attrs.get('x2', 0)
            y2 = attrs.get('y2', 0)
            if max(x1, x2) > region_w + tol:
                violations.append(
                    f"line max(x1,x2)={max(x1,x2)} > 区域宽({region_w})")
            if max(y1, y2) > region_h + tol:
                violations.append(
                    f"line max(y1,y2)={max(y1,y2)} > 区域高({region_h})")

        elif elem_type == 'path':
            d = attrs.get('d', '')
            for cmd_match in re.finditer(r'[ML]\s*([\d.-]+)\s+([\d.-]+)', d):
                px = float(cmd_match.group(1))
                py = float(cmd_match.group(2))
                if px > region_w + tol:
                    violations.append(
                        f"path px({px}) > 区域宽({region_w})")
                if py > region_h + tol:
                    violations.append(
                        f"path py({py}) > 区域高({region_h})")

    return violations
