# CascadeSVG: 基于多智能体层叠式架构的 SVG 信息图生成系统

## 1. 系统总览

### 1.1 设计理念

将 SVG 生成拆解为 6 个专业化节点，每个节点作为独立的 LLM Agent 负责单一子任务，
通过结构化 JSON 进行节点间通信。采用"决策 -> 执行 -> 修正"的分层递进模式。

| 节点 | 角色 | 职责 |
|------|------|------|
| 设计节点 | 理解需求 | 将用户请求转化为描述文本和主旨标签 |
| 转译节点 | 规划布局 | 确定层叠结构、配色、基准尺寸 |
| 模板节点 | 定义样式 | 生成可复用的 SVG 模板片段 |
| 生成节点 | 填充内容 | 后序递归 + 兄弟协同生成完整 svg_tree |
| 修正节点 | 质量检查 | 边界越界修正 + 7 项质量检查 |
| 渲染器 | 拼装输出 | svg_tree -> 完整 SVG 文件 |

### 1.2 流水线流程

```
用户请求
  -> 设计节点 -> {description, themes, canvas_hint}
  -> 转译节点 -> {cascade_structure, color_scheme, region_descriptions, ...}
  -> [预检#1] -> 验证层叠结构合法性（可选重试上游）
  -> 模板节点 -> {templates}
  -> [预检#2] -> 验证模板完整性（可选重试上游）
  -> [生成节点] -> 后序递归 + 兄弟节点协同生成 svg_tree
  -> [中间SVG] -> 渲染修正前的原始画面（供对比）
  -> 修正节点 -> 第1轮：边界越界修正 | 第2轮：质量检查
  -> 渲染器 -> 最终 SVG 文件
```

### 1.3 回退路径

| 触发条件 | 回退目标 | 处理方式 |
|----------|----------|----------|
| 预检#1 失败 | 重试转译节点 | 错误信息附加到输入中重新生成 |
| 预检#2 失败 | 重试模板节点 | 错误信息附加到输入中重新生成 |
| 最多重试 3 次 | - | 超过则终止流水线 |

---

## 2. 核心设计原则

### 2.1 层叠结构（Cascade Structure）

- 嵌套的 region 树，每个 region 有百分比定位和样式标签
- 父 region 包含子 region，形成视觉上的容器嵌套关系
- 转译节点将"横向"的信息流（文字描述）转化为"竖向"的结构（层叠树）
- 所有 position 使用小数百分比（范围 0.0~1.0，允许溢出）

### 2.2 百分比定位

| 项目 | 规则 |
|------|------|
| 画布尺寸 | 整数像素（转译节点定夺） |
| 区域内位置 | 小数百分比（0.0 ~ 1.0） |
| 坐标换算 | 生成节点将百分比转为绝对像素坐标 |

### 2.3 软策略：基准大小（Grid Unit + Base Font Size）

- 转译节点输出 base_font_size 和 grid_unit
- grid_unit：空间最小增量单位（如 8px），规范间距和对齐
- base_font_size：正文标准字号，标题等以此为基准缩放
- 这不是代码硬性校验，而是通过提示词传递给 LLM 的空间尺度参考

### 2.4 软策略：信息密度约束

生成节点提示词中要求 LLM 自检：
- 高度 <= 200px 的区域：至少 3 个视觉元素
- 高度 > 200px 的区域：至少 4-5 个元素，垂直覆盖 >= 60%
- 修正节点的质量检查包含密度检查作为第二道防线

### 2.5 禁画区规则（半软约束）

若某区域有子区域，则子区域占据的矩形范围为"禁画区"：
- 父容器不得在禁画区内绘制任何内容
- 父容器只能绘制：背景矩形、子区域间隙中的连接元素、子区域上方的标题
- 属于半软约束，LLM 不一定完全遵守

### 2.6 主题色体系

由转译节点生成，包含主色、辅色、背景色、文本色、强调色，传递给所有下游节点。

---

## 3. 节点详述

### 3.1 设计节点（Design Node）

**文件**: `nodes/design_node.py`
**函数**: `design_node(user_request) -> dict`

#### 输入
- 用户自然语言请求（如"大语言模型的基本原理"）

#### 输出（结构化 JSON）
```json
{
  "description": "这张图展示了大语言模型的基本原理...",
  "themes": ["结构性", "科技感", "层次分明"],
  "canvas_hint": {
    "suggested_ratio": "16:9",
    "min_width": 800,
    "min_height": 450
  }
}
```

#### 职责
- 理解用户意图，提取核心概念和主旨标签
- 确定画面比例和风格方向
- 输出传递给所有下游节点作为全局上下文

---

### 3.2 转译节点（Translation Node）

**文件**: `nodes/translation_node.py`
**函数**: `translation_node(design_output) -> dict`

#### 输入
| 字段 | 来源 |
|------|------|
| description | 设计节点 |
| themes | 设计节点 |
| canvas_hint | 设计节点 |

#### 输出（结构化 JSON）
```json
{
  "canvas": {"width": 1280, "height": 720},
  "base_font_size": 16,
  "grid_unit": 8,
  "color_scheme": {
    "primary": "#1E3A5F",
    "secondary": "#FF6B35",
    "background": "#F5F7FA",
    "text": "#333333",
    "accent": "#FFD700"
  },
  "cascade_structure": [
    {
      "region_id": "header",
      "label": "标题区域",
      "position": {"x": 0, "y": 0, "w": 1.0, "h": 0.15},
      "style_tag": "title-block",
      "children": [...]
    }
  ],
  "region_descriptions": {"header": "顶部标题区域..."},
  "style_descriptions": {"title-block": "标题区域背景块..."}
}
```

#### 关键字段说明
- `cascade_structure`：嵌套 region 树，定义区域层级关系和百分比定位
- `region_descriptions`：每个 region 的内容描述，覆盖所有 region_id
- `style_descriptions`：每个 style_tag 的视觉描述，指导模板生成
- `base_font_size` + `grid_unit`：空间尺度的基准参数（软策略）

---

### 3.3 模板节点（Template Node）

**文件**: `nodes/template_node.py`
**函数**: `template_node(design_output, translation_output) -> dict`

#### 职责
生成可复用的 SVG 模板片段，兄弟姐妹区域可选用相同模板确保风格一致。

#### 输出
```json
{
  "templates": [
    {
      "template_id": "card",
      "style_tag": "content-card",
      "description": "内容卡片模板，带圆角和阴影",
      "svg_template": "<rect .../>...",
      "params": {"width": {"type": "int"}, ...}
    }
  ]
}
```

---

### 3.4 预检脚本（Pre-check）

**文件**: `nodes/precheck.py`

两次预检分别在转译节点和模板节点之后执行，纯代码逻辑（无 LLM 调用）。

#### 预检#1（translation precheck）
- 检查层叠结构是否有区域重叠/超出画布
- 检查 region_id 是否唯一
- 检查配色方案是否完整

#### 预检#2（templates precheck）
- 检查模板结构是否完整
- 检查参数是否匹配
- 检查 SVG 模板是否合法

---

### 3.5 生成节点（Generation Node）

**文件**: `nodes/generation_node.py`
**函数**: `generation_node(design_output, translation_output, templates_output, user_request="") -> dict`

这是整个系统的核心引擎。

#### 后序递归生成策略

入口函数 `_sib_gen_node(node)` 的执行流程：
1. 若当前节点无子节点，直接返回（叶子节点优先）
2. 否则，先递归每个子节点：`_sib_gen_node(child)`
3. 子节点全部生成完毕后，再批量生成当前节点的所有子节点

这样保证：叶子节点先生成 -> 子节点 SVG 先存在 -> 父节点生成时知道子节点位置和内容摘要。

#### 兄弟节点协同生成（Sibling Co-generation）

同一父节点下的所有兄弟姐妹区域在单次 LLM 调用中同时生成：
- 确保视觉一致性（边框、圆角、阴影等风格参数统一）
- 允许交换尺寸和位置信息，避免视觉冲突
- N 次 LLM 调用减少为 1 次

#### 父子节点信息传递三层

| 方向 | 内容 | 作用 |
|------|------|------|
| 父 -> 子 | region_descriptions | 告诉子节点"在这个区域应该画什么" |
| 子 -> 父 | content_summary（40-60字） | 告诉父节点"我画了什么、用了什么颜色" |
| 子 -> 父 | 关键坐标 | 子节点的精确像素位置，用于在间隙中绘制连接线 |

#### 重试机制
- JSON 解析失败时最多重试 3 次
- 每次重试将错误信息加入提示词

#### 输出
```json
{
  "svg_tree": [
    {
      "region_id": "header",
      "x": 0, "y": 0, "w": 1280, "h": 108,
      "svg_content": "<rect .../>...",
      "content_summary": "标题区域使用深蓝渐变背景...",
      "children": [...]
    }
  ],
  "llm_call_count": 5
}
```

---

### 3.6 修正节点（Correction Node）

**文件**: `nodes/correction_node.py`
**函数**: `correction_node(generation_output, translation_output, design_output=None) -> dict`

解决层叠式生成的固有缺陷——单向前馈、无自我修正能力。

#### 第1轮：边界越界修正（条件执行）
- 遍历 svg_tree，对每个有 svg_content 的节点运行 _precheck_boundary()
- 检测元素坐标是否越出区域边界
- 对有违规的区域，LLM 一次性批量修正坐标和尺寸
- 修正后再次验证，直到无违规

#### 第2轮：质量检查（始终执行）
LLM 检查以下 7 项：
1. 信息密度 - 区域空间是否被充分利用
2. 排版 - 文字位置和字号层级是否合理
3. 对比度 - 前景色与背景色是否利于阅读
4. 遮盖 - 元素之间是否有重叠
5. 父级与子级对齐 - 连接线是否进入子区域禁画区
6. 父容器重复内容 - 父容器是否绘制了子节点已有的内容
7. 视觉平衡 - 整体布局是否协调

#### 重要保护
- 禁止将自定义 <layoutText> 标签替换为 <text>
- 禁止删除现有 <layoutText> 元素

#### 输出
```json
{
  "fixed_count": 3,
  "llm_call_count": 2,
  "fixes": {"region_id": "修正说明"}
}
```

---

### 3.7 渲染器（Renderer）

**文件**: `nodes/renderer.py`
**函数**: `renderer(translation_output, generation_output) -> str`

#### 职责
纯代码模块（非 LLM）。将 svg_tree 递归拼装为完整 SVG 文档。

#### 处理流程
1. 递归遍历 svg_tree，每个节点的 svg_content 在父级的 `<g transform="translate(x, y)">` 组内渲染
2. 坐标变换正确级联到所有子层
3. 处理自定义 <layoutText> 标签的自动换行逻辑（通过 PIL 计算字符宽度）
4. 保存完整 .svg 文件到 outputs/ 目录

#### 返回
生成的 SVG 文件路径（字符串）。

---

## 4. 项目文件结构

```
CascadeSVG/
  +-- pipeline.py           # 流水线编排器，串联所有节点
  +-- main.py               # 入口脚本（解析 --req 参数）
  +-- llm_utils.py          # LLM API 调用封装 + 调用计数 + Token 统计
  +-- logger.py             # 结构化日志 + 计时器 + 文件日志
  +-- example.py            # 测试用例管理器
  +-- compare.py            # 对照组：单次 LLM 调用生成 SVG
  +-- CLAUDE.md             # 项目说明
  +-- structure.md          # 本文档
  +-- config/
  |   +-- api_key.json      # LLM API 配置
  +-- nodes/
  |   +-- design_node.py       # 设计节点
  |   +-- translation_node.py  # 转译节点
  |   +-- template_node.py     # 模板节点
  |   +-- precheck.py          # 预检脚本
  |   +-- generation_node.py   # 生成节点（核心）
  |   +-- correction_node.py   # 修正节点
  |   +-- renderer.py          # 渲染器
  +-- outputs/              # SVG 输出 + 日志文件
  +-- report/               # 实验报告
```

---

## 5. Token 消耗与统计

### 5.1 Token 计数机制

- 所有 LLM 调用的 token 消耗通过 API 返回的 usage 字段精确统计
- `reset_llm_token_usage()`：重置全局计数器
- `get_llm_token_usage()`：获取累计消耗
- `snapshot_token_delta()`：计算两次快照之间的增量

### 5.2 流水线统计

pipeline.py 在每个节点后输出：
```
[TIME] 14:30:25 [设计节点] Token: 0+358(11%) (输入=280, 输出=78)
[TIME] 14:30:35 [转译节点] Token: 358+3552(56%) (输入=2800, 输出=752)
```

最终输出汇总：
```
Token 消耗汇总:
  设计节点:    358  (1.0%)
  转译节点:  3,552  (10.0%)
  模板节点:  1,250  (3.5%)
  生成节点: 23,950  (67.2%)
  修正节点:  6,521  (18.3%)
  ============================
  总计:     35,631
```

---

## 6. 对照组设计

**文件**: `compare.py`

### 实现
- 单次 LLM 调用直接生成完整 SVG
- 最小提示词：仅描述输出格式要求（直接输出 SVG，不包裹 JSON）
- 不提供布局规格、配色方案或设计约束
- 不经过修正节点

### 对比指标
- 视觉质量（布局、色彩、内容完整度）
- Token 消耗（单次 vs 多节点总消耗）
- 修正效果（修正前后对比）
- 不同 LLM 后端的表现差异

---

## 7. 运行方式

```bash
# CascadeSVG 层叠式生成
conda run -n nlp2 python main.py --req "大语言模型的基本原理"

# 对照组：单次调用生成
conda run -n nlp2 python compare.py --req "大语言模型的基本原理"
```

### 测试用例
1. 大语言模型的基本原理
2. 通俗易懂地解释词向量（Word Embedding）的基本概念
3. 中山大学的发展历程
4. 绘制 SVG 流程图，展示从一颗咖啡豆到一杯咖啡的完整生产链
5. YouTube has 10 times more videos than TikTok, TikTok has 2 times more than Kuaishou
6. [自选] 在 Minecraft Java Edition 中怪物生成和消失的范围展示

---

## 8. 核心发现

层叠式多节点架构的收益与底层 LLM 的能力呈负相关：
- **模型较弱时**：架构红利显著，任务分解降低认知负荷
- **模型较强时**：收益递减，信息衰减成为主要制约因素

具体数据、分析和图表见 `report/report.tex`。
