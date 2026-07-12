"""
LLM API 调用工具
提供统一的 LLM 调用接口，支持文本和 JSON 响应。

配置来源：config/api_key.json
  {
    "env_var": "NLP_HW_DEEKSEEK_API_KEY",
    "model": "deepseek-v4-flash",
    "api_base": "https://api.deepseek.com"
  }
"""
import os
import json
from openai import OpenAI

# ============ 从配置文件读取 LLM 配置 ============

_CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config", "api_key.json")

if not os.path.exists(_CONFIG_PATH):
    raise FileNotFoundError(
        f"配置文件不存在: {_CONFIG_PATH}\n"
        f"请创建该文件并填入 LLM API 配置。"
    )

with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
    _config = json.load(f)

ENV_VAR_NAME = _config.get("env_var")
LLM_MODEL_NAME = _config.get("model")
API_BASE_URL = _config.get("api_base")

assert ENV_VAR_NAME and LLM_MODEL_NAME and API_BASE_URL, "API配置文件错误"

# 从环境变量读取 API Key
LLM_API_KEY = os.getenv(ENV_VAR_NAME, None)
if LLM_API_KEY is None:
    raise ValueError(
        f"请在环境变量中设置 {ENV_VAR_NAME}\n"
        f"（来自配置文件: {_CONFIG_PATH}）"
    )

# ============ 修复 SSL_CERT_FILE（Windows conda 环境常见问题） ============

_ssl_cert = os.environ.get("SSL_CERT_FILE", "")
if _ssl_cert and not os.path.exists(_ssl_cert):
    import sys
    _conda_prefix = os.path.dirname(os.path.dirname(sys.executable))
    _alt_cert = os.path.join(_conda_prefix, "Library", "ssl", "cacert.pem")
    if os.path.exists(_alt_cert):
        os.environ["SSL_CERT_FILE"] = _alt_cert
    else:
        try:
            import certifi
            os.environ["SSL_CERT_FILE"] = certifi.where()
        except ImportError:
            pass

# ============ 初始化客户端 ============

client = OpenAI(api_key=LLM_API_KEY, base_url=API_BASE_URL)


# ============ 全局 LLM 调用计数器 ============

_llm_call_counter = 0
_llm_token_usage = {"prompt": 0, "completion": 0, "total": 0}
_token_snapshot = {"prompt": 0, "completion": 0, "total": 0}


def reset_llm_call_count():
    """重置 LLM 调用计数器（每次流水线开始时调用）"""
    global _llm_call_counter
    _llm_call_counter = 0


def get_llm_call_count() -> int:
    """返回当前流水线的 LLM 总调用次数"""
    return _llm_call_counter


def reset_llm_token_usage():
    """重置 token 用量统计"""
    global _llm_token_usage, _token_snapshot
    _llm_token_usage = {"prompt": 0, "completion": 0, "total": 0}
    _token_snapshot = {"prompt": 0, "completion": 0, "total": 0}


def get_llm_token_usage() -> dict:
    """返回当前流水线的 token 用量统计

    Returns:
        dict: {"prompt": int, "completion": int, "total": int}
    """
    return dict(_llm_token_usage)


def snapshot_token_delta() -> dict:
    """返回自上次快照以来的 token 增量，并重置快照点

    Returns:
        dict: {"prompt": int, "completion": int, "total": int}
    """
    global _token_snapshot
    current = get_llm_token_usage()
    delta = {
        "prompt": current["prompt"] - _token_snapshot["prompt"],
        "completion": current["completion"] - _token_snapshot["completion"],
        "total": current["total"] - _token_snapshot["total"],
    }
    _token_snapshot = current
    return delta


# ============ API 调用函数 ============

def ask_llm(system_prompt: str, user_prompt: str) -> str:
    """发送消息给 LLM，返回文本回答"""
    global _llm_call_counter, _llm_token_usage
    _llm_call_counter += 1
    response = client.chat.completions.create(
        model=LLM_MODEL_NAME,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        stream=False,
    )

    # 累计 token 用量
    usage = getattr(response, "usage", None)
    if usage:
        _llm_token_usage["prompt"] += usage.prompt_tokens or 0
        _llm_token_usage["completion"] += usage.completion_tokens or 0
        _llm_token_usage["total"] += usage.total_tokens or 0

    return response.choices[0].message.content


def ask_llm_json(system_prompt: str, user_prompt: str) -> dict:
    """发送消息给 LLM，返回解析后的 JSON 对象

    自动处理 LLM 返回 markdown 代码块包裹的情况。
    """
    text = ask_llm(system_prompt, user_prompt)
    return _parse_json_response(text)


def _parse_json_response(text: str) -> dict:
    """从 LLM 响应文本中提取并解析 JSON"""
    text = text.strip()

    if text.startswith("```"):
        lines = text.split("\n")
        if lines[0].startswith("```"):
            lines = lines[1:]
        while lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()

    return json.loads(text)
