"""
模板节点（工程师）

职责：根据转译节点的外观描述，为**可复用的视觉要素**生成 SVG 模板。
模板是视觉积木（如 step-card、arrow），不是每个区域的完整定义。

关键变化：
- 不再要求 "覆盖所有 style_tag"
- 只生成真正会被复用（2次以上）的视觉要素模板
- style_tag 只用一次的区域由生成节点直接处理

输出传递给：评审节点、生成节点、渲染器
"""
import sys
import os
import re

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from llm_utils import ask_llm_json

# ============ 系统提示词 ============

TEMPLATE_NODE_SYSTEM_PROMPT = \
"""你是一位"工程师"，负责为 SVG 图形设计可复用的视觉要素模板。

## 你的角色
你是整个流水线的第三环。你收到制图师（转译节点）的层叠结构和样式描述，
需要从中识别出**可复用的视觉元素**，并为它们生成参数化的 SVG 模板。

## 什么是"可复用的视觉要素"？
- 在整张图中**被使用 2 次以上**的视觉元素
- 例如：4 个步骤卡片都用到了"圆角卡片"→ 生成 step-card 模板
- 例如：多个区域之间都需要"连接箭头"→ 生成 arrow 模板
- 例如：多个文本块都使用"正文样式"→ 生成 body-text 模板
- 反例：标题区域只出现一次 → 不需要模板，由生成节点直接处理

## 输入信息
你将收到：
1. 设计描述和主旨标签（理解整体视觉方向）
2. 层叠结构中的所有 style_tag 及其视觉描述（style_descriptions）
3. 全局信息（画布尺寸、主题色、基准字号、网格单位）
4. 层叠结构详情（了解整体布局）

## 你的任务
1. **分析复用性**：查看每个 style_tag 在层叠结构中被使用了多少次
2. **筛选可复用**：只选择那些被使用 2 次以上的 style_tag 生成模板
3. **设计模板**：为每个可复用的视觉要素设计参数化的 SVG 模板

## 输出格式
输出必须是 **严格的 JSON**（不要包含 markdown 代码块标记）：

```json
{
  "templates": [
    {
      "template_id": "step-card",
      "description": "带圆角的卡片容器，用于放置步骤内容。浅色填充、深色边框、带细微阴影，内部可容纳图标和文字",
      "style_tag_hint": "step-card",
      "reuse_count": 4,
      "params": {
        "bg_color": { "type": "color", "description": "卡片背景色" },
        "border_color": { "type": "color", "description": "边框颜色" },
        "corner_radius": { "type": "grid_unit_multiple", "description": "圆角半径（px），建议 4~8" },
        "width": { "type": "number", "description": "卡片宽度（px）" },
        "height": { "type": "number", "description": "卡片高度（px）" },
        "x": { "type": "number", "description": "左上角X坐标（px）" },
        "y": { "type": "number", "description": "左上角Y坐标（px）" }
      },
      "svg_template": "<rect x=\"{{x}}\" y=\"{{y}}\" width=\"{{width}}\" height=\"{{height}}\" rx=\"{{corner_radius}}\" ry=\"{{corner_radius}}\" fill=\"{{bg_color}}\" stroke=\"{{border_color}}\" stroke-width=\"2\" />"
    }
  ]
}
```

## 模板字段说明
- **template_id**：模板的唯一标识符，与 style_tag 同名
- **description**：模板的"说明书"，描述该视觉元素长什么样、用在什么场景
- **style_tag_hint**：这个模板主要服务于哪个 style_tag（仅供参考，不要求覆盖）
- **reuse_count**：该 style_tag 在层叠结构中出现的次数（佐证其复用性）
- **params**：参数定义，键为参数名，值为类型和描述
  - 合法类型：percentage, color, grid_unit_multiple, string, number
- **svg_template**：带 {{param_name}} 占位符的 SVG 片段
  - 占位符名称必须与 params 中的键一一对应
  - 使用合法 SVG 语法（rect, circle, text, line, path 等）

## 设计原则
- **质量 > 数量**：只生成 1~4 个真正高价值的模板，不要凑数
- 模板的 SVG 应保持简洁，优先使用基础元素（rect, text, circle, line）
- 颜色值通过参数传入，不要硬编码
- 文本内容通过 {{text_content}} 参数传入，使用 `<text>{{text_content}}</text>` 语法
- svg_template 中严禁出现 `</svg>`（模板是片段，不是完整文档）
- 模板的视觉风格应与 style_descriptions 中描述的一致
"""


# ============ 节点实现 ============

def template_node(design_output: dict, translation_output: dict, extra_context: str = "") -> dict:
    """模板节点：为可复用的视觉要素生成 SVG 模板

    Args:
        design_output: 设计节点的输出（description, themes）
        translation_output: 转译节点的输出
        extra_context: 重试时附加的错误上下文（预检失败信息）

    Returns:
        dict: 包含 templates 列表的字典
    """
    description = design_output["description"]
    themes = design_output["themes"]
    cascade_structure = translation_output["cascade_structure"]
    color_scheme = translation_output["color_scheme"]
    base_font_size = translation_output["base_font_size"]
    grid_unit = translation_output["grid_unit"]
    canvas = translation_output["canvas"]
    style_descriptions = translation_output.get("style_descriptions", {})

    # 统计每个 style_tag 的使用次数
    style_tag_counts = _count_style_tags(cascade_structure)

    # 格式化 style_descriptions（仅包含层叠结构中实际使用的 tag）
    style_desc_lines = []
    for tag, desc in style_descriptions.items():
        count = style_tag_counts.get(tag, 0)
        reuse_note = "★ 可复用" if count >= 2 else "  单次使用"
        style_desc_lines.append(f'  - {tag}  [{reuse_note}，使用{count}次]: {desc}')
    style_desc_text = "\n".join(style_desc_lines) if style_desc_lines else "  (无)"

    # 构建复用分析摘要
    reusable_tags = [t for t, c in style_tag_counts.items() if c >= 2]
    single_tags = [t for t, c in style_tag_counts.items() if c < 2]

    user_prompt = f"""请根据以下信息，生成 SVG 样式模板。

## 设计描述
{description}

## 主旨标签
{', '.join(themes)}

## 全局信息
- 画布: {canvas['width']}x{canvas['height']}
- 基准字体大小: {base_font_size}px
- 网格单位: {grid_unit}px
- 主题色: 主色={color_scheme['primary']}, 辅色={color_scheme['secondary']},
  背景={color_scheme['background']}, 文本={color_scheme['text']}, 强调={color_scheme['accent']}

## 所有 style_tag 及其使用次数
{style_desc_text}

## 复用分析
- 可复用（使用 2 次以上，建议生成模板）: {', '.join(f'"{t}"' for t in reusable_tags) if reusable_tags else "无"}
- 单次使用（不生成模板，由生成节点直接处理）: {', '.join(f'"{t}"' for t in single_tags) if single_tags else "无"}

## 层叠结构详情
{_format_cascade_summary(cascade_structure)}

## 要求
- **只为可复用的 style_tag 生成模板**（即使用 2 次以上的）
- 单次使用的 style_tag **不要**生成模板
- 模板数量控制在 1~4 个
- 每个模板的 reuse_count 字段填入实际使用次数"""

    if extra_context:
        user_prompt += f"""

## 上一次生成的错误
{extra_context}

请根据上述反馈修正。"""

    user_prompt += "\n\n请生成模板集合 JSON。"

    result = ask_llm_json(TEMPLATE_NODE_SYSTEM_PROMPT, user_prompt)

    # === 后处理：规范化字段名 ===
    # LLM 有时会输出 style_tag 而不是 template_id，自动修正
    for tmpl in result.get("templates", []):
        if "template_id" not in tmpl and "style_tag" in tmpl:
            tmpl["template_id"] = tmpl["style_tag"]

    # === 输出验证（轻量） ===
    _validate_template_output(result)
    return result


# ============ 辅助函数 ============

def _count_style_tags(cascade_structure: list) -> dict:
    """递归统计每个 style_tag 在层叠结构中的使用次数"""
    counts = {}
    _walk_count(cascade_structure, counts)
    return counts


def _walk_count(regions: list, counts: dict):
    """递归遍历统计"""
    for r in regions:
        if "style_tag" in r:
            tag = r["style_tag"]
            counts[tag] = counts.get(tag, 0) + 1
        if r.get("children"):
            _walk_count(r["children"], counts)


def _format_cascade_summary(cascade_structure: list, indent: int = 0) -> str:
    """将层叠结构格式化为可读的摘要文本"""
    lines = []
    prefix = "  " * indent
    for region in cascade_structure:
        pos = region.get("position", {})
        tag = region.get("style_tag", "?")
        style_tag_note = f" [{tag}]"
        lines.append(
            f'{prefix}- {region.get("region_id", "?")}{style_tag_note}: '
            f'{region.get("label", "")} '
            f'pos=({pos.get("x", "?"):<5}, {pos.get("y", "?"):<5}) '
            f'size=({pos.get("w", "?"):<5}, {pos.get("h", "?"):<5})'
        )
        if region.get("children"):
            lines.append(_format_cascade_summary(region["children"], indent + 1))
    return "\n".join(lines)


# ============ 验证 ============

VALID_PARAM_TYPES = {"percentage", "color", "grid_unit_multiple", "string", "number"}


def _validate_template_output(output: dict):
    """验证模板节点输出。注意：不要求覆盖所有 style_tag，不要求模板存在"""
    if "templates" not in output:
        raise ValueError("模板节点输出缺少字段: templates")
    if not isinstance(output["templates"], list):
        raise ValueError("templates 必须为数组")

    # 空模板列表是允许的（没有可复用的视觉要素）
    if len(output["templates"]) == 0:
        return

    for i, tmpl in enumerate(output["templates"]):
        required_fields = ["template_id", "description", "params", "svg_template"]
        for field in required_fields:
            if field not in tmpl:
                raise ValueError(f"templates[{i}] 缺少字段: {field}")

        # 验证 params
        if not isinstance(tmpl["params"], dict) or len(tmpl["params"]) == 0:
            raise ValueError(f"templates[{i}] params 必须为非空对象")

        for pname, pdef in tmpl["params"].items():
            if not isinstance(pdef, dict) or "type" not in pdef:
                raise ValueError(f"templates[{i}].params.{pname} 缺少 type")
            if pdef["type"] not in VALID_PARAM_TYPES:
                raise ValueError(
                    f"templates[{i}].params.{pname} 类型无效: "
                    f"{pdef['type']}，有效值: {VALID_PARAM_TYPES}"
                )

        # 检查 <text> 元素是否为自闭合
        self_closing_texts = re.findall(r'<text[^>]*/\s*>', tmpl["svg_template"])
        if self_closing_texts:
            raise ValueError(
                f"templates[{i}] svg_template 中的 <text> 标签是自闭合的（/>），"
                f"请使用 <text>{{{{text_content}}}}</text> 语法"
            )

        # 检查 svg_template 中是否包含 </svg>
        if '</svg>' in tmpl["svg_template"]:
            raise ValueError(
                f"templates[{i}] svg_template 中包含了 </svg>，"
                f"模板是 SVG 片段，不应包含完整文档的闭合标签"
            )

    # 注意：NOT checking for style_tag coverage — 这是有意为之
    # 模板是可选的视觉积木，不要求覆盖任何 style_tag
