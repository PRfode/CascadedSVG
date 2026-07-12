"""
纯 LLM API 调用工具
使用固定系统提示词，无 RAG 检索。
"""

import os
from openai import OpenAI

# ============ 配置 ============
LLM_MODEL_NAME = "deepseek-v4-flash"
DEEPSEEK_API_KEY = os.getenv("NLP_HW_DEEKSEEK_API_KEY", None)
if DEEPSEEK_API_KEY is None:
    raise ValueError("请在环境变量中设置 NLP_HW_DEEKSEEK_API_KEY")

client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url="https://api.deepseek.com")

# 固定系统提示词（可根据需要修改）
SYSTEM_PROMPT = "你是一个乐于助人的助手。"

# ============ API 调用函数 ============
def ask_llm(question: str) -> str:
    """发送用户问题给 LLM，返回回答"""
    response = client.chat.completions.create(
        model=LLM_MODEL_NAME,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": question},
        ],
        stream=False,
    )
    return response.choices[0].message.content

# ============ 交互式入口 ============
if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("LLM 对话系统就绪（输入 exit 退出）")
    print("=" * 60)

    while True:
        user_input = input("\n⇩ 问: ").strip()
        if user_input.lower() in ("exit", "quit", "q"):
            print("· 关闭...")
            break
        if not user_input:
            continue

        answer = ask_llm(user_input)
        print(f"⇨ 答: {answer}")