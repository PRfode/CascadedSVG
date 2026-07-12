"""
CascadeSVG 主流水线（Pipeline）

将 SVG 生成拆解为以下流程：
  设计节点 -> 转译节点 -> [预检#1] -> 模板节点 -> [预检#2]
  -> 后序递归生成节点树 -> [中间 SVG] -> 修正节点 -> 渲染器

回退路径：
  预检#1 失败 -> 重试转译节点
  预检#2 失败 -> 重试模板节点
"""

import sys
import os
import time
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from logger import logger
from llm_utils import reset_llm_call_count, get_llm_call_count, reset_llm_token_usage, get_llm_token_usage, snapshot_token_delta
from nodes.design_node import design_node
from nodes.translation_node import translation_node
from nodes.template_node import template_node
from nodes.precheck import precheck_translation, precheck_templates
from nodes.generation_node import generation_node
from nodes.correction_node import correction_node
from nodes.renderer import renderer


MAX_RETRIES = 3

# 累积各节点 token 明细（每轮流水线重置）
_node_token_details = []


class Pipeline:
    """CascadeSVG 流水线编排器"""

    def __init__(self):
        self.context = {}
        self.total_llm_calls = 0
        self._timestamp = ""

    def run(self, user_request: str) -> dict:
        """运行完整流水线"""
        # 重置全局 LLM 计数器
        global _node_token_details
        reset_llm_call_count()
        reset_llm_token_usage()
        _node_token_details = []
        self.context = {}
        self.total_llm_calls = 0

        # 生成时间戳（用于日志和 SVG 文件名）
        self._timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        log_path = logger.open_log_file(self._timestamp)
        logger.info("Log", log_path)

        try:
            self._run_pipeline(user_request)
        except Exception as e:
            logger.fail(f"流水线异常: {type(e).__name__}: {e}")
            logger.close_log_file()
            raise

        logger.close_log_file()
        return self.context

    def _run_pipeline(self, user_request: str):
        """实际的流水线逻辑（被 run() 的 try/finally 包裹）"""
        logger.banner("CascadeSVG 流水线开始")
        logger.input_summary(user_request)

        # 初始化 token 快照基线
        snapshot_token_delta()

        # ============================================================
        # 阶段 ①：设计节点
        # ============================================================
        logger.set_node("设计节点")
        logger.section("阶段 1/5  设计节点")
        logger.info("输入", user_request)
        logger.timer_start()

        design_output = design_node(user_request)
        self.context["design"] = design_output

        logger.info("description", design_output["description"])
        logger.info("themes", ", ".join(design_output["themes"]))
        ch = design_output["canvas_hint"]
        logger.info("canvas_hint",
                     f"比例={ch['suggested_ratio']}, "
                     f"最小={ch['min_width']}x{ch['min_height']}")
        logger.timer_report("设计节点完成")
        _log_token_delta()

        # ============================================================
        # 阶段 2~3：规划阶段
        # ============================================================

        # ---------- 转译节点 ----------
        logger.set_node("转译节点")
        logger.section("阶段 2/5  转译节点")

        translation_errors = ""
        trans_success = False
        for attempt in range(1, MAX_RETRIES + 1):
            logger.attempt(attempt, MAX_RETRIES)
            if translation_errors:
                logger.info("附加", f"预检失败反馈 ({len(translation_errors)} chars)")
            logger.info("输入", f"description={design_output['description']} + "
                       f"themes=[{', '.join(design_output['themes'])}]")
            logger.timer_start()
            try:
                translation_output = translation_node(
                    design_output, extra_context=translation_errors,
                    user_request=user_request,
                )
                self.context["translation"] = translation_output

                # 预检脚本 #1
                logger.set_node("预检#1")
                logger.subsection("预检脚本 #1")
                check1 = precheck_translation(translation_output)
                self.context["precheck1"] = check1

                if check1["passed"]:
                    cv = translation_output["canvas"]
                    logger.info("画布",
                                 f"{cv['width']}x{cv['height']}, "
                                 f"基准字号={translation_output['base_font_size']}, "
                                 f"网格单位={translation_output['grid_unit']}")
                    cascade = translation_output["cascade_structure"]
                    logger.info("层叠结构",
                                 f"{len(cascade)} 个顶层区域")
                    _print_cascade_summary(cascade)
                    sd = translation_output.get("style_descriptions", {})
                    if sd:
                        logger.info("样式描述", f"{len(sd)} 个 style_tag")
                        for tag, desc in sd.items():
                            logger.kv(tag, desc)
                    rd = translation_output.get("region_descriptions", {})
                    if rd:
                        logger.info("区域描述", f"{len(rd)} 个 region 描述")
                        for rid, desc in rd.items():
                            logger.raw(f"         - [{rid}] {desc}")
                    logger.ok("预检 #1 通过")
                    for w in check1["warnings"]:
                        logger.warn(w)
                    logger.timer_report("转译节点完成")
                    _log_token_delta()
                    trans_success = True
                    break
                else:
                    logger.fail("预检 #1 失败")
                    for e in check1["errors"]:
                        logger.fail(f"  - {e}")
                    translation_errors = "; ".join(check1["errors"])
                    logger.info("重试转译节点")
            except ValueError as e:
                logger.fail(f"验证失败: {e}")
                if attempt < MAX_RETRIES:
                    translation_errors = str(e)
                    logger.info("重试转译节点")
                else:
                    raise
            except Exception as e:
                import traceback
                logger.fail(f"代码异常: {e}")
                for line in traceback.format_exc().splitlines():
                    logger.fail(line)
                raise

        if not trans_success:
            raise RuntimeError(f"转译节点重试 {MAX_RETRIES} 次后仍失败")

        # ---------- 模板节点 ----------
        logger.set_node("模板节点")
        logger.section("阶段 3/5  模板节点")

        template_errors = ""
        tmpl_success = False
        for attempt in range(1, MAX_RETRIES + 1):
            logger.attempt(attempt, MAX_RETRIES)
            if template_errors:
                logger.info("附加", f"预检失败反馈 ({len(template_errors)} chars)")
            logger.info("输入", f"主题色={translation_output['color_scheme']['primary']}")
            logger.timer_start()
            try:
                templates_output = template_node(
                    design_output, translation_output,
                    extra_context=template_errors
                )
                self.context["templates"] = templates_output

                # 预检脚本 #2
                logger.set_node("预检#2")
                logger.subsection("预检脚本 #2")
                check2 = precheck_templates(translation_output, templates_output)
                self.context["precheck2"] = check2

                if check2["passed"]:
                    tmpls = templates_output["templates"]
                    logger.info("模板数", str(len(tmpls)))
                    for tmpl in tmpls:
                        logger.kv(tmpl["template_id"], tmpl["description"])
                    logger.ok("预检 #2 通过")
                    for w in check2["warnings"]:
                        logger.warn(w)
                    logger.timer_report("模板节点完成")
                    _log_token_delta()
                    tmpl_success = True
                    break
                else:
                    logger.fail("预检 #2 失败")
                    for e in check2["errors"]:
                        logger.fail(f"  - {e}")
                    template_errors = "; ".join(check2["errors"])
                    logger.info("重试模板节点")
            except ValueError as e:
                logger.fail(f"验证失败: {e}")
                if attempt < MAX_RETRIES:
                    template_errors = str(e)
                    logger.info("重试模板节点")
                else:
                    raise
            except Exception as e:
                import traceback
                logger.fail(f"代码异常: {e}")
                for line in traceback.format_exc().splitlines():
                    logger.fail(line)
                raise

        if not tmpl_success:
            raise RuntimeError(f"模板节点重试 {MAX_RETRIES} 次后仍失败")

        # ============================================================
        # 阶段 ⑤：生成节点（递归多层）
        # ============================================================
        logger.set_node("生成节点")
        logger.section("阶段 4/5  生成节点")
        logger.timer_start()

        cascade = translation_output["cascade_structure"]
        tmpl_count = len(templates_output["templates"])
        logger.info("输入",
                     f"{_count_all_regions(cascade)} 个 region（{len(cascade)} 个顶层）"
                     f" + {tmpl_count} 个模板")

        try:
            generation_output = generation_node(
                design_output, translation_output, templates_output,
                user_request=user_request,
            )
        except ValueError as e:
            logger.fail(f"生成失败: {e}")
            raise
        except Exception as e:
            import traceback
            logger.fail(f"生成代码异常: {e}")
            for line in traceback.format_exc().splitlines():
                logger.fail(line)
            raise

        self.context["generation"] = generation_output

        gen_llm_count = generation_output["llm_call_count"]
        logger.info("LLM 调用次数", str(gen_llm_count))
        logger.timer_report("生成节点完成")
        _log_token_delta()

        # ============================================================
        # Extra：修正节点
        # ============================================================
        logger.set_node("修正节点")
        logger.section("Extra  修正节点")

        # 修正前渲染中间 SVG（保留修正前的原始画面）
        try:
            mid_svg = renderer(translation_output, generation_output,
                               timestamp=f"{self._timestamp}_mid")
            logger.info("中间 SVG", mid_svg)
        except Exception as e:
            logger.warn(f"中间 SVG 渲染失败: {e}")

        logger.timer_start()

        try:
            correction_output = correction_node(
                generation_output, translation_output,
                design_output=self.context.get("design"),
            )
        except Exception as e:
            import traceback
            logger.fail(f"修正异常: {e}")
            for line in traceback.format_exc().splitlines():
                logger.fail(line)
            # 修正节点失败不应阻塞主流水线
            correction_output = {"fixed_count": 0, "llm_call_count": 0, "fixes": {}}

        self.context["correction"] = correction_output

        if correction_output["fixed_count"] > 0:
            logger.info("修正区域数", str(correction_output["fixed_count"]))
        logger.timer_report("修正节点完成")
        _log_token_delta()

        # ============================================================
        # 阶段 ⑤：渲染器
        # ============================================================
        logger.set_node("渲染器")
        logger.section("阶段 5/5  渲染器")
        logger.timer_start()

        try:
            svg_path = renderer(translation_output, generation_output,
                                timestamp=self._timestamp)
        except Exception as e:
            import traceback
            logger.fail(f"渲染异常: {e}")
            for line in traceback.format_exc().splitlines():
                logger.fail(line)
            raise

        self.context["svg_output"] = svg_path

        logger.ok(f"SVG 已保存: {svg_path}")
        logger.timer_report("渲染器完成")

        # 总 LLM 调用次数
        total = get_llm_call_count()
        self.total_llm_calls = total
        token_usage = get_llm_token_usage()
        logger.banner(f"流水线执行完毕 → {svg_path}")
        logger.banner(f"LLM 总调用次数: {total} | "
                       f"Token 总计: {token_usage['total']} "
                       f"(提示={token_usage['prompt']}, "
                       f"生成={token_usage['completion']})")
        _print_token_summary()

def _log_token_delta():
    """输出当前节点的 token 增量消耗"""
    new_total = get_llm_token_usage()["total"]
    delta = snapshot_token_delta()
    prev_total = new_total - delta["total"]
    pct = round(delta["total"] / new_total * 100) if new_total > 0 else 0
    logger.info("Token",
                 f"{prev_total}+{delta['total']}({pct}%) "
                 f"(输入={delta['prompt']}, 输出={delta['completion']})")
    # 累计到节点明细
    _node_token_details.append(
        (logger._node_name, delta["total"], delta["prompt"], delta["completion"]))


def _print_token_summary():
    """输出各节点 token 占比汇总"""
    details = _node_token_details
    if not details:
        return
    total = sum(d[1] for d in details)
    if total == 0:
        return
    parts = []
    for name, tok, inp, out in details:
        pct = round(tok / total * 100)
        parts.append(f"{name}={tok}({pct}%)")
    logger.banner("Token 分布: " + " | ".join(parts))


def main():
    """交互式入口"""
    logger.blank()
    logger.info("CascadeSVG - 级联 LLM 驱动的 SVG 生成系统")
    logger.info("-" * 40)
    logger.info("输入您想要的 SVG 图形描述，流水线将逐层生成。")
    logger.info("输入 'exit' 退出。")
    logger.blank()

    pipeline = Pipeline()

    while True:
        try:
            user_input = input(">> ").strip()
        except (EOFError, KeyboardInterrupt):
            logger.blank()
            logger.info("关闭...")
            break

        if user_input.lower() in ("exit", "quit", "q"):
            logger.info("关闭...")
            break
        if not user_input:
            continue

        try:
            pipeline.run(user_input)
        except Exception as e:
            logger.blank()
            logger.fail(f"流水线异常: {type(e).__name__}: {e}")


# ============================================================
#  辅助函数
# ============================================================

def _count_all_regions(cascade: list) -> int:
    """递归统计所有 region 数量"""
    count = 0
    for r in cascade:
        count += 1
        if r.get("children"):
            count += _count_all_regions(r["children"])
    return count


def _print_cascade_summary(regions: list, indent: int = 0):
    """打印层叠结构树"""
    for region in regions:
        pos = region.get("position", {})
        prefix = "    " + "  " * indent
        logger.raw(
            f"         {prefix}{region.get('region_id', '?')} "
            f"[{region.get('style_tag', '?')}] "
            f"({pos.get('x', '?')}, {pos.get('y', '?')}) "
            f"[{pos.get('w', '?')}x{pos.get('h', '?')}]"
        )
        if region.get("children"):
            _print_cascade_summary(region["children"], indent + 1)


def _print_generation_tree(tree: list, indent: int = 0):
    """打印生成树结构"""
    for node in tree:
        prefix = "    " + "  " * indent
        summary = node.get("content_summary", "")
        logger.raw(
            f"         {prefix}{node.get('region_id', '?')} "
            f"[{node.get('abs_w', '?')}x{node.get('abs_h', '?')}]"
            f"{ ' - ' + summary if summary else ''}"
        )
        if node.get("children"):
            _print_generation_tree(node["children"], indent + 1)


if __name__ == "__main__":
    main()
