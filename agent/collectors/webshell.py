"""WebShell 文件型采集器（融合 §2.2 / §三.1）.

跨平台（Windows IIS/Tomcat 优先，Linux Nginx/Apache/Tomcat/宝塔 次）：
- 复用 ``LinuxBaselineCollector.discover_web_roots()`` 与 Windows ``web_roots.discover_web_roots()``
  发现 web 目录（平台优先级 Windows > Linux）；
- 按资源预算扫描：文件 ≤5MB 读全文，更大读头尾各 64KB + 均匀采样；
  单 web 根文件数超阈值采样；
- 静态检测危险函数 / 混淆度 / 哥斯拉-冰蝎信号，产出 ``webshells[]``。

无 macOS 分支（与主决策一致）。采集失败经 safe_collect 保护，不拖垮 Agent。
"""

import json
import logging
import os
import re
from datetime import datetime
from typing import List, Optional

from collectors.base_collector import BaseCollector
from collectors.resource_budget import (
    WEBSHELL_EXTENSIONS,
    WEBSHELL_FULL_READ_BYTES,
    WEBSHELL_HEAD_TAIL_BYTES,
    WEBSHELL_SAMPLE_CHUNK_BYTES,
    WEBSHELL_MAX_FILES_PER_ROOT,
)
from utils.platform import is_windows, is_linux, get_timestamp

logger = logging.getLogger(__name__)

# 危险函数（WebShell 常见）
_SUSPICIOUS_FUNC_RE = re.compile(
    r"(eval|assert|base64_decode|base64_encode|system|exec|passthru|"
    r"shell_exec|proc_open|popen|create_function|preg_replace)\s*\(",
    re.IGNORECASE,
)
# 哥斯拉/冰蝎等内存马/WebShell 信号词
_GODZILLA_MARKERS = (
    "getclassloader", "javax.crypto.cipher", "aes", "md5", "base64",
    "godzilla", "behinder", "payload", "aesencrypt", "$_post", "$_request",
    "getmethod", "classloader", "objectinputstream",
)
# 混淆指标
_OBFUSCATION_PACK_RE = re.compile(
    r"(gzinflate|gzuncompress|str_rot13|utf8_decode|convert_uu)", re.IGNORECASE
)
_LONG_BASE64_RE = re.compile(r"[A-Za-z0-9+/]{60,}={0,2}")


class WebShellCollector(BaseCollector):
    """WebShell 文件型采集器."""

    name = "webshells"
    platform = ["windows", "linux"]

    def __init__(self, log_days: int = 7) -> None:
        super().__init__(log_days=log_days)
        self.extra_web_dirs: List[str] = self._load_extra_web_dirs()

    # ── 公共检测函数（纯函数，便于单测）──────────────────────────
    @staticmethod
    def detect_suspicious_funcs(content: str) -> List[str]:
        """检测内容中的危险函数调用，返回去重函数名列表."""
        if not content:
            return []
        found = set()
        for m in _SUSPICIOUS_FUNC_RE.finditer(content):
            found.add(m.group(1).lower())
        return sorted(found)

    @staticmethod
    def compute_obfuscation_score(content: str) -> float:
        """启发式计算混淆度（0~1）.

        依据长 base64 块、打包函数组合、字符熵综合打分。
        """
        if not content:
            return 0.0
        score = 0.0
        # 1) 长 base64 块
        if _LONG_BASE64_RE.search(content):
            score += 0.4
        # 2) 打包/解包函数组合（base64_decode + gzinflate 等）
        if "base64_decode" in content.lower() and _OBFUSCATION_PACK_RE.search(content):
            score += 0.3
        # 3) 字符熵（采样前 4KB）
        sample = content[:4096]
        if sample:
            freq = {}
            for ch in sample:
                freq[ch] = freq.get(ch, 0) + 1
            import math
            n = len(sample)
            entropy = -sum((c / n) * math.log2(c / n) for c in freq.values() if c)
            # 英文字母熵约 4.0~4.5；接近 8 视为高熵（压缩/加密）
            if entropy >= 6.5:
                score += 0.3
            elif entropy >= 5.5:
                score += 0.15
        return min(1.0, score)

    @staticmethod
    def detect_behinder_godzilla(content: str) -> bool:
        """检测哥斯拉/冰蝎类信号（多标记命中）."""
        if not content:
            return False
        low = content.lower()
        hits = sum(1 for mk in _GODZILLA_MARKERS if mk in low)
        return hits >= 3

    @staticmethod
    def analyze_file(path: str, content: str, web_root: str, middleware: str) -> Optional[dict]:
        """对单个 Web 文件内容做静态分析，命中可疑特征则返回 WebShell 证据 dict.

        Args:
            path: 文件绝对路径.
            content: 已按资源预算读取的可分析文本.
            web_root: 所属 web 根目录.
            middleware: 中间件类型（apache/nginx/tomcat/iis/phpstudy/unknown）.

        Returns:
            命中则返回 WebShell 证据 dict；未命中返回 None（不产出噪音）.
        """
        funcs = WebShellCollector.detect_suspicious_funcs(content)
        obf = WebShellCollector.compute_obfuscation_score(content)
        godzilla = WebShellCollector.detect_behinder_godzilla(content)
        if not (funcs or obf >= 0.6 or godzilla):
            return None

        try:
            st = os.stat(path)
            size = st.st_size
            mtime = datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%dT%H:%M:%S")
        except OSError:
            size, mtime = 0, ""

        try:
            owner = os.stat(path).st_uid
        except OSError:
            owner = ""
        try:
            perms = oct(os.stat(path).st_mode & 0o777)
        except OSError:
            perms = ""

        return {
            "path": path,
            "name": os.path.basename(path),
            "size": size,
            "mtime": mtime,
            "owner": str(owner),
            "perms": perms,
            "sha256": WebShellCollector._sha256_file(path),
            "web_root": web_root,
            "middleware": middleware,
            "suspicious_funcs": funcs,
            "obfuscation_score": round(obf, 2),
            "behinder_godzilla_signal": godzilla,
            "risk_score": round(min(1.0, 0.3 * len(funcs) + obf + (0.2 if godzilla else 0.0)), 2),
            "scan_engine": "static",
        }

    @staticmethod
    def _sha256_file(path: str) -> str:
        """计算文件 sha256（失败返回空串）."""
        import hashlib
        try:
            h = hashlib.sha256()
            with open(path, "rb") as fh:
                for chunk in iter(lambda: fh.read(65536), b""):
                    h.update(chunk)
            return h.hexdigest()
        except OSError:
            return ""

    # ── 资源预算感知的文件读取 ──────────────────────────────────
    @staticmethod
    def read_for_scan(path: str) -> str:
        """按资源预算读取文件可分析内容.

        ≤5MB 读全文；更大读头尾各 64KB + 3 段均匀采样块（合并为分析文本）。

        Returns:
            可分析文本（解码失败/读取失败返回空串）.
        """
        try:
            size = os.path.getsize(path)
        except OSError:
            return ""
        if size <= WEBSHELL_FULL_READ_BYTES:
            try:
                with open(path, "r", encoding="utf-8", errors="replace") as fh:
                    return fh.read()
            except (OSError, UnicodeDecodeError):
                return ""
        # 大文件：头尾 + 均匀采样（二进制读取避免文本模式 seek 错位）
        try:
            with open(path, "rb") as fb:
                head = fb.read(WEBSHELL_HEAD_TAIL_BYTES).decode("utf-8", "replace")
                fb.seek(0, os.SEEK_END)
                total = fb.tell()
                samples = []
                n_samples = 3
                span = total - 2 * WEBSHELL_HEAD_TAIL_BYTES
                if span > 0:
                    step = max(1, span // (n_samples + 1))
                    for i in range(1, n_samples + 1):
                        off = WEBSHELL_HEAD_TAIL_BYTES + i * step
                        if off >= total:
                            break
                        fb.seek(off)
                        samples.append(fb.read(WEBSHELL_SAMPLE_CHUNK_BYTES).decode("utf-8", "replace"))
                fb.seek(max(0, total - WEBSHELL_HEAD_TAIL_BYTES))
                tail = fb.read(WEBSHELL_HEAD_TAIL_BYTES).decode("utf-8", "replace")
            return "\n".join([head] + samples + [tail])
        except (OSError, UnicodeDecodeError):
            return ""

    # ── 主采集流程 ────────────────────────────────────────────
    def collect(self) -> List[dict]:
        """执行 WebShell 文件型采集.

        Returns:
            webshells[] 列表（每项含 path/name/sha256/suspicious_funcs/...）。
            未发现 web 根或采集失败时返回空列表。
        """
        roots = self._discover_roots()
        if not roots:
            logger.info("未发现 Web 根目录，跳过 WebShell 采集")
            return []

        results: List[dict] = []
        for root, middleware in roots:
            results.extend(self._scan_root(root, middleware))
        logger.info("WebShell 采集完成，命中 %d 个可疑文件", len(results))
        return results

    def _discover_roots(self) -> List[tuple]:
        """按平台优先级发现 web 根目录（Windows > Linux），返回 [(root, middleware)]."""
        roots: List[tuple] = []
        if is_windows():
            try:
                from collectors.windows.web_roots import discover_web_roots
                for r in discover_web_roots(self.extra_web_dirs):
                    roots.append((r, self._infer_middleware(r, windows=True)))
            except Exception as exc:
                logger.warning("Windows Web 根发现失败: %s", exc)
        if is_linux():
            try:
                from collectors.linux import LinuxBaselineCollector
                for r in LinuxBaselineCollector.discover_web_roots(self.extra_web_dirs):
                    roots.append((r, self._infer_middleware(r, windows=False)))
            except Exception as exc:
                logger.warning("Linux Web 根发现失败: %s", exc)
        # 全部平台兜底也允许 extra_web_dirs
        for d in self.extra_web_dirs:
            if os.path.isdir(d) and not any(d == r[0] for r in roots):
                roots.append((d, "unknown"))
        return roots

    @staticmethod
    def _infer_middleware(root: str, windows: bool) -> str:
        """根据路径/平台推断中间件类型（apache/nginx/tomcat/iis/phpstudy）."""
        low = root.lower().replace("\\", "/")
        if "nginx" in low:
            return "nginx"
        if "tomcat" in low or "webapps" in low:
            return "tomcat"
        if "iis" in low or "inetpub" in low:
            return "iis"
        if "phpstudy" in low or "wamp" in low or "xampp" in low:
            return "phpstudy"
        if "apache" in low:
            return "apache"
        return "iis" if windows else "nginx"

    def _scan_root(self, root: str, middleware: str) -> List[dict]:
        """扫描单个 web 根下的脚本文件，按资源预算采样 + 静态分析."""
        files = []
        for dirpath, _dirs, filenames in os.walk(root):
            for fn in filenames:
                if fn.lower().endswith(WEBSHELL_EXTENSIONS):
                    files.append(os.path.join(dirpath, fn))

        # 文件数超阈值 → 均匀采样，避免低频 web 根拖垮采集
        if len(files) > WEBSHELL_MAX_FILES_PER_ROOT:
            step = max(1, len(files) // WEBSHELL_MAX_FILES_PER_ROOT)
            files = files[::step]
            logger.info("web 根 %s 文件数超阈值，采样 %d 个", root, len(files))

        hits: List[dict] = []
        for fp in files:
            try:
                content = self.read_for_scan(fp)
                item = self.analyze_file(fp, content, root, middleware)
                if item:
                    hits.append(item)
            except Exception as exc:
                logger.debug("WebShell 分析失败 %s: %s", fp, exc)
        return hits

    @staticmethod
    def _load_extra_web_dirs() -> List[str]:
        """从 cwd 的 agent_config.json 读取 extra_web_dirs（可选）."""
        try:
            cfg_path = os.path.join(os.getcwd(), "agent_config.json")
            if os.path.isfile(cfg_path):
                with open(cfg_path, "r", encoding="utf-8") as fh:
                    data = json.load(fh)
                dirs = data.get("extra_web_dirs") or []
                if isinstance(dirs, list):
                    return [str(d) for d in dirs if d]
        except (OSError, json.JSONDecodeError, ValueError):
            pass
        return []
