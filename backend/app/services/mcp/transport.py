"""MCP 传输层 — stdio / sse 抽象与实现（MVP-2 真实传输）.

提供：
  - MCPTransport：抽象基类，定义 list_tools / call_tool 接口。
  - StdioTransport：本地子进程实现，通过 subprocess + JSON-RPC 通信。
  - SSETransport：远程端点的 HTTP+SSE 实现，通过 urllib.request 通信。
  - get_transport(server)：按 server.transport 选择实现的工厂。
"""

import json
import logging
import select
import subprocess
import threading
import time
import urllib.request
import urllib.error
from abc import ABC, abstractmethod
from typing import Any, Optional

from app.models.mcp import McpServer
from app.services.mcp.protocol import build_request, parse_response

logger = logging.getLogger(__name__)

# 默认超时（秒）
_DEFAULT_TIMEOUT = 30


class MCPTransport(ABC):
    """MCP 传输层抽象基类。"""

    def __init__(self, server: dict) -> None:
        self.server = server

    @abstractmethod
    def connect(self) -> None:
        """建立传输连接（spawn 子进程 / 建立 HTTP 会话）。"""
        raise NotImplementedError

    @abstractmethod
    def list_tools(self) -> list[dict]:
        """列出远端服务器提供的工具 schema。"""
        raise NotImplementedError

    @abstractmethod
    def call_tool(self, name: str, args: dict) -> Any:
        """调用远端工具。"""
        raise NotImplementedError

    @abstractmethod
    def disconnect(self) -> None:
        """断开并清理资源。"""
        raise NotImplementedError


class StdioTransport(MCPTransport):
    """stdio 传输（本地子进程）— 通过 subprocess.Popen + JSON-RPC 通信。"""

    def __init__(self, server: dict) -> None:
        super().__init__(server)
        self._process: Optional[subprocess.Popen] = None
        self._lock = threading.Lock()

    def connect(self) -> None:
        """通过 subprocess.Popen 启动 MCP 服务器进程。"""
        command = self.server.get("command", "")
        args_json = self.server.get("args_json", "[]")
        if isinstance(args_json, str):
            args_list = json.loads(args_json) if args_json else []
        else:
            args_list = list(args_json) if args_json else []

        cmd = [command] + args_list
        logger.info("StdioTransport connecting: %s", " ".join(cmd))

        try:
            self._process = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
        except FileNotFoundError as exc:
            raise RuntimeError(f"MCP 服务器命令不存在: {command}") from exc
        except OSError as exc:
            raise RuntimeError(f"启动 MCP 服务器失败: {exc}") from exc

        logger.info("StdioTransport connected (PID=%d)", self._process.pid)

    def list_tools(self) -> list[dict]:
        """发送 JSON-RPC "tools/list" 请求，返回工具 schema 列表。"""
        request_str = build_request("tools/list", {})
        response_str = self._send_and_receive(request_str)
        result = parse_response(response_str)
        tools = result if isinstance(result, list) else result.get("tools", [])
        logger.info("StdioTransport.list_tools: %d tools returned", len(tools))
        return tools

    def call_tool(self, name: str, args: dict) -> Any:
        """发送 JSON-RPC "tools/call" 请求，返回调用结果。"""
        params = {"name": name, "arguments": args}
        request_str = build_request("tools/call", params)
        response_str = self._send_and_receive(request_str)
        result = parse_response(response_str)
        logger.info("StdioTransport.call_tool(%s): completed", name)
        return result

    def disconnect(self) -> None:
        """终止子进程并清理资源。"""
        proc = self._process
        if proc is None:
            return
        logger.info("StdioTransport disconnecting (PID=%d)", proc.pid)
        try:
            proc.terminate()
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            logger.warning("StdioTransport 进程 %d 未在 5s 内终止，强制 kill", proc.pid)
            try:
                proc.kill()
                proc.wait(timeout=2)
            except Exception as exc:
                logger.error("StdioTransport 强制 kill 失败: %s", exc)
        except Exception as exc:
            logger.warning("StdioTransport disconnect 异常: %s", exc)
        finally:
            self._process = None

    def _send_and_receive(self, request_str: str) -> str:
        """写入请求到 stdin，从 stdout 读取一行响应。

        超时控制：使用 threading 做读超时兜底（Windows select 不支持 pipes）。

        Returns:
            原始响应字符串（单行）。

        Raises:
            RuntimeError: 进程未运行、写入失败、读超时、进程异常退出.
        """
        proc = self._process
        if proc is None or proc.stdin is None or proc.stdout is None:
            raise RuntimeError("StdioTransport 未连接")

        with self._lock:
            # 检查进程是否仍在运行
            if proc.poll() is not None:
                stderr_output = ""
                try:
                    stderr_output = (proc.stderr.read() if proc.stderr else "")
                except Exception:
                    pass
                raise RuntimeError(
                    f"MCP 服务器进程已退出 (returncode={proc.returncode}): {stderr_output}"
                )

            # 写入请求
            try:
                proc.stdin.write(request_str + "\n")
                proc.stdin.flush()
            except BrokenPipeError as exc:
                raise RuntimeError("MCP 服务器 stdin 管道已关闭") from exc
            except OSError as exc:
                raise RuntimeError(f"写入 stdin 失败: {exc}") from exc

            # 读取响应（带超时兜底）
            response_str = self._read_line_with_timeout(proc.stdout, timeout=_DEFAULT_TIMEOUT)

        if response_str is None:
            # 尝试读取 stderr 获取错误信息
            stderr_output = ""
            try:
                stderr_output = (proc.stderr.read() if proc.stderr else "")
            except Exception:
                pass
            raise RuntimeError(
                f"MCP 服务器读取响应超时（{_DEFAULT_TIMEOUT}s）"
                + (f". stderr: {stderr_output}" if stderr_output else "")
            )

        return response_str.strip()

    @staticmethod
    def _read_line_with_timeout(stream, timeout: int) -> Optional[str]:
        """从流中读取一行，带超时控制。

        Windows 上 select 不支持 pipes，改用 threading 做超时兜底。
        """
        result: list[Optional[str]] = [None]

        def reader() -> None:
            try:
                line = stream.readline()
                result[0] = line
            except Exception:
                pass

        thread = threading.Thread(target=reader, daemon=True)
        thread.start()
        thread.join(timeout=timeout)

        if thread.is_alive():
            # 超时：线程仍在运行，放弃读取
            return None

        return result[0]


class SSETransport(MCPTransport):
    """SSE 传输（远程端点）— 通过 HTTP POST + JSON-RPC 通信。"""

    def __init__(self, server: dict) -> None:
        super().__init__(server)
        self._base_url: str = ""
        self._timeout: int = _DEFAULT_TIMEOUT

    def connect(self) -> None:
        """初始化 HTTP 会话（连接懒初始化，仅校验 url 配置）。"""
        self._base_url = (self.server.get("url") or "").rstrip("/")
        if not self._base_url:
            raise ValueError("SSETransport 缺少 url 配置")
        logger.info("SSETransport connecting to: %s", self._base_url)

    def list_tools(self) -> list[dict]:
        """HTTP POST 到 {url}/tools/list，返回工具 schema 列表。"""
        url = f"{self._base_url}/tools/list"
        response_data = self._http_post(url, {})
        tools = response_data if isinstance(response_data, list) else response_data.get("tools", [])
        logger.info("SSETransport.list_tools: %d tools returned", len(tools))
        return tools

    def call_tool(self, name: str, args: dict) -> Any:
        """HTTP POST 到 {url}/tools/call，返回调用结果。"""
        url = f"{self._base_url}/tools/call"
        body = {"name": name, "arguments": args}
        result = self._http_post(url, body)
        logger.info("SSETransport.call_tool(%s): completed", name)
        return result

    def disconnect(self) -> None:
        """关闭 HTTP 会话（清理资源）。"""
        logger.info("SSETransport disconnected from: %s", self._base_url)
        self._base_url = ""

    def _http_post(self, url: str, body: dict) -> Any:
        """发送 HTTP POST 请求并解析 JSON 响应。

        Args:
            url: 目标 URL.
            body: 请求体字典.

        Returns:
            响应中的 data/result 字典.

        Raises:
            RuntimeError: HTTP 请求失败或响应格式错误.
        """
        data_bytes = json.dumps(body, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data_bytes,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                raw = resp.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            error_body = ""
            try:
                error_body = exc.read().decode("utf-8", errors="replace")
            except Exception:
                pass
            raise RuntimeError(
                f"HTTP {exc.code} from {url}: {error_body or exc.reason}"
            ) from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"请求 {url} 失败: {exc.reason}") from exc
        except OSError as exc:
            raise RuntimeError(f"请求 {url} 异常: {exc}") from exc

        try:
            response = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"无效 JSON 响应来自 {url}: {exc}") from exc

        return response.get("result") or response


def get_transport(server: dict) -> MCPTransport:
    """按 server.transport 选择传输实现。

    transport='stdio' → StdioTransport；transport='sse' → SSETransport。
    """
    transport = (server or {}).get("transport", "stdio")
    if transport == "sse":
        return SSETransport(server)
    return StdioTransport(server)
