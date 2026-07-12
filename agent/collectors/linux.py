"""Linux 基础维度采集器（融合 §三.1）.

补齐 Linux 与 Windows 对等的基础维度：cron / systemd / ssh / bash_history / web_dirs。
其中 ``discover_web_roots()`` 向 WebShellCollector 暴露，复用其发现的 Web 目录，
避免 webshell 采集器直接耦合平台细节。

仅 Linux 支持（无 macOS 分支，与主决策一致）。
"""

import glob
import logging
import os
import re
from typing import List, Optional

from collectors.base_collector import BaseCollector
from utils.platform import is_linux, run_command

logger = logging.getLogger(__name__)

# Nginx / Apache / Tomcat / 宝塔 / PHPStudy / 1Panel 等常见 web 根候选（存在性扫描）
_CANDIDATE_DIRS = [
    "/var/www", "/var/www/html", "/srv/www", "/srv/http", "/usr/local/nginx/html",
    "/opt/lampp/htdocs", "/www", "/www/wwwroot", "/opt/1panel/www",
    "/opt/tomcat/webapps", "/var/lib/tomcat/webapps",
    "/usr/share/tomcat9/webapps", "/usr/share/tomcat8/webapps",
    "/data/www", "/home/wwwroot",
]

# 解析 root 指令的配置文件（Nginx / Apache）
_ROOT_CONFIG_GLOBS = [
    "/etc/nginx/nginx.conf",
    "/etc/nginx/conf.d/*.conf",
    "/etc/nginx/sites-enabled/*",
    "/etc/apache2/apache2.conf",
    "/etc/apache2/sites-enabled/*",
    "/etc/httpd/conf/httpd.conf",
    "/etc/httpd/conf.d/*.conf",
    "/usr/local/nginx/conf/nginx.conf",
]

# Tomcat server.xml 候选
_TOMCAT_SERVER_XML = [
    "/opt/tomcat/conf/server.xml",
    "/etc/tomcat/server.xml",
    "/var/lib/tomcat*/conf/server.xml",
    "/usr/share/tomcat*/conf/server.xml",
]


class LinuxBaselineCollector(BaseCollector):
    """Linux 基础维度采集器."""

    name = "linux_baseline"
    platform = ["linux"]

    # ── Web 目录发现（供 WebShellCollector 复用）──────────────────
    @staticmethod
    def discover_web_roots(extra_dirs: Optional[List[str]] = None) -> List[str]:
        """发现 Linux 主机上的 Web 根目录列表.

        解析 Nginx/Apache 的 ``root`` 指令与 Tomcat ``appBase``，并回退扫描常见
        web 根候选目录。返回存在的绝对路径列表（去重）。

        Args:
            extra_dirs: 额外手动指定的 web 目录（如 agent_config.extra_web_dirs）.

        Returns:
            web 根目录绝对路径列表（按发现顺序，去重）.
        """
        if not is_linux():
            return []

        roots: List[str] = []
        seen = set()

        def _add(p: str) -> None:
            if p and os.path.isdir(p):
                ap = os.path.abspath(p)
                if ap not in seen:
                    seen.add(ap)
                    roots.append(ap)

        # 1) 解析 Nginx / Apache root 指令
        for pattern in _ROOT_CONFIG_GLOBS:
            for cfg in glob.glob(pattern):
                try:
                    with open(cfg, "r", encoding="utf-8", errors="replace") as fh:
                        text = fh.read()
                    for m in re.finditer(r"\broot\s+([^;\s]+)\s*;", text):
                        _add(m.group(1))
                except (OSError, UnicodeDecodeError) as exc:
                    logger.debug("Web 根配置解析失败 %s: %s", cfg, exc)

        # 2) 解析 Tomcat appBase
        for pattern in _TOMCAT_SERVER_XML:
            for cfg in glob.glob(pattern):
                try:
                    with open(cfg, "r", encoding="utf-8", errors="replace") as fh:
                        text = fh.read()
                    for m in re.finditer(r'appBase\s*=\s*"([^"]+)"', text):
                        _add(m.group(1))
                except (OSError, UnicodeDecodeError) as exc:
                    logger.debug("Tomcat 配置解析失败 %s: %s", cfg, exc)

        # 3) 回退：扫描常见 web 根候选目录
        for d in _CANDIDATE_DIRS:
            _add(d)
        # 宝塔 / 1Panel 等动态 home 目录
        for d in glob.glob("/www/wwwroot/*"):
            if os.path.isdir(d):
                _add(d)

        # 4) 额外指定目录
        for d in (extra_dirs or []):
            _add(d)

        if not roots:
            logger.info("Linux 未发现已知 Web 根目录（Nginx/Apache/Tomcat 等未安装或未扫描到）")
        else:
            logger.info("Linux 发现 %d 个 Web 根目录", len(roots))
        return roots

    def collect(self) -> dict:
        """采集 Linux 基础维度.

        Returns:
            含 cron / systemd / ssh / bash_history / web_dirs 的字典。
            各子项独立 try/except，单项错误不影响整体（安全隔离）。
        """
        result: dict = {
            "cron": [],
            "systemd": [],
            "ssh": [],
            "bash_history": [],
            "web_dirs": [],
        }

        # Web 根目录（核心产出，供 WebShellCollector 复用）
        try:
            result["web_dirs"] = self.discover_web_roots()
        except Exception as exc:
            logger.warning("discover_web_roots 失败: %s", exc)

        # cron 作业（系统 + 用户级 crontab 文件存在性）
        try:
            cron_paths = (
                ["/etc/crontab"]
                + glob.glob("/etc/cron.d/*")
                + glob.glob("/etc/cron.daily/*")
                + glob.glob("/etc/cron.hourly/*")
                + glob.glob("/var/spool/cron/crontabs/*")
                + glob.glob("/var/spool/cron/*")
            )
            result["cron"] = [p for p in cron_paths if os.path.isfile(p)]
        except Exception as exc:
            logger.debug("cron 采集失败: %s", exc)

        # systemd 启用服务（best-effort：优先 systemctl，失败回退目录扫描）
        try:
            out = run_command(
                "systemctl list-unit-files --type=service --state=enabled --no-legend 2>/dev/null",
                timeout=20,
            )
            if out:
                result["systemd"] = [
                    ln.split()[0] for ln in out.splitlines() if ln.strip()
                ]
            else:
                svc_dirs = ["/etc/systemd/system", "/lib/systemd/system", "/usr/lib/systemd/system"]
                found = []
                for sd in svc_dirs:
                    if os.path.isdir(sd):
                        found.extend(glob.glob(os.path.join(sd, "*.service")))
                result["systemd"] = found
        except Exception as exc:
            logger.debug("systemd 采集失败: %s", exc)

        # SSH authorized_keys
        try:
            ak = glob.glob("/home/*/.ssh/authorized_keys")
            ak += glob.glob("/root/.ssh/authorized_keys")
            result["ssh"] = [p for p in ak if os.path.isfile(p)]
        except Exception as exc:
            logger.debug("ssh 采集失败: %s", exc)

        # bash_history
        try:
            bh = glob.glob("/home/*/.bash_history")
            bh += glob.glob("/root/.bash_history")
            result["bash_history"] = [p for p in bh if os.path.isfile(p)]
        except Exception as exc:
            logger.debug("bash_history 采集失败: %s", exc)

        return result
