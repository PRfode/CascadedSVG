"""
对照组：单次 LLM 调用生成 SVG

与 CascadeSVG 多节点层叠式架构对比，此脚本使用**单次 LLM 调用**
直接生成完整 SVG 文件。

用法:
    conda run -n nlp2 python compare.py --req "大语言模型的基本原理"
"""

import sys
import os
import re
import argparse
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from llm_utils import ask_llm, reset_llm_token_usage, get_llm_token_usage
from logger import logger


# ============================================================
#  系统提示词
# ============================================================

BASELINE_SYSTEM_PROMPT = \
"""你是一个 SVG 信息图生成器。根据用户的需求，直接生成一张完整的 SVG 信息图。

## 输出格式
直接输出原始的 SVG 代码，不要包裹 JSON，不要使用 markdown 代码块标记。
以 `<svg` 开头，以 `</svg>` 结尾。
"""


# ============================================================
#  主函数
# ============================================================

def baseline_generate(user_request: str) -> str:
    """单次 LLM 调用生成 SVG

    Args:
        user_request: 用户需求描述

    Returns:
        str: 生成的 SVG 文件路径
    """
    logger.info("对照组", f"请求: {user_request}")
    logger.info("方法", "单次 LLM 调用（无层叠分解）")

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    reset_llm_token_usage()

    user_prompt = (
        f"请根据以下需求生成一张 SVG 信息图：\n\n"
        f"{user_request}\n\n"
    )

    logger.timer_start()
    try:
        raw_svg = ask_llm(BASELINE_SYSTEM_PROMPT, user_prompt)
    except Exception as e:
        logger.fail(f"LLM 调用失败: {e}")
        raise

    elapsed = logger.timer_elapsed()
    token_usage = get_llm_token_usage()

    # 提取 SVG 代码（去除 markdown 代码块包裹）
    svg_content = raw_svg.strip()
    m = re.search(r'<svg[\s\S]*?</svg>', svg_content, re.IGNORECASE)
    if m:
        svg_content = m.group(0)
    else:
        raise ValueError("LLM 返回内容中未找到 SVG 代码")

    logger.info("SVG 长度", f"{len(svg_content)} 字符")
    logger.info("Token",
                 f"{token_usage['total']} "
                 f"(输入={token_usage['prompt']}, "
                 f"输出={token_usage['completion']})")
    logger.info("耗时", elapsed)

    # 保存 SVG
    output_dir = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "outputs",
    )
    os.makedirs(output_dir, exist_ok=True)

    filename = os.path.join(output_dir, f"baseline_{timestamp}.svg")

    with open(filename, "w", encoding="utf-8") as f:
        f.write(svg_content.strip())

    logger.ok(f"对照组 SVG 已保存: {filename}")
    return os.path.normpath(filename)


# ============================================================
#  入口
# ============================================================

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="对照组：单次 LLM 调用生成 SVG")
    parser.add_argument("--req", type=str, default="", help="SVG 图形描述")
    args = parser.parse_args()
    assert args.req, "请输入 SVG 图形描述（--req）"

    try:
        svg_path = baseline_generate(args.req)
        print(f"\nSVG 文件: {svg_path}")
    except Exception as e:
        logger.fail(f"生成失败: {type(e).__name__}: {e}")
        sys.exit(1)
