"""3. 进程信息采集器（增强版：融合 §2.1 / §三.1）.

在既有字段（pid/ppid/name/path/command_line/user/start_time/threads/connections）
基础上，就地补充富化字段（不新增顶层 key）：
- ``session``：跨会话父子检测（#4）；
- ``state``：僵尸/Suspended 判定；
- ``memory_sections``：统一内存区段契约（B #1/#2 注入/PE 痕迹 + A 内存马/JVM 语义）。

``memory_sections`` 按资源预算降采样：仅对「解释器 / 年轻进程(<60s) / 无签名进程」
采集，单进程区段上限 ≤64。Linux 读 ``/proc/PID/maps``；Windows 走 ``VirtualQueryEx``
（best-effort，权限不足/容器隔离时降级为空，绝不抛异常拖垮 Agent）。
"""

import logging
from datetime import datetime, timezone
from typing import Any, List, Optional

from collectors.base_collector import BaseCollector
from collectors.resource_budget import (
    INTERPRETER_NAMES,
    MEM_SECTION_MAX_PER_PROCESS,
    is_young_process,
)
from utils.platform import (
    get_timestamp,
    is_windows,
    is_linux,
    run_command,
    read_file_safe,
)

logger = logging.getLogger(__name__)


class ProcessesCollector(BaseCollector):
    """进程信息采集器（增强版）.

    采集 PID、PPID、进程名、路径、命令行、用户、启动时间、线程数、网络连接，
    并就地补充 session / state / memory_sections 富化字段。
    """

    name = "processes"
    platform = ["windows", "linux"]

    def collect(self) -> list:
        """执行进程信息采集（优先 psutil，失败回退 wmic/tasklist）."""
        processes = []

        try:
            import psutil
        except ImportError:
            logger.warning("psutil not available, using fallback")
            return self._collect_fallback()

        # psutil 主采集
        conn_map = self._build_connection_map(psutil)
        try:
            proc_iter = list(psutil.process_iter(["pid", "ppid", "name", "exe", "cmdline",
                                                   "username", "create_time", "num_threads"]))
            if not proc_iter:
                logger.warning("psutil.process_iter returned empty, using fallback")
                return self._collect_fallback()
        except Exception as exc:
            logger.warning("psutil.process_iter failed: %s, using fallback", exc)
            return self._collect_fallback()

        for proc in proc_iter:
            try:
                info = proc.info
                pid = info.get("pid", 0)

                create_time = info.get("create_time")
                start_time = ""
                if create_time is not None:  # None 跳过，0 也格式化
                    try:
                        start_time = datetime.fromtimestamp(create_time, tz=timezone.utc).isoformat()
                    except (ValueError, OSError, OverflowError):
                        start_time = ""

                cmdline = info.get("cmdline")
                command_line = " ".join(cmdline) if cmdline else ""

                ppid = info.get("ppid", 0)
                parent_name = self._get_parent_name(ppid)

                process_data = {
                    "pid": pid,
                    "ppid": ppid,
                    "name": info.get("name", ""),
                    "path": info.get("exe", "") or "",
                    "command_line": command_line,
                    "user": info.get("username", "") or "",
                    "start_time": start_time,
                    "threads": info.get("num_threads", 0) or 0,
                    "parent_name": parent_name,
                    "connections": conn_map.get(pid, []),
                    "collected_at": get_timestamp(),
                }
                # ── 富化：session / state / memory_sections ──
                self._enrich(process_data)
                processes.append(process_data)
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                continue

        return processes

    def _collect_fallback(self) -> list:
        """使用 wmic / tasklist 作为 Windows 回退方案（含富化）."""
        from utils.platform import is_windows

        if not is_windows():
            return []

        processes = []
        # 方案 A: wmic (CSV 格式，含命令行)
        import csv, io
        output = run_command(
            'wmic process get ProcessId,ParentProcessId,Name,ExecutablePath,CommandLine /format:csv',
            timeout=30,
        )
        if output and "ProcessId" in output:
            try:
                reader = csv.reader(io.StringIO(output.strip()))
                rows = list(reader)
                if len(rows) > 1:
                    headers = [h.strip() for h in rows[0]]
                    pid_idx = _find_col(headers, "ProcessId")
                    ppid_idx = _find_col(headers, "ParentProcessId")
                    name_idx = _find_col(headers, "Name")
                    path_idx = _find_col(headers, "ExecutablePath")
                    cmd_idx = _find_col(headers, "CommandLine")
                    for row in rows[1:]:
                        if len(row) < len(headers):
                            continue
                        pid_str = row[pid_idx].strip() if pid_idx < len(row) else ""
                        if not pid_str or pid_str == "0":
                            continue
                        try:
                            pid = int(pid_str)
                        except ValueError:
                            continue
                        ppid_str = row[ppid_idx].strip() if ppid_idx < len(row) else "0"
                        try:
                            ppid = int(ppid_str) if ppid_str and ppid_str.isdigit() else 0
                        except ValueError:
                            ppid = 0
                        # 从 wmic creationdate 解析进程启动时间
                        cdate_idx = _find_col(headers, "CreationDate")
                        wmic_ct = row[cdate_idx].strip() if cdate_idx < len(row) else ""
                        start_time = ""
                        if wmic_ct:
                            try:
                                # wmic 格式: 20260711230710.123456+480 (YYYYMMDDHHMMSS.ffffff±ZZZ)
                                wmic_ct = wmic_ct.strip()
                                dt_str = wmic_ct.split(".")[0]
                                start_time = f"{dt_str[0:4]}-{dt_str[4:6]}-{dt_str[6:8]}T{dt_str[8:10]}:{dt_str[10:12]}:{dt_str[12:14]}+08:00"
                            except Exception:
                                start_time = ""
                        pd = {
                            "pid": pid,
                            "ppid": ppid,
                            "name": row[name_idx].strip() if name_idx < len(row) else "",
                            "path": row[path_idx].strip() if path_idx < len(row) else "",
                            "command_line": row[cmd_idx].strip() if cmd_idx < len(row) else "",
                            "user": "",
                            "start_time": start_time,
                            "threads": 0,
                            "parent_name": "",
                            "connections": [],
                            "collected_at": get_timestamp(),
                        }
                        self._enrich(pd)
                        processes.append(pd)
                    if processes:
                        return processes
            except Exception as exc:
                logger.warning("wmic CSV parse failed: %s, trying tasklist", exc)

        # 方案 B: tasklist（无命令行，但有 PID/Name）
        output = run_command('tasklist /fo csv /nh', timeout=15)
        if output:
            reader = csv.reader(io.StringIO(output.strip()))
            for row in reader:
                if len(row) < 2:
                    continue
                try:
                    name = row[0].strip('"')
                    pid_str = row[1].strip('"')
                    pid = int(pid_str)
                except (ValueError, IndexError):
                    continue
                pd = {
                    "pid": pid,
                    "ppid": 0,
                    "name": name,
                    "path": "",
                    "command_line": "",
                    "user": "",
                    "start_time": "",
                    "threads": 0,
                    "parent_name": "",
                    "connections": [],
                    "collected_at": get_timestamp(),
                }
                self._enrich(pd)
                processes.append(pd)
        return processes

    def _build_connection_map(self, psutil) -> dict:
        """构建 PID → 网络连接列表的映射."""
        conn_map: dict[int, list] = {}
        try:
            connections = psutil.net_connections(kind="inet")
            for conn in connections:
                pid = conn.pid
                if pid is None:
                    continue
                if pid not in conn_map:
                    conn_map[pid] = []
                conn_map[pid].append({
                    "protocol": "TCP" if conn.type.name == "SOCK_STREAM" else "UDP",
                    "local_address": conn.laddr.ip if conn.laddr else "",
                    "local_port": conn.laddr.port if conn.laddr else 0,
                    "remote_address": conn.raddr.ip if conn.raddr else "",
                    "remote_port": conn.raddr.port if conn.raddr else 0,
                    "state": conn.status if conn.status else "",
                })
        except (psutil.AccessDenied, psutil.NoSuchProcess):
            pass
        return conn_map

    # ── 父进程名称查找 ─────────────────────────────────────────
    @staticmethod
    def _get_parent_name(ppid: int) -> str:
        """通过 ppid 查找父进程名称.

        Args:
            ppid: 父进程 PID.

        Returns:
            父进程名称；父进程已退出返回 ``"[exited]"``，其他异常返回 ``""``。
        """
        if ppid <= 0:
            return ""
        try:
            import psutil
            parent = psutil.Process(ppid)
            return parent.name()
        except (psutil.NoSuchProcess, psutil.ZombieProcess):
            return "[exited]"
        except psutil.AccessDenied:
            return ""
        except Exception:
            return ""

    # ── 富化字段（session / state / memory_sections）─────────────
    def _enrich(self, proc: dict) -> None:
        """就地补充 session / state / memory_sections 富化字段（安全隔离）."""
        pid = proc.get("pid")
        name = proc.get("name", "") or ""
        start_time = proc.get("start_time", "")
        path = proc.get("path", "") or ""
        try:
            if is_linux():
                proc["session"] = self._linux_session(pid)
                proc["state"] = self._linux_state(pid)
            else:
                proc["session"] = self._windows_session(pid)
                proc["state"] = self._windows_state(pid)
        except Exception as exc:
            logger.debug("富化 session/state 失败 pid=%s: %s", pid, exc)
            proc.setdefault("session", None)
            proc.setdefault("state", None)

        try:
            proc["memory_sections"] = self._collect_memory_sections(pid, name, start_time, path)
        except Exception as exc:
            logger.debug("memory_sections 采集失败 pid=%s: %s", pid, exc)
            proc["memory_sections"] = None

    @staticmethod
    def _should_collect_sections(name: str, start_time: str, path: str) -> bool:
        """资源预算降采样判定：仅解释器 / 年轻(<60s) / 无签名(无路径)进程采集."""
        name_lower = (name or "").lower()
        if name_lower in INTERPRETER_NAMES:
            return True
        if is_young_process(start_time):
            return True
        if not path:
            return True
        return False

    def _collect_memory_sections(
        self, pid: Optional[int], name: str, start_time: str, path: str
    ) -> Optional[list]:
        """采集进程内存区段（降采样判定后分发到平台实现）."""
        if pid is None or not self._should_collect_sections(name, start_time, path):
            return None
        if is_linux():
            return self._linux_memory_sections(pid)
        return self._windows_memory_sections(pid)

    # ── Linux 富化 ─────────────────────────────────────────────
    @staticmethod
    def _linux_session(pid: Optional[int]) -> Optional[int]:
        """从 /proc/PID/stat 读取 session id（第 6 字段）。"""
        if pid is None:
            return None
        text = read_file_safe(f"/proc/{pid}/stat")
        if not text:
            return None
        try:
            # stat 第2字段为 (comm)，可能含空格，需从右解析；session 为第6字段
            # 取末尾数字字段更稳定
            parts = text.split()
            # 结构: pid (comm) state ppid pgrp session ... 第6个为 session
            if len(parts) >= 6:
                return int(parts[5])
        except (ValueError, IndexError, OSError):
            return None
        return None

    @staticmethod
    def _linux_state(pid: Optional[int]) -> Optional[str]:
        """从 /proc/PID/stat 读取进程状态字符（第 3 字段，comm 之后）。"""
        if pid is None:
            return None
        text = read_file_safe(f"/proc/{pid}/stat")
        if not text:
            return None
        try:
            # comm 在括号内，状态紧随其后
            rparen = text.rfind(")")
            if rparen != -1 and rparen + 2 < len(text):
                return text[rparen + 2]
        except (ValueError, OSError):
            return None
        return None

    @staticmethod
    def _parse_proc_maps(text: str) -> list:
        """解析 /proc/PID/maps 为统一内存区段契约（§2.1）.

        Args:
            text: /proc/PID/maps 内容.

        Returns:
            memory_sections 列表（上限由调用方裁剪），每项含 base_address /
            end_address / size / protection / type / is_non_image / mapped_path /
            is_anonymous_rwx / injection 等键。
        """
        sections: list = []
        for line in text.splitlines():
            # 格式: 7f...-7f... r-xp 00000000 08:01 12345  /path
            parts = line.split()
            if len(parts) < 2:
                continue
            addr = parts[0]
            perms = parts[1]
            mapped = parts[-1] if len(parts) >= 6 and "/" in parts[-1] else None
            try:
                start_s, end_s = addr.split("-")
                start = int(start_s, 16)
                end = int(end_s, 16)
                size = end - start
            except ValueError:
                continue
            protection = "".join(c.upper() for c in perms if c in "rwx")
            is_non_image = mapped is None
            is_rwx = ("R" in protection and "W" in protection and "X" in protection)
            is_anonymous_rwx = is_rwx and is_non_image
            # 区段类型启发式
            if mapped:
                if mapped.endswith(".so") or "/lib/" in mapped or "/usr/" in mapped:
                    stype = "image"
                elif "heap" in mapped or mapped == "[heap]":
                    stype = "heap"
                elif "stack" in mapped or mapped == "[stack]":
                    stype = "stack"
                elif mapped.lower().endswith((".jar", ".class", "jvm")):
                    stype = "jvm_generated"
                else:
                    stype = "mapped"
            else:
                stype = "mem_image" if is_anonymous_rwx else "heap"
            section = {
                "base_address": "0x" + start_s,
                "end_address": "0x" + end_s,
                "size": size,
                "protection": protection,
                "type": stype,
                "is_non_image": is_non_image,
                "pe_in_memory": False,           # Linux 无 PE 落盘语义，留待注入规则启发式
                "injection": is_anonymous_rwx,   # 匿名 RWX → 注入/反射加载启发式
                "is_anonymous_rwx": is_anonymous_rwx,
                "mapped_path": mapped,
                "evidence": "anonymous RWX region, no backing file" if is_anonymous_rwx else "",
                "confidence": 0.9 if is_anonymous_rwx else 0.3,
            }
            sections.append(section)
        return sections

    def _linux_memory_sections(self, pid: int) -> Optional[list]:
        """Linux：读 /proc/PID/maps 并裁剪到单进程上限 ≤64."""
        text = read_file_safe(f"/proc/{pid}/maps")
        if not text:
            return None
        sections = self._parse_proc_maps(text)
        if not sections:
            return None
        if len(sections) > MEM_SECTION_MAX_PER_PROCESS:
            sections = sections[:MEM_SECTION_MAX_PER_PROCESS]
        return sections

    # ── Windows 富化（best-effort，权限不足降级）────────────────
    @staticmethod
    def _windows_session(pid: Optional[int]) -> Optional[int]:
        """Windows：尝试读取进程会话 ID（TokenSessionId），失败返回 None."""
        if pid is None:
            return None
        try:
            import ctypes
            from ctypes import wintypes
            advapi32 = ctypes.windll.advapi32
            kernel32 = ctypes.windll.kernel32
            TOKEN_QUERY = 0x0008
            TokenSessionId = 12
            h_token = wintypes.HANDLE()
            proc = kernel32.OpenProcess(0x0400, False, pid)  # PROCESS_QUERY_INFORMATION
            if not proc:
                return None
            try:
                if not advapi32.OpenProcessToken(proc, TOKEN_QUERY, ctypes.byref(h_token)):
                    return None
                sid = wintypes.DWORD()
                ret_len = wintypes.DWORD()
                if not advapi32.GetTokenInformation(
                    h_token, TokenSessionId, ctypes.byref(sid),
                    ctypes.sizeof(sid), ctypes.byref(ret_len),
                ):
                    return None
                return int(sid.value)
            finally:
                kernel32.CloseHandle(proc)
        except Exception as exc:
            logger.debug("Windows session 读取失败 pid=%s: %s", pid, exc)
            return None

    @staticmethod
    def _windows_state(pid: Optional[int]) -> Optional[str]:
        """Windows：通过 psutil 读取进程状态（映射为 Running/Suspended 等）。"""
        if pid is None:
            return None
        try:
            import psutil
            p = psutil.Process(pid)
            st = p.status()
            mapping = {
                psutil.STATUS_RUNNING: "Running",
                psutil.STATUS_SLEEPING: "Sleeping",
                psutil.STATUS_DISK_SLEEP: "DiskSleep",
                psutil.STATUS_STOPPED: "Stopped",
                psutil.STATUS_ZOMBIE: "Zombie",
                psutil.STATUS_DEAD: "Dead",
                psutil.STATUS_WAKE_KILL: "WakeKill",
                psutil.STATUS_IDLE: "Idle",
            }
            return mapping.get(st, str(st))
        except Exception:
            return None

    def _windows_memory_sections(self, pid: int) -> Optional[list]:
        """Windows：VirtualQueryEx 遍历内存区段（best-effort，权限不足降级为空）.

        仅对降采样命中的进程调用；任何异常（无权限/容器隔离/不可用）均返回 None，
        绝不抛异常。遍历设上限以避免超大地址空间卡顿。
        """
        try:
            import ctypes
            from ctypes import wintypes

            kernel32 = ctypes.windll.kernel32
            PROCESS_VM_READ = 0x0010
            PROCESS_QUERY_INFORMATION = 0x0400

            class MEMORY_BASIC_INFORMATION(ctypes.Structure):
                _fields_ = [
                    ("BaseAddress", ctypes.c_void_p),
                    ("AllocationBase", ctypes.c_void_p),
                    ("AllocationProtect", wintypes.DWORD),
                    ("RegionSize", ctypes.c_size_t),
                    ("State", wintypes.DWORD),
                    ("Protect", wintypes.DWORD),
                    ("Type", wintypes.DWORD),
                ]

            h = kernel32.OpenProcess(PROCESS_VM_READ | PROCESS_QUERY_INFORMATION, False, pid)
            if not h:
                return None
            try:
                mbi = MEMORY_BASIC_INFORMATION()
                addr = 0
                max_iter = 8192
                count = 0
                sections = []
                while count < max_iter:
                    ret = kernel32.VirtualQueryEx(
                        h, ctypes.c_void_p(addr), ctypes.byref(mbi),
                        ctypes.sizeof(mbi),
                    )
                    if not ret or mbi.RegionSize == 0:
                        break
                    base = mbi.BaseAddress
                    end = ctypes.cast(base, ctypes.c_void_p).value + mbi.RegionSize
                    protect = mbi.Protect
                    # 解析 PAGE_* 权限
                    r = bool(protect & 0x02) or bool(protect & 0x40)  # READ
                    w = bool(protect & 0x04) or bool(protect & 0x80)  # WRITE
                    x = bool(protect & 0x10) or bool(protect & 0x20)  # EXECUTE
                    protection = ("R" if r else "") + ("W" if w else "") + ("X" if x else "")
                    is_anonymous_rwx = (r and w and x)
                    section = {
                        "base_address": hex(base or 0),
                        "end_address": hex(end or 0),
                        "size": int(mbi.RegionSize),
                        "protection": protection,
                        "type": "mem_image" if is_anonymous_rwx else "image",
                        "is_non_image": False,
                        "pe_in_memory": False,
                        "injection": is_anonymous_rwx,
                        "is_anonymous_rwx": is_anonymous_rwx,
                        "mapped_path": None,
                        "evidence": "anonymous RWX region" if is_anonymous_rwx else "",
                        "confidence": 0.9 if is_anonymous_rwx else 0.3,
                    }
                    sections.append(section)
                    addr = end
                    count += 1
                if not sections:
                    return None
                if len(sections) > MEM_SECTION_MAX_PER_PROCESS:
                    sections = sections[:MEM_SECTION_MAX_PER_PROCESS]
                return sections
            finally:
                kernel32.CloseHandle(h)
        except Exception as exc:
            logger.debug("Windows VirtualQueryEx 失败 pid=%s: %s", pid, exc)
            return None


def _find_col(headers: list, name: str) -> int:
    """在 CSV 表头中查找列索引（不区分大小写）."""
    for i, h in enumerate(headers):
        if h.strip().lower() == name.strip().lower():
            return i
    return 999  # 超出范围，调用方自行判断
