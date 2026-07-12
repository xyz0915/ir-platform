"""Windows Web 目录发现（融合 §三.1，向 WebShellCollector 暴露 discover_web_roots）.

仅扫描既有常见 Web 服务器安装目录与 IIS/Tomcat 配置，返回存在的 web 根目录列表。
无 macOS 分支（与主决策一致）；非 Windows 平台返回空列表。
"""

import logging
import os
from typing import List

from utils.platform import is_windows, run_command

logger = logging.getLogger(__name__)

# Windows 常见 Web 服务器 web 根候选目录
_CANDIDATE_DIRS = [
    r"C:\inetpub\wwwroot",                                  # IIS 默认
    r"C:\xampp\htdocs",                                     # XAMPP
    r"C:\wamp\www",                                         # WAMP
    r"C:\Program Files\Apache Software Foundation\Apache2.4\htdocs",
    r"C:\phpstudy_pro\WWW",                                 # PHPStudy
    r"C:\phpstudy\PHPTutorial\WWW",
    r"C:\tomcat\webapps",                                   # Tomcat
    r"C:\Program Files\Apache Software Foundation\Tomcat\webapps",
    r"C:\BtSoft\wwwroot",                                   # 宝塔 Windows 版
]


def _discover_from_iis() -> List[str]:
    """解析 IIS applicationHost.config 提取物理路径（best-effort）."""
    roots: List[str] = []
    # 常见 IIS 配置路径
    cfg_candidates = [
        r"C:\Windows\System32\inetsrv\config\applicationHost.config",
        r"C:\Windows\SysWOW64\inetsrv\config\applicationHost.config",
    ]
    for cfg in cfg_candidates:
        if not os.path.isfile(cfg):
            continue
        try:
            with open(cfg, "r", encoding="utf-8", errors="replace") as fh:
                text = fh.read()
            import re
            for m in re.finditer(r'physicalPath\s*=\s*"([^"]+)"', text):
                p = m.group(1)
                if p and os.path.isdir(p):
                    roots.append(os.path.abspath(p))
        except (OSError, UnicodeDecodeError) as exc:
            logger.debug("IIS 配置解析失败 %s: %s", cfg, exc)
    return roots


def _discover_from_tomcat() -> List[str]:
    """解析 Tomcat server.xml 提取 appBase（best-effort）."""
    roots: List[str] = []
    cfg_candidates = [
        r"C:\tomcat\conf\server.xml",
        r"C:\Program Files\Apache Software Foundation\Tomcat\conf\server.xml",
    ]
    for cfg in cfg_candidates:
        if not os.path.isfile(cfg):
            continue
        try:
            with open(cfg, "r", encoding="utf-8", errors="replace") as fh:
                text = fh.read()
            import re
            for m in re.finditer(r'appBase\s*=\s*"([^"]+)"', text):
                base = m.group(1)
                if base and os.path.isdir(base):
                    roots.append(os.path.abspath(base))
        except (OSError, UnicodeDecodeError) as exc:
            logger.debug("Tomcat 配置解析失败 %s: %s", cfg, exc)
    return roots


def discover_web_roots(extra_dirs: List[str] = None) -> List[str]:
    """发现 Windows 主机上的 Web 根目录列表.

    Args:
        extra_dirs: 额外手动指定的 web 目录（如 agent_config.extra_web_dirs）.

    Returns:
        存在的 web 根目录绝对路径列表（去重，按发现顺序）。
    """
    if not is_windows():
        return []

    roots: List[str] = []
    seen = set()

    def _add(p: str) -> None:
        if p and os.path.isdir(p):
            ap = os.path.abspath(p)
            if ap not in seen:
                seen.add(ap)
                roots.append(ap)

    for d in _CANDIDATE_DIRS:
        _add(d)
    for r in _discover_from_iis():
        _add(r)
    for r in _discover_from_tomcat():
        _add(r)
    for d in (extra_dirs or []):
        _add(d)

    if not roots:
        logger.info("Windows 未发现已知 Web 根目录（IIS/Tomcat/PHPStudy 等未安装或未扫描到）")
    else:
        logger.info("Windows 发现 %d 个 Web 根目录", len(roots))
    return roots
