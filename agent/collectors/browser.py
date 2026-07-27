"""11. 浏览器痕迹采集器."""

import logging
import os
import sqlite3
import shutil
import tempfile
import time
from typing import Any

from collectors.base_collector import BaseCollector
from utils.platform import is_windows, is_linux, normalize_timestamp

logger = logging.getLogger(__name__)


class BrowserCollector(BaseCollector):
    """浏览器痕迹采集器.

    采集 Chrome/Firefox/Edge/IE 历史记录、下载记录、扩展.
    按 log_days 过滤最近 N 天的记录.

    Attributes:
        log_days: 采集最近 N 天的浏览器记录（默认 7 天）.
    """

    name = "browser"
    platform = ["windows", "linux"]

    def collect(self) -> dict:
        """执行浏览器痕迹采集."""
        return {
            "chrome": self._collect_chrome(),
            "firefox": self._collect_firefox(),
            "edge": self._collect_edge(),
            "ie": self._collect_ie(),
        }

    def _cutoff_timestamp(self) -> int:
        """计算 log_days 前对应的 Unix 时间戳（秒）.

        Returns:
            Unix 时间戳（秒）.
        """
        return int(time.time() - self.log_days * 86400)

    def _get_browser_paths(self) -> dict:
        """获取各浏览器数据路径."""
        paths: dict[str, Any] = {}
        home = os.path.expanduser("~")

        if is_windows():
            local_app = os.environ.get("LOCALAPPDATA", os.path.join(home, "AppData", "Local"))
            paths["chrome"] = os.path.join(local_app, "Google", "Chrome", "User Data", "Default")
            paths["edge"] = os.path.join(local_app, "Microsoft", "Edge", "User Data", "Default")
            paths["firefox"] = os.path.join(home, "AppData", "Roaming", "Mozilla", "Firefox", "Profiles")
            paths["ie"] = os.path.join(home, "AppData", "Local", "Microsoft", "Windows", "History")
        elif is_linux():
            paths["chrome"] = os.path.join(home, ".config", "google-chrome", "Default")
            paths["edge"] = os.path.join(home, ".config", "microsoft-edge", "Default")
            paths["firefox"] = os.path.join(home, ".mozilla", "firefox")
        return paths

    def _collect_chrome(self) -> dict:
        """采集 Chrome 浏览器数据."""
        paths = self._get_browser_paths()
        chrome_path = paths.get("chrome", "")
        if not chrome_path or not os.path.exists(chrome_path):
            return {"history": [], "downloads": [], "extensions": []}

        history_db = os.path.join(chrome_path, "History")
        return {
            "history": self._read_chrome_history(history_db),
            "downloads": self._read_chrome_downloads(history_db),
            "extensions": self._read_chrome_extensions(chrome_path),
        }

    def _collect_edge(self) -> dict:
        """采集 Edge 浏览器数据（与 Chrome 格式相同）."""
        paths = self._get_browser_paths()
        edge_path = paths.get("edge", "")
        if not edge_path or not os.path.exists(edge_path):
            return {"history": [], "downloads": [], "extensions": []}

        history_db = os.path.join(edge_path, "History")
        return {
            "history": self._read_chrome_history(history_db),
            "downloads": self._read_chrome_downloads(history_db),
            "extensions": self._read_chrome_extensions(edge_path),
        }

    def _read_chrome_history(self, db_path: str) -> list:
        """读取 Chrome/Edge 历史记录（按 log_days 过滤）."""
        history = []
        if not os.path.exists(db_path):
            return history

        tmp_path = self._copy_db_to_temp(db_path)
        if not tmp_path:
            return history

        cutoff = self._cutoff_timestamp()
        try:
            conn = sqlite3.connect(tmp_path)
            cursor = conn.execute(
                "SELECT url, title, datetime(last_visit_time/1000000-11644473600, 'unixepoch') as visit_time "
                "FROM urls "
                "WHERE last_visit_time/1000000-11644473600 > ? "
                "ORDER BY last_visit_time DESC LIMIT 100",
                (cutoff,),
            )
            for row in cursor:
                history.append({"url": row[0], "title": row[1] or "", "visit_time": normalize_timestamp(row[2]) if row[2] else ""})
            conn.close()
        except Exception as exc:
            logger.debug("Chrome history read failed: %s", exc)
        finally:
            self._cleanup_temp(tmp_path)
        return history

    def _read_chrome_downloads(self, db_path: str) -> list:
        """读取 Chrome/Edge 下载记录（按 log_days 过滤）."""
        downloads = []
        if not os.path.exists(db_path):
            return downloads

        tmp_path = self._copy_db_to_temp(db_path)
        if not tmp_path:
            return downloads

        cutoff = self._cutoff_timestamp()
        try:
            conn = sqlite3.connect(tmp_path)
            cursor = conn.execute(
                "SELECT target_path, tab_url, total_bytes, "
                "datetime(start_time/1000000-11644473600, 'unixepoch') as start_time "
                "FROM downloads "
                "WHERE start_time/1000000-11644473600 > ? "
                "ORDER BY start_time DESC LIMIT 50",
                (cutoff,),
            )
            for row in cursor:
                downloads.append({
                    "path": row[0] or "",
                    "url": row[1] or "",
                    "size": row[2] or 0,
                    "time": normalize_timestamp(row[3]) if row[3] else "",
                })
            conn.close()
        except Exception as exc:
            logger.debug("Chrome downloads read failed: %s", exc)
        finally:
            self._cleanup_temp(tmp_path)
        return downloads

    def _read_chrome_extensions(self, profile_path: str) -> list:
        """读取 Chrome/Edge 扩展列表."""
        extensions = []
        ext_dir = os.path.join(profile_path, "Extensions")
        if not os.path.exists(ext_dir):
            return extensions
        try:
            for ext_id in os.listdir(ext_dir):
                ext_path = os.path.join(ext_dir, ext_id)
                if os.path.isdir(ext_path):
                    versions = os.listdir(ext_path)
                    for ver in versions:
                        manifest_path = os.path.join(ext_path, ver, "manifest.json")
                        if os.path.exists(manifest_path):
                            extensions.append({
                                "id": ext_id,
                                "version": ver,
                                "path": os.path.join(ext_path, ver),
                            })
                            break
        except (PermissionError, OSError):
            pass
        return extensions

    def _collect_firefox(self) -> dict:
        """采集 Firefox 浏览器数据."""
        paths = self._get_browser_paths()
        ff_path = paths.get("firefox", "")
        if not ff_path or not os.path.exists(ff_path):
            return {"history": [], "downloads": [], "extensions": []}

        # 查找默认 profile
        profile_dir = ""
        if os.path.isdir(ff_path):
            for item in os.listdir(ff_path):
                if item.endswith(".default") or item.endswith(".default-release"):
                    profile_dir = os.path.join(ff_path, item)
                    break

        if not profile_dir:
            return {"history": [], "downloads": [], "extensions": []}

        places_db = os.path.join(profile_dir, "places.sqlite")
        return {
            "history": self._read_firefox_history(places_db),
            "downloads": self._read_firefox_downloads(places_db),
            "extensions": self._read_firefox_extensions(profile_dir),
        }

    def _read_firefox_history(self, db_path: str) -> list:
        """读取 Firefox 历史记录（按 log_days 过滤）."""
        history = []
        if not os.path.exists(db_path):
            return history
        tmp_path = self._copy_db_to_temp(db_path)
        if not tmp_path:
            return history

        cutoff = self._cutoff_timestamp()
        try:
            conn = sqlite3.connect(tmp_path)
            cursor = conn.execute(
                "SELECT url, title, datetime(last_visit_date/1000000, 'unixepoch') as visit_time "
                "FROM moz_places WHERE last_visit_date IS NOT NULL "
                "AND last_visit_date/1000000 > ? "
                "ORDER BY last_visit_date DESC LIMIT 100",
                (cutoff,),
            )
            for row in cursor:
                history.append({"url": row[0], "title": row[1] or "", "visit_time": normalize_timestamp(row[2]) if row[2] else ""})
            conn.close()
        except Exception as exc:
            logger.debug("Firefox history read failed: %s", exc)
        finally:
            self._cleanup_temp(tmp_path)
        return history

    def _read_firefox_downloads(self, db_path: str) -> list:
        """读取 Firefox 下载记录（按 log_days 过滤）."""
        downloads = []
        if not os.path.exists(db_path):
            return downloads
        tmp_path = self._copy_db_to_temp(db_path)
        if not tmp_path:
            return downloads

        cutoff = self._cutoff_timestamp()
        try:
            conn = sqlite3.connect(tmp_path)
            cursor = conn.execute(
                "SELECT p.url, datetime(a.date/1000000, 'unixepoch') as download_time "
                "FROM moz_annos a JOIN moz_places p ON a.place_id = p.id "
                "WHERE a.anno_attribute_id IN (SELECT id FROM moz_anno_attributes WHERE name LIKE 'download%') "
                "AND a.date/1000000 > ? "
                "ORDER BY a.date DESC LIMIT 50",
                (cutoff,),
            )
            for row in cursor:
                downloads.append({"url": row[0], "time": normalize_timestamp(row[1]) if row[1] else ""})
            conn.close()
        except Exception as exc:
            logger.debug("Firefox downloads read failed: %s", exc)
        finally:
            self._cleanup_temp(tmp_path)
        return downloads

    def _read_firefox_extensions(self, profile_path: str) -> list:
        """读取 Firefox 扩展列表."""
        extensions = []
        ext_file = os.path.join(profile_path, "extensions.json")
        if not os.path.exists(ext_file):
            return extensions
        try:
            import json
            with open(ext_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            for addon in data.get("addons", []):
                extensions.append({
                    "id": addon.get("id", ""),
                    "name": addon.get("defaultLocale", {}).get("name", ""),
                    "version": addon.get("version", ""),
                })
        except Exception as exc:
            logger.debug("Firefox extensions read failed: %s", exc)
        return extensions

    def _collect_ie(self) -> dict:
        """采集 IE 浏览器数据."""
        return {"history": [], "downloads": []}

    def _copy_db_to_temp(self, db_path: str) -> str:
        """复制数据库到临时目录（避免数据库锁定）."""
        try:
            tmp_dir = tempfile.mkdtemp()
            tmp_path = os.path.join(tmp_dir, os.path.basename(db_path))
            shutil.copy2(db_path, tmp_path)
            return tmp_path
        except (PermissionError, OSError) as exc:
            logger.debug("Failed to copy DB: %s", exc)
            return ""

    def _cleanup_temp(self, tmp_path: str) -> None:
        """清理临时文件."""
        try:
            os.remove(tmp_path)
            os.rmdir(os.path.dirname(tmp_path))
        except (OSError, PermissionError):
            pass
