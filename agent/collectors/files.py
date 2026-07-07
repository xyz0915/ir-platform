"""7. 文件信息采集器."""

import logging
import os
import time
from datetime import datetime, timedelta
from typing import Any

from collectors.base_collector import BaseCollector
from utils.platform import is_windows, is_linux

logger = logging.getLogger(__name__)

# 可疑文件路径模式
SUSPICIOUS_PATHS = [
    r"C:\Users\Public",
    r"C:\Windows\Temp",
    r"C:\Temp",
    "/tmp",
    "/var/tmp",
    "/dev/shm",
]

# 可疑文件扩展名
SUSPICIOUS_EXTENSIONS = [".exe", ".dll", ".bat", ".ps1", ".vbs", ".js", ".jar", ".scr", ".com"]


class FilesCollector(BaseCollector):
    """文件信息采集器.

    采集近期文件、可疑路径文件、临时目录文件.
    """

    name = "files"
    platform = ["windows", "linux"]

    def collect(self) -> dict:
        """执行文件信息采集."""
        return {
            "recent_files": self._get_recent_files(),
            "suspicious_files": self._get_suspicious_files(),
            "temp_files": self._get_temp_files(),
        }

    def _get_recent_files(self) -> list:
        """获取近期修改的文件（24小时内）."""
        recent = []
        cutoff = time.time() - 86400  # 24小时前

        scan_dirs = self._get_scan_dirs()
        for scan_dir in scan_dirs:
            if not os.path.exists(scan_dir):
                continue
            try:
                for root, dirs, files in os.walk(scan_dir):
                    # 限制深度
                    depth = root[len(scan_dir):].count(os.sep)
                    if depth >= 3:
                        dirs[:] = []
                        continue
                    for filename in files:
                        filepath = os.path.join(root, filename)
                        try:
                            stat = os.stat(filepath)
                            if stat.st_mtime > cutoff:
                                recent.append({
                                    "path": filepath,
                                    "size": stat.st_size,
                                    "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                                    "created": datetime.fromtimestamp(stat.st_ctime).isoformat(),
                                })
                        except (OSError, PermissionError):
                            continue
                    # 限制每目录文件数
                    if len(recent) > 500:
                        break
            except (PermissionError, OSError):
                continue
        return recent[:500]

    def _get_suspicious_files(self) -> list:
        """获取可疑路径下的文件."""
        suspicious = []
        for path in SUSPICIOUS_PATHS:
            if not os.path.exists(path):
                continue
            try:
                for root, dirs, files in os.walk(path):
                    depth = root[len(path):].count(os.sep)
                    if depth >= 2:
                        dirs[:] = []
                        continue
                    for filename in files:
                        filepath = os.path.join(root, filename)
                        _, ext = os.path.splitext(filename)
                        if ext.lower() in SUSPICIOUS_EXTENSIONS:
                            try:
                                stat = os.stat(filepath)
                                suspicious.append({
                                    "path": filepath,
                                    "size": stat.st_size,
                                    "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                                    "reason": f"可执行文件在可疑路径: {path}",
                                })
                            except (OSError, PermissionError):
                                continue
                    if len(suspicious) > 200:
                        break
            except (PermissionError, OSError):
                continue
        return suspicious[:200]

    def _get_temp_files(self) -> list:
        """获取临时目录文件."""
        temp_files = []
        temp_dirs = []

        if is_windows():
            import os
            temp_dirs.append(os.environ.get("TEMP", ""))
            temp_dirs.append(os.environ.get("TMP", ""))
            temp_dirs.append(r"C:\Windows\Temp")
        elif is_linux():
            temp_dirs.append("/tmp")
            temp_dirs.append("/var/tmp")

        for temp_dir in temp_dirs:
            if not temp_dir or not os.path.exists(temp_dir):
                continue
            try:
                for filename in os.listdir(temp_dir):
                    filepath = os.path.join(temp_dir, filename)
                    if os.path.isfile(filepath):
                        stat = os.stat(filepath)
                        temp_files.append({
                            "path": filepath,
                            "size": stat.st_size,
                            "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                        })
                    if len(temp_files) > 200:
                        break
            except (PermissionError, OSError):
                continue
        return temp_files[:200]

    def _get_scan_dirs(self) -> list:
        """获取要扫描的目录列表."""
        dirs = []
        if is_windows():
            user_profile = os.environ.get("USERPROFILE", "")
            if user_profile:
                dirs.append(os.path.join(user_profile, "Desktop"))
                dirs.append(os.path.join(user_profile, "Documents"))
                dirs.append(os.path.join(user_profile, "Downloads"))
        elif is_linux():
            home = os.path.expanduser("~")
            dirs.append(os.path.join(home, "Desktop"))
            dirs.append(os.path.join(home, "Documents"))
            dirs.append(os.path.join(home, "Downloads"))
        return [d for d in dirs if os.path.exists(d)]
