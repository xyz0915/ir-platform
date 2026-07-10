#!/usr/bin/env python3
"""IR Platform 一键启动编排器（跨平台，纯标准库，无第三方依赖）。

职责：
  1. bootstrap 后端 venv + 依赖（新机 clone 也能跑）
  2. bootstrap 前端 node_modules（缺失则 npm install）
  3. 启动前后端子进程（后端走 backend/run.py，自动 load_dotenv 读取 backend/.env）
  4. 转发子进程日志（加 [BACKEND]/[FRONTEND] 前缀）
  5. 收到 SIGINT/SIGTERM 优雅关闭两个子进程

入口路径全部基于本脚本位置派生，不依赖当前工作目录。
"""
from __future__ import annotations

import argparse
import os
import platform
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BACKEND = ROOT / "backend"
FRONTEND = ROOT / "frontend"

VENV_DIR = BACKEND / "venv"
DEPS_MARKER = BACKEND / ".ir_deps_installed"

IS_WINDOWS = platform.system() == "Windows"

FRONTEND_PORT = 5173


def venv_python() -> Path:
    if IS_WINDOWS:
        return VENV_DIR / "Scripts" / "python.exe"
    return VENV_DIR / "bin" / "python"


def venv_pip() -> Path:
    if IS_WINDOWS:
        return VENV_DIR / "Scripts" / "pip.exe"
    return VENV_DIR / "bin" / "pip"


# --------------------------------------------------------------------------
# 跨平台端口清理（供 --restart 使用）
# --------------------------------------------------------------------------
def kill_port(port: int) -> None:
    """杀掉占用指定 TCP 端口的进程；解析失败静默忽略，不阻断启动。"""
    try:
        if IS_WINDOWS:
            out = subprocess.run(
                ["netstat", "-ano"], capture_output=True, text=True
            ).stdout
            for line in out.splitlines():
                if f":{port} " in line:
                    pid = line.split()[-1]
                    if pid.isdigit():
                        subprocess.run(
                            ["taskkill", "/F", "/PID", pid],
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL,
                        )
        else:
            out = subprocess.run(
                ["lsof", "-ti", f"tcp:{port}"],
                capture_output=True,
                text=True,
            ).stdout
            for pid in out.split():
                pid = pid.strip()
                if pid:
                    subprocess.run(
                        ["kill", "-9", pid],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
    except Exception as exc:  # 端口查询工具缺失/解析异常都不应阻断启动
        print(f"[启动器] 清理端口 {port} 时出错（已忽略）: {exc}", flush=True)


# --------------------------------------------------------------------------
# 后端 bootstrap + 启动
# --------------------------------------------------------------------------
def bootstrap_backend() -> None:
    venv_created = False
    if not VENV_DIR.exists():
        print("[启动器] 未检测到后端 venv，正在创建虚拟环境 ...", flush=True)
        subprocess.run(
            [sys.executable, "-m", "venv", str(VENV_DIR)], check=True
        )
        venv_created = True

    if venv_created or not DEPS_MARKER.exists():
        pip = venv_pip()
        print("[启动器] 安装后端依赖 (pip install -r requirements.txt) ...", flush=True)
        install_env = {
            **os.environ,
            "PYTHONUTF8": "1",
            "PYTHONIOENCODING": "utf-8",
        }
        try:
            subprocess.run(
                [str(pip), "install", "-r", str(BACKEND / "requirements.txt")],
                cwd=str(BACKEND),
                env=install_env,
                check=True,
            )
            DEPS_MARKER.touch()
        except subprocess.CalledProcessError as exc:
            print(f"[启动器] 后端依赖安装失败（请检查网络/镜像源）: {exc}", flush=True)
            raise
    else:
        print("[启动器] 后端依赖已就绪，跳过安装。", flush=True)


def start_backend(host: str, port: int) -> "subprocess.Popen | None":
    py = venv_python()
    if not py.exists():
        print(f"[启动器] 未找到后端解释器: {py}（依赖安装可能失败），跳过后端启动。", flush=True)
        return None

    print(f"[启动器] 启动后端 -> http://{host}:{port}/docs", flush=True)
    popen_kwargs = dict(
        cwd=str(BACKEND),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
    )
    if IS_WINDOWS:
        popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        popen_kwargs["start_new_session"] = True
    return subprocess.Popen([str(py), "run.py"], **popen_kwargs)


# --------------------------------------------------------------------------
# 前端 bootstrap + 启动
# --------------------------------------------------------------------------
def bootstrap_frontend() -> None:
    if (FRONTEND / "node_modules").exists():
        print("[启动器] 前端依赖已就绪，跳过 npm install。", flush=True)
        return
    print("[启动器] 未检测到前端 node_modules，正在 npm install ...", flush=True)
    try:
        subprocess.run(
            "npm install",
            cwd=str(FRONTEND),
            shell=True,
            env={**os.environ, "PYTHONUTF8": "1"},
            check=True,
        )
    except subprocess.CalledProcessError as exc:
        print(f"[启动器] 前端 npm install 失败（请确认已安装 Node 18+）: {exc}", flush=True)
        raise


def start_frontend() -> "subprocess.Popen | None":
    pkg = FRONTEND / "package.json"
    if not pkg.exists():
        print(f"[启动器] 未找到前端项目: {pkg}，跳过前端启动。", flush=True)
        return None

    print(f"[启动器] 启动前端 -> http://localhost:{FRONTEND_PORT}", flush=True)
    # shell=True：Windows 经 cmd 解析 npm.cmd，POSIX 经 sh 解析 npm
    return subprocess.Popen(
        "npm run dev",
        cwd=str(FRONTEND),
        shell=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
    )


# --------------------------------------------------------------------------
# 日志转发
# --------------------------------------------------------------------------
def _pipe_reader(stream, prefix: str) -> None:
    try:
        for line in iter(stream.readline, ""):
            if not line:
                break
            print(f"{prefix} {line.rstrip()}", flush=True)
    except Exception:
        pass


def forward_logs(proc: "subprocess.Popen | None", prefix: str) -> None:
    if proc is None:
        return
    for stream in (proc.stdout, proc.stderr):
        if stream is not None:
            threading.Thread(
                target=_pipe_reader, args=(stream, prefix), daemon=True
            ).start()


# --------------------------------------------------------------------------
# 优雅退出
# --------------------------------------------------------------------------
_shutdown = threading.Event()


def terminate_child(proc: "subprocess.Popen | None") -> None:
    if proc is None or proc.poll() is not None:
        return
    try:
        if IS_WINDOWS:
            subprocess.run(
                ["taskkill", "/F", "/PID", str(proc.pid)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        else:
            import os as _os

            _os.killpg(_os.getpgid(proc.pid), signal.SIGTERM)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass


def handle_signal(signum, _frame) -> None:
    print("\n[启动器] 收到退出信号，正在关闭服务 ...", flush=True)
    _shutdown.set()


# --------------------------------------------------------------------------
# 主流程
# --------------------------------------------------------------------------
def main() -> None:
    parser = argparse.ArgumentParser(description="IR Platform 一键启动编排器")
    parser.add_argument("--restart", action="store_true", help="先杀掉 8000/5173 再启动")
    parser.add_argument("--no-backend", action="store_true", help="不启动后端")
    parser.add_argument("--no-frontend", action="store_true", help="不启动前端")
    parser.add_argument("--host", default="0.0.0.0", help="后端监听地址（默认 0.0.0.0）")
    parser.add_argument("--port", type=int, default=8000, help="后端监听端口（默认 8000）")
    args = parser.parse_args()

    if args.restart:
        print("[启动器] --restart：清理已占用端口 ...", flush=True)
        kill_port(args.port)
        kill_port(FRONTEND_PORT)

    backend_proc: "subprocess.Popen | None" = None
    frontend_proc: "subprocess.Popen | None" = None

    try:
        if not args.no_backend:
            bootstrap_backend()
            backend_proc = start_backend(args.host, args.port)
            forward_logs(backend_proc, "[BACKEND]")

        if not args.no_frontend:
            try:
                bootstrap_frontend()
                frontend_proc = start_frontend()
                forward_logs(frontend_proc, "[FRONTEND]")
            except subprocess.CalledProcessError:
                frontend_proc = None

        signal.signal(signal.SIGINT, handle_signal)
        signal.signal(signal.SIGTERM, handle_signal)

        print("\n" + "=" * 56, flush=True)
        print("  IR Platform 启动完成", flush=True)
        if backend_proc is not None:
            print(f"  后端:  http://localhost:{args.port}/docs", flush=True)
        if frontend_proc is not None:
            print(f"  前端:  http://localhost:{FRONTEND_PORT}", flush=True)
        print("  Ctrl+C 优雅退出", flush=True)
        print("=" * 56 + "\n", flush=True)

        while not _shutdown.is_set():
            time.sleep(0.5)
    finally:
        terminate_child(backend_proc)
        terminate_child(frontend_proc)
        sys.exit(0)


if __name__ == "__main__":
    main()
