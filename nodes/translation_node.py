"""
转译节点

职责：将设计节点的感性输出转化为具体的布局规划。
定义画布、层叠结构、主题色、基准尺寸。
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from llm_utils import ask_llm_json

# ============ 系统预设 ============

CANVAS_RULES = {
    "min_width": 400,
    "min_height": 300,
    "recommended_ratios": ["4:3", "16:9", "1:1", "3:2"],
}

# ============ 系统提示词 ============

TRANSLATION_NODE_SYSTEM_PROMPT = \
"""你负责将设计理念转化为具体的 SVG 布局规划。

## 你的任务
1. **确定画布尺寸**：根据画布建议和预设规则，确定整数的画布宽高
2. **确定基准尺寸**：根据画布尺寸动态计算基准字体尺寸（整数像素）
3. **确定网格单位**：`网格单位 = 基准尺寸 / 2`
4. **设计主题色**：生成与主旨标签匹配的主题色方案
5. **规划层叠结构**：将画面按**内容逻辑**递归拆分为区域

## 预设
- 画布最小尺寸：400x300，推荐比例 4:3 / 16:9 / 1:1 / 3:2
- 颜色使用十六进制 #RRGGBB

## 输出格式
输出严格的 JSON，结构如下：

{
  "canvas": { "width": 1280, "height": 720 },
  "base_font_size": 16,
  "grid_unit": 8,
  "color_scheme": { "primary":"...", "secondary":"...", "background":"...", "text":"...", "accent":"..." },
  "cascade_structure": [ { "region_id":"...", "label":"...", "position":{"x":0,"y":0,"w":1,"h":1}, "style_tag":"...", "children":[...] } ],
  "style_descriptions": { "style_tag名": "视觉描述" },
  "region_descriptions": { "region_id": "视觉结构+具体内容的描述" }
}

## 字段说明

- canvas.width/height：整数像素，>= 400x300
- base_font_size：整数，画布大→基准大，画布小→基准小
- grid_unit = base_font_size / 2（整数）
- color_scheme：primary, secondary, background, text, accent 五色，兼顾美观和可读性
- region_id：见名知意，如 header, main, step1, footer
- label：简短用途说明，如"标题区域"
- position：相对于父区域的百分比小数 (0.0~1.0)
- style_tag：视觉风格标签，相同外观用相同标签
- children：递归，最多 3 层深度

### style_descriptions
每个 style_tag 的视觉描述：形状、颜色、光影效果。
传递给生成节点作为绘图依据。

### region_descriptions
每个 region_id 的**视觉结构 + 具体内容**描述。
- **必须覆盖所有 region_id**
- 描述两部分：视觉布局（背景/边框/内部排列）+ 具体文字/图形内容
- 内容量要充实，让生成节点能直接照画
- 描述必须包含两部分：
  1. **视觉结构**：背景颜色、边框、圆角、内部元素的大致布局（左中右/上中下）
  2. **具体内容**：结合整张图的主题，说明要展示什么文字或图形
- 格式范例：
  ```
  深蓝灰色背景矩形铺满整个区域，居中放置白色粗体大标题"大语言模型的基本原理"，字体约 28px
  ```
  ```
  浅蓝色卡片区域带蓝色边框和圆角，内部左侧为白色圆角矩形"自注意力子层"，右侧为白色圆角矩形"前馈网络子层"，两者间用蓝色箭头连接，黑色文字标注
  ```
- **禁止**只写"这个是做什么的"而不写"长什么样"。每个描述都要让生成节点无需猜测就知道该怎么画
- 这份描述将直接传递给生成节点作为绘图的唯一依据
- **内容量要充足**：描述中的"具体内容"部分必须包含**足够充实的实际文字和细节**，让生成节点拿到后直接照画就能填满空间
  - 对于卡片类区域（如流程图步骤、时间轴事件）：不能只写"图标+标签"。每个卡片必须包含标题、可视化内容（图标/图形）、至少一行辅助描述文字，三者均匀分布
    例如"种植"卡片不能只写"咖啡树图标+种植"，而要写成"咖啡树图标（绿色树冠+棕色树干）+标题'种植'+说明文字'选择适宜海拔和气候的咖啡豆进行种植'"
  - 概括地说：描述中的实际内容量应至少能填满**该区域 60% 的垂直空间**

### region_descriptions 与 style_descriptions 一致性要求
- **region_descriptions 中的视觉结构描述必须与对应 style_tag 的 style_descriptions 一致**
- 不要在 region_descriptions 中引入与 style_descriptions 矛盾的视觉特征。
  例如 style_descriptions 说"深蓝色背景白色文字"，region_descriptions 就不能说"白色背景"或"白色矩形覆盖"。
- 每个 region 的视觉底色、边框、圆角等由 style_tag 定义，region_descriptions 只需描述**内容布局和具体文本**，
  不要在 region_descriptions 中重复定义与 style_tag 相悖的外观。

### 禁止"分层施工式"表述
- region_descriptions 应当描述**最终视觉效果**，而不是"绘制步骤"。
- **禁止使用**"覆盖""叠加""铺在...之上""在...基础上"等分层施工用语。
- 描述中的每个区域在画面上应当是一个**单一视觉整体**，而不是多个图层的叠加。
- 正确的做法：把"深蓝色 + 圆角 + 白色文字"合并为一句话描述这个区域的外观，
  而不是拆成"深蓝底 → 白圆角矩形盖上去 → 写白字"的施工步骤。

### 视觉层级区分
层叠结构的不同深度应使用不同的 style_tag 类型，避免"万物皆卡片"：

- **容器类样式**（用于深度 0~1 的区域，如 main、left_panel）：
  - 仅纯色背景 + 可选细边框或分割线
  - **不含**圆角、阴影、渐变色、卡片感
  - 这些区域只是"划分空间"，不是"视觉卡片"
  - 范例：`content-bg` 应该只是浅色背景矩形，不要圆角不要阴影

- **内容类样式**（用于深度 2+ 的叶子节点，如卡片、步骤块）：
  - 可以有圆角（rx=6~12）、背景色/渐变色、轻微阴影
  - 这些是真正的"视觉卡片"
  - 多个同类内容卡片应共享同一个 style_tag（如 step-card）

- **标注类样式**（用于纯文字区域）：
  - 无背景、无边框，只有文字
  - 如 footer 区域不要画卡片，单行文字即可

- 以下是推荐的不同层级样式组合：
  | 深度 | 角色 | style_tag 示例 | 视觉特征 |
  |------|------|---------------|----------|
  | 0（根） | 画布 | - | 仅纯色背景，无边框无圆角 |
  | 1 | 分区容器 | content-bg, section-bg | 纯色背景+可选细边框，无圆角无阴影 |
  | 2 | 内容卡片 | step-card, info-card, layer-block | 白/浅色背景+圆角+可选阴影 |
  | 3 | 嵌套内容块 | sub-block, text-block | 纯色底纹或无背景，紧凑排列 |

## 级联关键规则

### 层叠结构是**内容逻辑划分**，不是视觉元素列举
- **每个 region 应当对应一个在内容上自成一体的逻辑分区**
- 不要将一个逻辑分区拆为多个视觉元素 region。
  例如 "header" 是一个 region 而不是 "header-bg" + "header-title" + "header-subtitle"。
  header 内部的标题、副标题等应在生成节点中处理，不单独成区。
- 不要在 cascade 中创建箭头、连线、图标等视觉元素的 region。
  这些由生成节点在父 region 中绘制。例如 main_flow 中的步骤间箭头由 main_flow 生成时处理。
- 同一个 region 在画面上是一个连续的视觉区块。

### style_tag 复用规则
- **相同的视觉风格必须使用相同的 style_tag**。
- 例如 4 个步骤卡片都用 `step-card`，多个文本段落都用 `text-body`。
- 整张图的 style_tag 种类**严格控制在 3~6 个**。
- 如果某个 style_tag 只使用一次，说明你拆分过细——请合并。

### 数量和深度控制
- 单个父节点的子节点数量建议 3~6 个，不超过 8 个
- 层叠结构深度最多 3 层（根→子→孙）
- 整张图的 region 总数建议 8~15 个

### 其他
- 所有 position 使用小数百分比，如 x=0.05 表示距父容器左边界 5% 处
- 子区域的 position 是相对于父区域的百分比
- 区域划分应完整覆盖画布，不要留白（除非设计意图如此）
- **子区域必须在父区域内保留内边距（padding）**：子区域的 position 不应紧贴父区域的边界，至少留 3%~5% 的内边距
  例如父区域的子节点 position.x 不应为 0.0，建议 0.03~0.05；w 不应为 1.0，建议 0.90~0.94
  这样生成节点绘制的内容不会与父容器的边框重叠
- style_tag 应当语义化，让人能理解应该是什么样式（如 title-area, step-card, text-body）
- region_descriptions 要具体、有内容，帮助生成节点理解要生成什么

### 内容与尺寸匹配
- 区域的大小必须与其内容量匹配：文字多→空间大，图示简单→空间小
- 每个区域分配的高度应大致等于：标题空间(约 40px) + 图形空间(约 80~120px) + 说明文字(约 40px/行)
- 例如一个卡片只需要标题+图标+一行说明，高度在 200px 以内足够；超过 300px 必须添加更多内容
- **禁止创建内容撑不满的大区域**。如果实际内容只有少量文字和一个小图标，不应分配超过 200px 的高度
- **垂直覆盖率硬性要求**：每个 region 分配的高度必须是其实际内容所需高度的 1~1.5 倍，极限不超过 2 倍
  - 估算方法：标题(30px) + 图形/图标(100px) + N 行文字(N×20px)，最后乘以 1.2 的间距系数
  - 例如：标题+图标+2行说明 = (30+100+40)×1.2 ≈ 204px。如果分配 400px 就太大了
- 如果 region_descriptions 内容量不足但区域面积很大，必须增加描述中的内容量来填充空间
- **检查标准**：想象将描述的内容画出来，它能覆盖该区域垂直空间的至少 60% 吗？如果不行，要么缩小区域，要么充实描述内容

### 原始需求参考
- 在"用户需求"字段中你会看到用户最初的原始请求
- **请对照原始需求检查设计描述是否覆盖了全部方面**
- 如果设计描述过于聚焦于某个例子而遗漏了其他重要方面，请在布局中补充缺失的内容区域
"""


# ============ 节点实现 ============

def translation_node(design_output: dict, extra_context: str = "",
                     user_request: str = "") -> dict:
    """转译节点：将设计理念转化为具体布局规划

    Args:
        design_output: 设计节点的输出，包含 description, themes, canvas_hint
        extra_context: 重试时附加的错误上下文（预检失败信息）
        user_request: 用户的原始需求（用于对照检查设计描述是否覆盖全面）

    Returns:
        dict: 包含 canvas, base_font_size, grid_unit, color_scheme,
                 cascade_structure, style_descriptions
    """
    description = design_output["description"]
    themes = design_output["themes"]
    canvas_hint = design_output["canvas_hint"]

    user_prompt = f"""请根据以下设计理念，生成 SVG 布局规划。

## 用户需求
{user_request}

## 设计描述
{description}

## 主旨标签
{', '.join(themes)}

## 画布建议
比例: {canvas_hint['suggested_ratio']}
最小尺寸: {canvas_hint['min_width']}x{canvas_hint['min_height']}

## 系统预设
最小尺寸: {CANVAS_RULES['min_width']}x{CANVAS_RULES['min_height']}
推荐比例: {', '.join(CANVAS_RULES['recommended_ratios'])}"""

    if extra_context:
        user_prompt += f"""

## 上一次生成的错误
以下问题需要你修正：
{extra_context}

请确保本次生成不出现上述错误。"""

    user_prompt += "\n\n请生成完整的布局规划 JSON。"

    result = ask_llm_json(TRANSLATION_NODE_SYSTEM_PROMPT, user_prompt)

    # === 输出验证 ===
    _validate_translation_output(result)
    return result


def _validate_translation_output(output: dict):
    """验证转译节点输出的字段完整性和类型"""
    required_fields = ["canvas", "base_font_size", "grid_unit", "color_scheme", "cascade_structure", "style_descriptions", "region_descriptions"]
    for field in required_fields:
        if field not in output:
            raise ValueError(f"转译节点输出缺少必要字段: {field}")

    # style_descriptions 校验
    sd = output["style_descriptions"]
    if not isinstance(sd, dict) or len(sd) == 0:
        raise ValueError("style_descriptions 必须为非空对象")

    # region_descriptions 校验
    rd = output["region_descriptions"]
    if not isinstance(rd, dict) or len(rd) == 0:
        raise ValueError("region_descriptions 必须为非空对象")
    # 检查每个 region_id 是否有描述
    region_ids = set()
    _collect_region_ids(output["cascade_structure"], region_ids)
    missing_rd = region_ids - set(rd.keys())
    if missing_rd:
        raise ValueError(f"region_descriptions 缺少以下 region_id: {', '.join(sorted(missing_rd))}")

    # 画布
    canvas = output["canvas"]
    if not isinstance(canvas, dict) or "width" not in canvas or "height" not in canvas:
        raise ValueError("canvas 必须包含 width 和 height")
    if not isinstance(canvas["width"], (int, float)) or canvas["width"] < 400:
        raise ValueError(f"canvas.width 必须 >= 400，当前: {canvas['width']}")
    if not isinstance(canvas["height"], (int, float)) or canvas["height"] < 300:
        raise ValueError(f"canvas.height 必须 >= 300，当前: {canvas['height']}")

    # 基准尺寸与网格单元
    if not isinstance(output["base_font_size"], (int, float)) or output["base_font_size"] <= 0:
        raise ValueError(f"base_font_size 必须 > 0，当前: {output['base_font_size']}")
    if not isinstance(output["grid_unit"], (int, float)) or output["grid_unit"] <= 0:
        raise ValueError(f"grid_unit 必须 > 0，当前: {output['grid_unit']}")

    # 即使 LLM 生成不一致也可以容忍，但 grid_unit 应当是 base_font_size / 2
    expected_grid = output["base_font_size"] / 2
    if abs(output["grid_unit"] - expected_grid) > 0.5:
        raise ValueError(f"grid_unit ({output['grid_unit']}) 应为 base_font_size/2 ({expected_grid})")

    # 主题色
    color_scheme = output["color_scheme"]
    required_colors = ["primary", "secondary", "background", "text", "accent"]
    for c in required_colors:
        if c not in color_scheme:
            raise ValueError(f"color_scheme 缺少颜色: {c}")

    # 层叠结构
    cascade = output["cascade_structure"]
    if not isinstance(cascade, list) or len(cascade) == 0:
        raise ValueError("cascade_structure 必须为非空数组")

    _validate_cascade_structure(cascade)


def _collect_region_ids(regions: list, ids: set):
    """递归收集所有 region_id"""
    for r in regions:
        if "region_id" in r:
            ids.add(r["region_id"])
        if r.get("children"):
            _collect_region_ids(r["children"], ids)


def _validate_cascade_structure(regions: list, path: str = "root"):
    """递归验证层叠结构"""
    for i, region in enumerate(regions):
        for field in ["region_id", "label", "position", "style_tag"]:
            if field not in region:
                raise ValueError(f"{path}[{i}] 缺少字段: {field}")

        pos = region["position"]
        for dim in ["x", "y", "w", "h"]:
            if dim not in pos:
                raise ValueError(f"{path}[{i}].position 缺少维度: {dim}")
            if not isinstance(pos[dim], (int, float)):
                raise ValueError(f"{path}[{i}].position.{dim} 必须为数字")

        if "children" not in region:
            raise ValueError(f"{path}[{i}] 缺少字段: children")
        if not isinstance(region["children"], list):
            raise ValueError(f"{path}[{i}].children 必须为数组")

        # 递归验证子节点
        child_path = f"{path}[{i}].{region.get('region_id', '?')}"
        _validate_cascade_structure(region["children"], child_path)
