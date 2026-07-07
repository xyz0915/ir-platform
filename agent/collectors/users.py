"""2. 用户信息采集器."""

import logging
from typing import Any

from collectors.base_collector import BaseCollector
from utils.platform import is_windows, is_linux, run_command, read_file_lines_safe

logger = logging.getLogger(__name__)


class UsersCollector(BaseCollector):
    """用户信息采集器.

    采集用户列表、UID、主目录、最后登录时间、管理员权限、禁用状态.
    """

    name = "users"
    platform = ["windows", "linux"]

    def collect(self) -> list:
        """执行用户信息采集."""
        if is_windows():
            return self._collect_windows()
        elif is_linux():
            return self._collect_linux()
        return []

    def _collect_windows(self) -> list:
        """Windows 用户信息采集."""
        users = []
        # 使用 net user 获取本地用户列表
        output = run_command("net user")
        if output:
            lines = output.split("\n")
            # net user 输出格式：前几行是标题，最后几行是统计
            for line in lines[4:]:
                line = line.strip()
                if not line or "命令成功完成" in line or "The command completed" in line:
                    break
                # 每行可能有多个用户名
                for username in line.split():
                    if username and not username.startswith("-"):
                        user_info = self._get_windows_user_detail(username)
                        users.append(user_info)
        return users

    def _get_windows_user_detail(self, username: str) -> dict:
        """获取 Windows 单个用户详情."""
        output = run_command(f'net user "{username}"')
        info: dict[str, Any] = {
            "username": username,
            "uid": None,
            "home_dir": None,
            "last_logon": None,
            "is_admin": False,
            "is_disabled": False,
        }
        if output:
            for line in output.split("\n"):
                line_lower = line.lower().strip()
                if "local group memberships" in line_lower or "本地组成员" in line:
                    if "admin" in line_lower:
                        info["is_admin"] = True
                elif "account active" in line_lower or "帐户启用" in line_lower:
                    if "no" in line_lower or "否" in line_lower:
                        info["is_disabled"] = True
                elif "last logon" in line_lower or "上次登录" in line_lower:
                    parts = line.split(")", 1) if ")" in line else line.split("：", 1)
                    if len(parts) > 1:
                        info["last_logon"] = parts[-1].strip()
        return info

    def _collect_linux(self) -> list:
        """Linux 用户信息采集."""
        users = []
        lines = read_file_lines_safe("/etc/passwd")
        for line in lines:
            if line.startswith("#") or not line.strip():
                continue
            parts = line.split(":")
            if len(parts) >= 7:
                username = parts[0]
                uid = self._safe_int(parts[2])
                home_dir = parts[5]
                shell = parts[6]

                # 跳过系统用户（UID < 1000 且非 root）和 nologin 用户
                info = {
                    "username": username,
                    "uid": uid,
                    "home_dir": home_dir,
                    "last_logon": self._get_last_logon_linux(username),
                    "is_admin": uid == 0 or self._is_sudoer(username),
                    "is_disabled": shell in ("/bin/false", "/usr/sbin/nologin", "/sbin/nologin"),
                }
                users.append(info)
        return users

    def _get_last_logon_linux(self, username: str) -> str:
        """获取 Linux 用户最后登录时间."""
        output = run_command(f"lastlog -u {username} 2>/dev/null", timeout=5)
        if output:
            lines = output.strip().split("\n")
            if len(lines) >= 2:
                parts = lines[1].split()
                if len(parts) >= 4 and "Never" not in lines[1]:
                    return " ".join(parts[3:])
        return ""

    def _is_sudoer(self, username: str) -> bool:
        """检查用户是否有 sudo 权限."""
        output = run_command(f"groups {username} 2>/dev/null", timeout=5)
        if output:
            if "sudo" in output or "wheel" in output or "admin" in output:
                return True
        return False

    def _safe_int(self, value: str) -> int:
        """安全转换为整数."""
        try:
            return int(value)
        except (ValueError, TypeError):
            return 0
