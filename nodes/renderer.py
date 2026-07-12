"""
渲染器

职责：将生成节点的 svg_tree 递归拼装为完整的 SVG 文件。
- 创建 SVG 文档骨架（xmlns, viewBox）
- 按生成树深度优先遍历，每个 region 的 SVG 用 <g transform="translate"> 包裹
- 保存至 outputs/ 目录，以时间戳为文件名
"""
import sys
import os
import re
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ============================================================
#  核心渲染
# ============================================================

def renderer(translation_output, generation_output, timestamp: str = "") -> str:
    """渲染器：将生成结果拼装为完整 SVG 并保存

    Args:
        translation_output: 转译节点输出（canvas, color_scheme）
        generation_output: 生成节点输出（svg_tree）
        timestamp: 时间戳字符串（与日志文件同步），为空则自动生成

    Returns:
        str: 保存的 SVG 文件绝对路径
    """
    canvas = translation_output["canvas"]
    color_scheme = translation_output["color_scheme"]
    svg_tree = generation_output["svg_tree"]

    cw, ch = canvas["width"], canvas["height"]
    ts = timestamp if timestamp else datetime.now().strftime("%Y%m%d_%H%M%S")
    human_ts = f"{ts[:4]}-{ts[4:6]}-{ts[6:8]} {ts[9:11]}:{ts[11:13]}:{ts[13:15]}"
    lines = [
        '<?xml version="1.0" encoding="utf-8"?>',
        f'<!--',
        f'  ============================================================',
        f'  CascadeSVG 生成输出',
        f'  生成时间: {human_ts}',
        f'  画布: {cw}x{ch}',
        f'  主题色:',
        f'    primary:   {color_scheme["primary"]}',
        f'    secondary: {color_scheme["secondary"]}',
        f'    background: {color_scheme["background"]}',
        f'    text:      {color_scheme["text"]}',
        f'    accent:    {color_scheme["accent"]}',
        f'  ============================================================',
        f'-->',
        "",
        f'<svg xmlns="http://www.w3.org/2000/svg"',
        f'     width="{cw}" height="{ch}"',
        f'     viewBox="0 0 {cw} {ch}">',
        "",
    ]

    # 背景
    lines.append(f'  <!-- 背景画布 -->')
    lines.append(f'  <rect width="100%" height="100%" '
                 f'fill="{color_scheme["background"]}" />')
    lines.append("")

    # 递归渲染每个顶层节点
    for root in svg_tree:
        _render_node(root, 0, 0, lines, depth=1)

    lines.append("")
    lines.append('</svg>')

    svg_content = "\n".join(lines)

    # 处理 <layoutText> 自动换行
    svg_content = _process_layout_text(svg_content)

    # 保存至 outputs/
    output_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "outputs",
    )
    os.makedirs(output_dir, exist_ok=True)

    filename = os.path.join(output_dir, f"{ts}.svg")

    with open(filename, "w", encoding="utf-8") as f:
        f.write(svg_content)

    return os.path.normpath(filename)


def _render_node(node, parent_abs_x, parent_abs_y, lines, depth=1):
    """递归渲染一个 region 节点

    translate 组同时包裹本节点 SVG 内容和子节点递归，
    确保坐标变换正确级联到所有子层。

    每个节点生成:
      <g id="region_id">
        <g transform="translate(rel_x, rel_y)">
          ...svg_content...
          <!-- 子节点在此 translate 组内部，继承坐标偏移 -->
          <g id="child">
            <g transform="translate(child_rel_x, child_rel_y)">
              ...child_svg...
            </g>
          </g>
        </g>
      </g>
    """
    indent = "  " * depth
    rid = node.get("region_id", "?")

    # 计算相对父节点的偏移
    rel_x = node["abs_x"] - parent_abs_x
    rel_y = node["abs_y"] - parent_abs_y

    lines.append(f'{indent}<!-- region: {rid} '
                 f'({node["abs_x"]},{node["abs_y"]}) '
                 f'[{node["abs_w"]}x{node["abs_h"]}] -->')
    lines.append(f'{indent}<g id="{rid}">')

    svg = node.get("svg_content", "")
    has_children = bool(node.get("children"))

    if svg.strip() or has_children:
        # 单个 translate 组同时包裹本节点内容 + 子节点，
        # 确保坐标变换正确级联到所有子层
        lines.append(f'{indent}  <g transform="translate({rel_x}, {rel_y})">')

        if svg.strip():
            for svg_line in svg.strip().split("\n"):
                if svg_line.strip():
                    lines.append(f'{indent}    {svg_line.strip()}')
                else:
                    lines.append("")

        # 递归渲染子节点（在 translate 组内部，继承坐标偏移）
        for child in node.get("children", []):
            lines.append("")
            _render_node(child, node["abs_x"], node["abs_y"],
                         lines, depth + 2)

        lines.append(f'{indent}  </g>')

    lines.append(f'{indent}</g>')


# ============================================================
#  layoutText 处理（自动换行）
# ============================================================

_font_cache = {}


def _process_layout_text(svg_content: str) -> str:
    """处理 <layoutText> 自定义标签，替换为多个 <text> 实现自动换行

    支持属性:
        x, y: 起始坐标
        width: 最大行宽（换行阈值，px）
        font-size: 字号（px）
        fill: 颜色（默认 #333333）
        line-height: 行高倍数（默认 1.5）
        font-weight: 字重 normal/bold（默认 normal）
        text-anchor: start/middle/end（默认 start）
    """

    def _replace_match(match):
        attrs_str = match.group(1)
        text = match.group(2)

        # 解析属性
        attrs = {}
        for key, value in re.findall(r'([\w-]+)=["\'](.*?)["\']', attrs_str):
            attrs[key] = value

        x = float(attrs.get("x", 0))
        y = float(attrs.get("y", 0))
        max_width = float(attrs.get("width", 200))
        font_size = float(attrs.get("font-size", 16))
        fill = attrs.get("fill", "#333333")
        line_height = float(attrs.get("line-height", 1.5))
        font_weight = attrs.get("font-weight", "normal")
        text_anchor = attrs.get("text-anchor", "start")

        line_spacing = font_size * line_height
        font = _get_font(int(font_size), font_weight)

        # 拆分为多行
        lines = _split_text_to_lines(text, max_width, font_size, font)
        if not lines:
            lines = [""]

        # 生成 <text> 元素
        result_lines = []
        for i, line_text in enumerate(lines):
            line_y = y + i * line_spacing
            parts = [f'<text x="{x}" y="{line_y}"']
            parts.append(f' font-size="{font_size}px"')
            parts.append(f' fill="{fill}"')
            if font_weight == "bold":
                parts.append(' font-weight="bold"')
            if text_anchor != "start":
                parts.append(f' text-anchor="{text_anchor}"')
            parts.append(f">{_escape_xml(line_text)}</text>")
            result_lines.append("".join(parts))

        return "\n" + "\n".join(result_lines)

    pattern = r"<layoutText\s+(.*?)>(.*?)</layoutText>"
    return re.sub(pattern, _replace_match, svg_content, flags=re.DOTALL)


def _get_font(font_size: int, font_weight: str = "normal"):
    """加载中文字体（缓存），返回 PIL ImageFont 或 None"""
    cache_key = (font_size, font_weight)
    if cache_key in _font_cache:
        return _font_cache[cache_key]

    try:
        from PIL import ImageFont

        if font_weight == "bold":
            paths = [
                r"C:\Windows\Fonts\msyhbd.ttc",
                r"C:\Windows\Fonts\msyh.ttc",
                r"C:\Windows\Fonts\simhei.ttf",
                r"C:\Windows\Fonts\simsun.ttc",
            ]
        else:
            paths = [
                r"C:\Windows\Fonts\msyh.ttc",
                r"C:\Windows\Fonts\simsun.ttc",
                r"C:\Windows\Fonts\simhei.ttf",
            ]

        for path in paths:
            if os.path.exists(path):
                try:
                    font = ImageFont.truetype(path, font_size)
                    _font_cache[cache_key] = font
                    return font
                except Exception:
                    continue
    except Exception:
        pass

    _font_cache[cache_key] = None
    return None


def _split_text_to_lines(text: str, max_width: float,
                         font_size: int, font) -> list:
    """按指定宽度将文本拆分为多行（字符级贪心算法）"""
    lines = []
    for paragraph in text.split("\n"):
        if not paragraph:
            lines.append("")
            continue

        current = ""
        for char in paragraph:
            test = current + char
            if _get_text_width(test, font_size, font) > max_width and current:
                lines.append(current)
                current = char
            else:
                current = test

        if current:
            lines.append(current)

    return lines


def _get_text_width(text: str, font_size: int, font) -> float:
    """获取文本宽度，优先使用 PIL，无字体时 fallback 估算"""
    if font:
        try:
            bbox = font.getbbox(text)
            return bbox[2] - bbox[0]
        except Exception:
            pass
    # Fallback：CJK ≈ 1.0×font_size, ASCII ≈ 0.6×font_size
    width = 0.0
    for ch in text:
        if "\u4e00" <= ch <= "\u9fff" or "\u3000" <= ch <= "\u303f":
            width += font_size * 1.0
        else:
            width += font_size * 0.6
    return width


def _escape_xml(text: str) -> str:
    """转义 XML 特殊字符"""
    text = text.replace("&", "&amp;")
    text = text.replace("<", "&lt;")
    text = text.replace(">", "&gt;")
    text = text.replace('"', "&quot;")
    text = text.replace("'", "&apos;")
    return text
