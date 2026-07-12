"""
预检规则脚本（纯代码模块，无 LLM 调用）

Pre-check #1：转译节点后 → 模板节点前
  - 字段完整性：canvas / base_font_size / grid_unit / color_scheme
  - 层叠结构有效性：region_id / label / position / style_tag / children
  - 记录所有 region_id 供后续校验

Pre-check #2：模板节点后 → 评审节点前
  - 模板格式检查：template_id / description / params / svg_template
  - 参数类型检查
  - 不再检查 style_tag 覆盖性（模板是可选的视觉积木）
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

VALID_PARAM_TYPES = {"percentage", "color", "grid_unit_multiple", "string", "number"}


# ============================================================
#  Pre-check #1：转译节点输出校验
# ============================================================

def precheck_translation(translation_output: dict) -> dict:
    """对转译节点输出执行预检

    Returns:
        dict: {"passed": bool, "errors": list, "warnings": list}
    """
    errors = []
    warnings = []

    # ---------- 1. 字段完整性 ----------
    required_fields = ["canvas", "base_font_size", "grid_unit", "color_scheme",
                       "cascade_structure", "style_descriptions", "region_descriptions"]
    for field in required_fields:
        if field not in translation_output:
            errors.append(f"缺少必要字段: {field}")

    if errors:
        return _precheck_result(False, errors, warnings)

    # style_descriptions 检查
    sd = translation_output.get("style_descriptions", {})
    if not isinstance(sd, dict) or len(sd) == 0:
        errors.append("style_descriptions 必须为非空对象")

    # region_descriptions 检查
    cascade = translation_output.get("cascade_structure", [])
    rd = translation_output.get("region_descriptions", {})
    if not isinstance(rd, dict) or len(rd) == 0:
        errors.append("region_descriptions 必须为非空对象")
    else:
        region_ids = set()
        _collect_region_ids(cascade, region_ids) if isinstance(cascade, list) else None
        missing_rd = region_ids - set(rd.keys())
        if missing_rd:
            errors.append(f"region_descriptions 缺少以下 region_id: {', '.join(sorted(missing_rd))}")

    # ---------- 2. Canvas 校验 ----------
    canvas = translation_output.get("canvas", {})
    if not isinstance(canvas, dict):
        errors.append("canvas 必须为对象")
    else:
        cw = canvas.get("width", 0)
        ch = canvas.get("height", 0)
        if not isinstance(cw, (int, float)) or cw < 400:
            errors.append(f"canvas.width 无效: {cw}，期望 >= 400")
        if not isinstance(ch, (int, float)) or ch < 300:
            errors.append(f"canvas.height 无效: {ch}，期望 >= 300")

    # ---------- 3. 基准尺寸与网格 ----------
    bfs = translation_output.get("base_font_size")
    if not isinstance(bfs, (int, float)) or bfs <= 0:
        errors.append(f"base_font_size 必须 > 0，当前: {bfs}")

    gu = translation_output.get("grid_unit")
    if not isinstance(gu, (int, float)) or gu <= 0:
        errors.append(f"grid_unit 必须 > 0，当前: {gu}")

    if isinstance(bfs, (int, float)) and isinstance(gu, (int, float)) and bfs > 0 and gu > 0:
        expected_grid = bfs / 2
        if abs(gu - expected_grid) > 0.5:
            warnings.append(f"grid_unit ({gu}) 与 base_font_size/2 ({expected_grid}) 不匹配")

    # ---------- 4. 主题色 ----------
    cs = translation_output.get("color_scheme", {})
    if not isinstance(cs, dict):
        errors.append("color_scheme 必须为对象")
    else:
        required_colors = ["primary", "secondary", "background", "text", "accent"]
        for c in required_colors:
            if c not in cs:
                errors.append(f"color_scheme 缺少颜色: {c}")

    # ---------- 5. 层叠结构 ----------
    cascade = translation_output.get("cascade_structure", [])
    if not isinstance(cascade, list):
        errors.append("cascade_structure 必须为数组")
    elif len(cascade) == 0:
        errors.append("cascade_structure 不能为空")
    else:
        _check_cascade(cascade, errors, warnings)

    # ---------- 6. style_tag 复用警告 ----------
    if isinstance(cascade, list):
        tag_counts = _count_style_tags(cascade)
        single_use = [t for t, c in tag_counts.items() if c == 1]
        if len(single_use) > 0 and len(tag_counts) > 3:
            warnings.append(
                f"以下 style_tag 只使用了一次: {', '.join(single_use)}。"
                f"建议合并或调整，使每个 style_tag 至少使用 2 次"
            )

    return _precheck_result(len(errors) == 0, errors, warnings)


# ============================================================
#  Pre-check #2：模板节点输出校验
# ============================================================

def precheck_templates(translation_output: dict, templates_output: dict) -> dict:
    """对模板节点输出执行预检

    注意：不再检查 style_tag 覆盖性。模板是可选的视觉积木，
    空模板列表是允许的。

    Args:
        translation_output: 转译节点输出
        templates_output: 模板节点输出

    Returns:
        dict: {"passed": bool, "errors": list, "warnings": list}
    """
    errors = []
    warnings = []

    if "templates" not in templates_output:
        errors.append("模板输出缺少字段: templates")
        return _precheck_result(False, errors, warnings)

    templates = templates_output["templates"]
    if not isinstance(templates, list):
        errors.append("templates 必须为数组")
        return _precheck_result(False, errors, warnings)

    # 空模板列表是允许的 — 没有可复用的视觉要素
    if len(templates) == 0:
        return _precheck_result(True, errors, warnings)

    # 模板数量建议
    if len(templates) > 4:
        warnings.append(f"模板数量 {len(templates)} 个，建议控制在 1~4 个")

    # 检查每个模板
    for i, tmpl in enumerate(templates):
        required_fields = ["template_id", "description", "params", "svg_template"]
        for field in required_fields:
            if field not in tmpl:
                errors.append(f"templates[{i}] 缺少字段: {field}")

        # params 检查
        if "params" in tmpl:
            if not isinstance(tmpl["params"], dict) or len(tmpl["params"]) == 0:
                errors.append(f"templates[{i}] params 必须为非空对象")
            else:
                for pname, pdef in tmpl["params"].items():
                    if not isinstance(pdef, dict) or "type" not in pdef:
                        errors.append(f"templates[{i}].params.{pname} 缺少 type")
                    elif pdef["type"] not in VALID_PARAM_TYPES:
                        errors.append(
                            f"templates[{i}].params.{pname} 类型无效: {pdef['type']}"
                        )

    # 注意：不再检查 style_tag 覆盖性
    # 模板是可选的，不要求覆盖所有 region

    return _precheck_result(len(errors) == 0, errors, warnings)


# ============================================================
#  辅助函数
# ============================================================

def _precheck_result(passed: bool, errors: list, warnings: list) -> dict:
    return {"passed": passed, "errors": errors, "warnings": warnings}


def _check_cascade(regions: list, errors: list, warnings: list, path: str = "root"):
    """递归检查层叠结构"""
    for i, region in enumerate(regions):
        region_path = f"{path}[{i}]"
        required = ["region_id", "label", "position", "style_tag", "children"]
        for field in required:
            if field not in region:
                errors.append(f"{region_path} 缺少字段: {field}")

        if "region_id" in region:
            region_path = f"{region_path}.{region['region_id']}"

        # 检查 position
        pos = region.get("position", {})
        if isinstance(pos, dict):
            for dim in ["x", "y", "w", "h"]:
                if dim not in pos:
                    errors.append(f"{region_path}.position 缺少 {dim}")
                elif not isinstance(pos[dim], (int, float)):
                    errors.append(f"{region_path}.position.{dim} 必须为数字")
        else:
            errors.append(f"{region_path}.position 必须为对象")

        # 递归检查子节点
        children = region.get("children", [])
        if isinstance(children, list):
            _check_cascade(children, errors, warnings, region_path)
        else:
            errors.append(f"{region_path}.children 必须为数组")


def _collect_region_ids(regions: list, ids: set):
    """递归收集所有 region_id"""
    for r in regions:
        if isinstance(r, dict):
            if "region_id" in r:
                ids.add(r["region_id"])
            children = r.get("children", [])
            if isinstance(children, list):
                _collect_region_ids(children, ids)


def _count_style_tags(regions: list) -> dict:
    """递归统计每个 style_tag 的使用次数"""
    counts = {}
    _walk_count(regions, counts)
    return counts


def _walk_count(regions: list, counts: dict):
    """递归遍历统计 style_tag 使用次数"""
    for r in regions:
        if isinstance(r, dict) and "style_tag" in r:
            tag = r["style_tag"]
            counts[tag] = counts.get(tag, 0) + 1
        children = r.get("children", [])
        if isinstance(children, list):
            _walk_count(children, counts)
