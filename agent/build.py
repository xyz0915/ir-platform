#!/usr/bin/env python3
"""PyInstaller 打包脚本 — 将 Agent 打包为单文件可执行程序.

Usage:
    python build.py              # 打包当前平台版本
    python build.py --platform windows  # 指定平台
"""

import argparse
import platform
import subprocess
import sys
from pathlib import Path


def build(platform_name: str = None) -> None:
    """执行 PyInstaller 打包.

    Args:
        platform_name: 目标平台 (windows/linux)，默认为当前平台.
    """
    if platform_name is None:
        platform_name = "windows" if platform.system() == "Windows" else "linux"

    agent_dir = Path(__file__).resolve().parent
    spec_file = agent_dir / "agent.spec"

    print(f"Building Agent for {platform_name}...")

    # PyInstaller 命令 — 使用 spec 文件，所有配置已在 spec 中定义
    # PyInstaller 不允许 .spec 文件与 --hidden-import 等选项同时使用
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--clean",
        "--noconfirm",
        str(spec_file),
        "--distpath", str(agent_dir / "dist"),
        "--workpath", str(agent_dir / "build"),
    ]

    print(f"Command: {' '.join(cmd)}")

    try:
        result = subprocess.run(cmd, check=True, cwd=str(agent_dir))
        print(f"\nBuild successful! Output in: {agent_dir / 'dist'}")
    except subprocess.CalledProcessError as exc:
        print(f"\nBuild failed: {exc}")
        sys.exit(1)


def main() -> None:
    """主入口."""
    parser = argparse.ArgumentParser(description="IR Agent PyInstaller 打包脚本")
    parser.add_argument(
        "--platform", "-p",
        choices=["windows", "linux"],
        default=None,
        help="目标平台（默认当前平台）",
    )
    args = parser.parse_args()
    build(args.platform)


if __name__ == "__main__":
    main()
