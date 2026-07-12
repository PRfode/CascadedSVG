"""
CascadeSVG 入口
级联 LLM 驱动的 SVG 生成系统

使用方式：
    conda activate nlp2
    python main.py --request "大语言模型的基本原理"
"""
import sys
import os
import argparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from llm_utils import LLM_MODEL_NAME
from pipeline import Pipeline
from logger import logger


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="CascadeSVG - 级联 LLM 驱动的 SVG 生成系统")
    parser.add_argument("--req", type=str, default="", help="SVG 图形描述")
    args = parser.parse_args()
    assert args.req, "请输入 SVG 图形描述"

    logger.info(f"API Model: {LLM_MODEL_NAME}")
    
    pipeline = Pipeline()
    try:
        pipeline.run(args.req)
    except Exception as e:
        logger.fail(f"流水线异常: {type(e).__name__}: {e}")
