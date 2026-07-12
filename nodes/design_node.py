"""
设计节点

职责：将用户的自然语言请求翻译为两部分输出：
1. 描述文本（description）：解释最终 SVG 图"要表达什么"的自然语言段落
2. 主旨标签（themes）：从用户需求中提取的结构化形容词列表
3. 画布建议（canvas_hint）：推荐比例和最小尺寸

数据流向：此节点的输出传递给所有下游节点，作为全局上下文。
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from llm_utils import ask_llm_json

# ============ 系统提示词 ============

DESIGN_NODE_SYSTEM_PROMPT = \
"""你是一位"思想家"，负责将用户的自然语言需求转化为 SVG 图形的设计理念。

## 你的角色
你是整个流水线的第一环，用户只告诉你"想要什么"，你需要理解其核心意图，
把模糊的需求转译为清晰的设计方向，你的设计理念将会传达给"制图师"进行具体的设计，随后供后续节点执行。

## 你的任务

### 步骤 1：概念分析
分析用户需求，列出需要解释的**核心概念**（不超过3个，推荐只有1/2个）。
每个核心概念都必须在最终的 SVG 中有对应的可视化区域。

### 步骤 2：设计理念
基于概念分析的结果，为**每个概念**设计对应的可视化表达和对应的文字描述。
确保所有概念都被覆盖，不要遗漏。

### 步骤 3：提取主旨
提取主旨标签（themes），一系列形容词或短词，表达这张图给人的主观感觉/联想。需要不少于4个，推荐不多于8个。
例如：温暖/优雅/科技感/压抑/清新/扁平化等等

### 步骤 4：画布建议
提供画布建议（canvas_hint），包括推荐比例和最小尺寸。

## 输出格式
输出必须是 **严格的 JSON**（不要包含 markdown 代码块标记），包含以下字段：

```json
{
  "description": "自然语言段落，描述SVG要表达的内容",
  "themes": ["标签1", "标签2", "标签3", "标签4"],
  "canvas_hint": {
    "suggested_ratio": "16:9",
    "min_width": 800,
    "min_height": 450
  }
}
```

## 描述规范
- description 必须**先详细阐释本图覆盖的核心概念**，再描述视觉设计
- 确保每个列出的概念在 visual 描述中都有对应的区域来展示
- 如果是"解释X的基本概念"，必须覆盖"X是什么、有什么性质、为什么重要"等多个方面
- 3-5句话。不要求所有概念深度展开，但必须都提到。

## 设计风格要求
- **优先使用扁平化设计**：简洁的几何形状（矩形、圆形、线条）、纯色填充、少量圆角，避免复杂的3D效果、透视、厚重渐变或写实拟物
- **降低图形表达难度**：使用简单的布局（左右分栏、上下分层、卡片式），避免过于复杂的交错结构、大量连线或高密度节点
- **信息层级清晰**：用简洁的色块和文字传递信息，而不是复杂的视觉特效

## 注意事项
- **themes**：结构化形容词/短词列表，4-6个，表达感觉/联想。
  例如：["结构性", "科技感", "蓝色调", "层级分明", "数据密集"]
  又如：["温馨", "暖色调", "家庭感", "柔和", "阳光"]
- **canvas_hint.suggested_ratio**：从 4:3, 16:9, 1:1, 3:2 中选择最适合的比例。
- **canvas_hint.min_width / min_height**：不应小于 400x300。根据内容复杂度适当放大。
"""


# ============ 节点实现 ============

def design_node(user_request: str) -> dict:
    """设计节点：将用户需求转换为设计理念

    Args:
        user_request: 用户的自然语言需求描述

    Returns:
        dict: 包含 description, themes, canvas_hint 的字典
              结构见类文档字符串中的 JSON 示例

    Raises:
        ValueError: 如果 LLM 返回的 JSON 缺少必要字段或类型不正确
    """
    user_prompt = f"用户需求：\n{user_request}\n\n请根据上述用户需求，生成 SVG 设计理念。"
    result = ask_llm_json(DESIGN_NODE_SYSTEM_PROMPT, user_prompt)

    # === 输出验证 ===
    _validate_design_output(result)
    return result


def _validate_design_output(output: dict):
    """验证设计节点输出的字段完整性和类型"""
    required_fields = ["description", "themes", "canvas_hint"]
    for field in required_fields:
        if field not in output:
            raise ValueError(f"设计节点输出缺少必要字段: {field}")

    if not isinstance(output["description"], str) or not output["description"].strip():
        raise ValueError("设计节点输出 description 必须为非空字符串")

    if not isinstance(output["themes"], list) or len(output["themes"]) == 0:
        raise ValueError("设计节点输出 themes 必须为非空数组")

    if not isinstance(output["canvas_hint"], dict):
        raise ValueError("设计节点输出 canvas_hint 必须为对象")

    canvas_hint_fields = ["suggested_ratio", "min_width", "min_height"]
    for field in canvas_hint_fields:
        if field not in output["canvas_hint"]:
            raise ValueError(f"设计节点输出 canvas_hint 缺少字段: {field}")

    ratio = output["canvas_hint"]["suggested_ratio"]
    valid_ratios = ["4:3", "16:9", "1:1", "3:2"]
    if ratio not in valid_ratios:
        raise ValueError(f"不支持的画布比例: {ratio}，有效值: {valid_ratios}")
