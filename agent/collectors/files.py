"""7. 文件信息采集器."""

import hashlib
import logging
import os
import time
from datetime import datetime, timedelta, timezone
from typing import Any

from collectors.base_collector import BaseCollector
from utils.platform import is_windows, is_linux, run_command, get_timestamp

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

# 可计算哈希的 PE 文件扩展名
PE_EXTENSIONS = {".exe", ".dll", ".sys"}

# 签名校验超时（秒）
SIGNATURE_TIMEOUT = 15

# file_hashes 最大采集数
MAX_FILE_HASHES = 50


class FilesCollector(BaseCollector):
    """文件信息采集器.

    采集近期文件、可疑路径文件、临时目录文件，
    以及平台所需的文件哈希（SHA256 + 数字签名）.
    """

    name = "files"
    platform = ["windows", "linux"]

    def collect(self) -> dict:
        """执行文件信息采集."""
        return {
            "recent_files": self._get_recent_files(),
            "suspicious_files": self._get_suspicious_files(),
            "temp_files": self._get_temp_files(),
            "file_hashes": self._get_executable_hashes(),
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
                                    "modified": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
                                    "created": datetime.fromtimestamp(stat.st_ctime, tz=timezone.utc).isoformat(),
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
                                    "modified": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
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
                            "modified": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
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

    def _compute_sha256(self, filepath: str) -> str:
        """计算文件的 SHA256 哈希值.

        Args:
            filepath: 文件路径.

        Returns:
            SHA256 十六进制字符串，读取失败返回空字符串.
        """
        try:
            hasher = hashlib.sha256()
            with open(filepath, "rb") as f:
                while True:
                    chunk = f.read(65536)  # 64KB 块
                    if not chunk:
                        break
                    hasher.update(chunk)
            return hasher.hexdigest()
        except (IOError, OSError, PermissionError) as exc:
            logger.debug("Failed to compute SHA256 for %s: %s", filepath, exc)
            return ""

    def _check_signature(self, filepath: str) -> dict:
        """使用 PowerShell Get-AuthenticodeSignature 校验文件数字签名.

        仅在 Windows 平台有效.

        Args:
            filepath: 文件路径.

        Returns:
            签名信息字典 {"is_signed": 0|1, "signer": str}.
        """
        result: dict[str, Any] = {"is_signed": 0, "signer": ""}
        if not is_windows():
            return result

        # 转义文件路径中的单引号
        escaped_path = filepath.replace("'", "''")
        cmd = (
            f"powershell -NoProfile -Command "
            f"\"Get-AuthenticodeSignature -FilePath '{escaped_path}' "
            f"| Select-Object Status, SignerCertificate | Format-List\""
        )
        output = run_command(cmd, timeout=SIGNATURE_TIMEOUT)
        if not output:
            return result

        status = ""
        signer_lines: list[str] = []
        for line in output.split("\n"):
            line_stripped = line.strip()
            if line_stripped.startswith("Status"):
                parts = line_stripped.split(":", 1)
                if len(parts) > 1:
                    status = parts[1].strip()
            elif line_stripped.startswith("SignerCertificate"):
                parts = line_stripped.split(":", 1)
                if len(parts) > 1:
                    signer_lines.append(parts[1].strip())

        if status and status.lower() in ("valid", "hashmismatch"):
            result["is_signed"] = 1
            # 尝试从 SignerCertificate 后续行提取 Subject
            if signer_lines:
                result["signer"] = signer_lines[0]
            # 尝试从 CN= 提取友好名称
            for line in output.split("\n"):
                stripped = line.strip()
                if "CN=" in stripped:
                    cn_part = stripped.split("CN=", 1)[1]
                    cn_name = cn_part.split(",")[0].strip()
                    if cn_name:
                        result["signer"] = cn_name
                        break

        return result

    def _get_product_info(self, filepath: str) -> dict:
        """读取文件的 ProductName 和 ProductVersion（Windows PE 文件）.

        Args:
            filepath: 文件路径.

        Returns:
            {"product_name": str, "product_version": str}.
        """
        info: dict[str, str] = {"product_name": "", "product_version": ""}
        if not is_windows():
            return info

        escaped_path = filepath.replace("'", "''")
        cmd = (
            f"powershell -NoProfile -Command "
            f"\"(Get-Item '{escaped_path}').VersionInfo "
            f"| Select-Object ProductName, ProductVersion | Format-List\""
        )
        output = run_command(cmd, timeout=10)
        if not output:
            return info

        for line in output.split("\n"):
            stripped = line.strip()
            if stripped.startswith("ProductName"):
                parts = stripped.split(":", 1)
                if len(parts) > 1:
                    info["product_name"] = parts[1].strip()
            elif stripped.startswith("ProductVersion"):
                parts = stripped.split(":", 1)
                if len(parts) > 1:
                    info["product_version"] = parts[1].strip()

        return info

    def _get_executable_hashes(self) -> list:
        """扫描可疑路径中的 .exe/.dll/.sys 文件，计算 SHA256 和签名信息.

        最多采集 MAX_FILE_HASHES 个文件.

        Returns:
            file_hashes 列表，每项包含:
            file_path, file_name, sha256, is_signed, signer,
            file_size, product_name, product_version, collected_at.
        """
        results: list[dict[str, Any]] = []
        now = get_timestamp()

        # 收集所有可扫描的文件
        candidates: list[str] = []
        for path in SUSPICIOUS_PATHS:
            if not os.path.exists(path):
                continue
            try:
                for root, dirs, files in os.walk(path):
                    depth = root[len(path):].count(os.sep)
                    if depth >= 3:
                        dirs[:] = []
                        continue
                    for filename in files:
                        _, ext = os.path.splitext(filename)
                        if ext.lower() in PE_EXTENSIONS:
                            candidates.append(os.path.join(root, filename))
                    if len(candidates) >= MAX_FILE_HASHES:
                        break
            except (PermissionError, OSError):
                continue
            if len(candidates) >= MAX_FILE_HASHES:
                break

        # 还从 temp 目录收集
        temp_dirs = []
        if is_windows():
            temp_dirs.append(os.environ.get("TEMP", ""))
            temp_dirs.append(r"C:\Windows\Temp")
        elif is_linux():
            temp_dirs.extend(["/tmp", "/var/tmp"])

        for temp_dir in temp_dirs:
            if not temp_dir or not os.path.exists(temp_dir):
                continue
            try:
                for filename in os.listdir(temp_dir):
                    filepath = os.path.join(temp_dir, filename)
                    _, ext = os.path.splitext(filename)
                    if os.path.isfile(filepath) and ext.lower() in PE_EXTENSIONS:
                        if filepath not in candidates:
                            candidates.append(filepath)
                    if len(candidates) >= MAX_FILE_HASHES:
                        break
            except (PermissionError, OSError):
                continue
            if len(candidates) >= MAX_FILE_HASHES:
                break

        # 对每个候选文件计算 SHA256 和签名
        for filepath in candidates[:MAX_FILE_HASHES]:
            try:
                stat = os.stat(filepath)
                file_size = stat.st_size
                file_mtime = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat()
            except (OSError, PermissionError):
                continue

            file_name = os.path.basename(filepath)
            sha256_hash = self._compute_sha256(filepath)
            if not sha256_hash:
                continue

            sig_info = self._check_signature(filepath)
            product_info = self._get_product_info(filepath)

            results.append({
                "file_path": filepath,
                "file_name": file_name,
                "sha256": sha256_hash,
                "is_signed": sig_info["is_signed"],
                "signer": sig_info["signer"],
                "file_size": file_size,
                "product_name": product_info["product_name"],
                "product_version": product_info["product_version"],
                "collected_at": now,
                "file_mtime": file_mtime,
            })

        logger.info("Collected %d file hashes (SHA256) from suspicious paths", len(results))
        return results
