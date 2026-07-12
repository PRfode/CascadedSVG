"""
CascadeSVG Logger

结构化日志输出，格式统一为：
  时间 | [级别] | 节点名称: 内容

兼容 Windows GBK 编码，所有输出使用 ASCII-only 字符。

支持同时输出到控制台和文件。
"""
import sys
import time
import os
from datetime import datetime


class Logger:
    """结构化日志输出工具"""

    def __init__(self, stream=sys.stdout):
        self._stream = stream
        self._node_name = "系统"
        self._start_time = None
        self._last_ts = None
        self._log_file = None  # 文件句柄，用于同步写入

    # ============ 文件日志 ============

    def open_log_file(self, timestamp: str) -> str:
        """打开日志文件，后续所有输出同步写入该文件

        Args:
            timestamp: 时间戳字符串（如 20250708_143022）

        Returns:
            str: 日志文件绝对路径
        """
        log_dir = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "outputs", "logs",
        )
        os.makedirs(log_dir, exist_ok=True)
        log_path = os.path.join(log_dir, f"{timestamp}.log")
        self._log_file = open(log_path, "w", encoding="utf-8")
        self._raw(f"CascadeSVG 日志 | {timestamp}")
        self._raw("=" * 50)
        return os.path.normpath(log_path)

    def close_log_file(self):
        """关闭日志文件"""
        if self._log_file:
            self._log_file.close()
            self._log_file = None

    # ============ 节点标记 ============

    def set_node(self, name: str):
        """设置当前节点名称，后续所有日志使用此名称"""
        self._node_name = name

    # ============ 时间戳 ============

    def _ts(self) -> str:
        """返回当前时间字符串 (HH:MM:SS)"""
        return datetime.now().strftime("%H:%M:%S")

    # ============ 核心输出 ============

    def _write(self, level: str, text: str):
        """写入格式化日志行（控制台 + 文件）"""
        ts = self._ts()
        line = f"{ts} | [{level}] | {self._node_name}: {text}"
        print(line, file=self._stream)
        if self._log_file:
            self._log_file.write(line + "\n")
            self._log_file.flush()

    def _raw(self, text: str):
        """写入无格式行（用于分隔线等，控制台 + 文件）"""
        ts = self._ts()
        line = f"{ts} | {text}"
        print(line, file=self._stream)
        if self._log_file:
            self._log_file.write(line + "\n")
            self._log_file.flush()

    # ============ 级别方法 ============

    def raw(self, text: str):
        """输出无格式行（无时间/级别/节点前缀，控制台 + 文件）"""
        print(text, file=self._stream)
        if self._log_file:
            self._log_file.write(text + "\n")
            self._log_file.flush()

    def info(self, key: str, value: str = ""):
        """输出信息"""
        msg = f"{key}: {value}" if value else key
        self._write("INFO", msg)

    def ok(self, text: str):
        """成功"""
        self._write("OK", text)

    def fail(self, text: str):
        """失败"""
        self._write("FAIL", text)

    def warn(self, text: str):
        """警告"""
        self._write("WARNING", text)

    def stub(self, text: str = ""):
        """桩模块"""
        msg = text if text else "待实现"
        self._write("STUB", msg)

    def retry(self, target: str):
        """回退/重试"""
        self._write("RETRY", f"-> 回退到 {target}")

    # ============ 结构化输出 ============

    def kv(self, key: str, value):
        """键值对（缩进格式）"""
        self._write("INFO", f". {key} = {value}")

    def input_summary(self, text: str):
        """输入摘要"""
        if len(text) > 80:
            self._write("INFO", f"输入: {text[:80]}...")
        else:
            self._write("INFO", f"输入: {text}")

    def attempt(self, current: int, total: int, context: str = ""):
        """重试尝试"""
        msg = f"尝试 ({current}/{total})"
        if context:
            msg += f" - {context}"
        self._write("INFO", msg)

    def timer_report(self, label: str = "耗时"):
        """耗时报告"""
        if self._start_time is None:
            elapsed = "?.?s"
        else:
            elapsed = f"{time.time() - self._start_time:.1f}s"
        self._write("TIME", f"{label}: {elapsed}")

    def dict_summary(self, d: dict, indent: int = 1, max_val_len: int = 60):
        """字典摘要"""
        prefix = "  " * indent
        for k, v in d.items():
            if isinstance(v, dict):
                self._write("INFO", f"{prefix}{k}: ...")
                self.dict_summary(v, indent + 1, max_val_len)
            elif isinstance(v, list):
                self._write("INFO", f"{prefix}{k}: [{len(v)} items]")
            else:
                s = str(v)
                if len(s) > max_val_len:
                    s = s[:max_val_len] + "..."
                self._write("INFO", f"{prefix}{k}: {s}")

    # ============ 计时器 ============

    def timer_start(self):
        """开始计时"""
        self._start_time = time.time()

    def timer_elapsed(self) -> str:
        """返回经过时间"""
        if self._start_time is None:
            return "?.?s"
        return f"{time.time() - self._start_time:.1f}s"

    # ============ 版式输出 ============

    def banner(self, text: str):
        """大标题"""
        self._raw(f"  {text}")

    def section(self, text: str):
        """阶段标题"""
        self._raw("")
        self._raw(f">> {text}")

    def subsection(self, text: str):
        """子标题"""
        self._raw(f"  [{text}]")

    def blank(self):
        """空行"""
        self._raw("")


# ============ 全局单例 ============

logger = Logger()
