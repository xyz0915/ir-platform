"""内存码采集器（Java 内存马 / PHP 扩展，融合 §2.2 / §三.1）.

平台分工：
- Linux：以 Java 为主（``jcmd GC.class_histogram`` / ``jstack`` / JVM 探针 +
  ``/proc/PID/maps`` 字符串），定位 java 进程（依赖 ProcessesCollector 富化）。
- Windows：以 PHP/IIS 为主（``/proc`` 不可用，退化读进程模块 / 命令行启发式，
  标 ``confidence: low``）。

所有探针经 safe_collect / try-except 保护，权限不足或容器隔离时降级（标 low / 跳过），
绝不抛异常拖垮 Agent。无 macOS 分支（与主决策一致）。
"""

import logging
import re
from typing import List, Optional

from collectors.base_collector import BaseCollector
from utils.platform import is_windows, is_linux, run_command, read_file_safe

logger = logging.getLogger(__name__)

# 可疑类特征（内存马常见命名）
_SUSPICIOUS_CLASS_RE = re.compile(
    r"(MemShell|Godzilla|Behinder|Shell|Filter|Agent|EventHandler|"
    r"ClassLoader|Spring|StandardContext)",
    re.IGNORECASE,
)
# 随机化长类名（疑似动态注册的内存马 Filter/Servlet）
_RANDOM_CLASS_RE = re.compile(r"[A-Za-z0-9_]{16,}\.(?:Filter|Servlet|Listener|Interceptor)")
# 异常线程特征
_SUSPICIOUS_THREAD_RE = re.compile(
    r"(ClassFileTransformer|non-daemon|Transformer|attach|Instrumentation)",
    re.IGNORECASE,
)
# 外连信号（IP:port）
_CONN_RE = re.compile(r"\b(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}:\d+)\b")
# Agent 探针信号
_AGENT_SIG_RE = re.compile(r"(-javaagent|agent\.jar|Instrumentation|ByteBuddy|ClassFileTransformer)", re.IGNORECASE)

# Java / PHP / IIS 进程名（用于定位内存马宿主）
_JAVA_NAMES = ("java", "javaw", "tomcat", "spring", "jar")
_PHP_NAMES = ("php", "php-cgi", "php-fpm", "php.exe")
_IIS_NAMES = ("w3wp", "iisexpress")


class MemoryShellCollector(BaseCollector):
    """内存码采集器."""

    name = "memory_shells"
    platform = ["windows", "linux"]

    # ── 纯解析函数（便于单测）──────────────────────────────────
    @staticmethod
    def analyze_class_histogram(text: str) -> List[str]:
        """解析 ``jcmd GC.class_histogram`` 输出，提取可疑类信号.

        jcmd 输出形如 ``   1:     123   4567   com.xxx.MemShellFilter``。

        Returns:
            可疑类名列表（去重）。
        """
        if not text:
            return []
        signals = []
        for line in text.splitlines():
            # 跳过表头/汇总行
            m = re.search(r"([A-Za-z_][\w.$]*(?:Filter|Servlet|Listener|Interceptor|Agent|Shell|ClassLoader|EventHandler|Spring|StandardContext)[\w.$]*)", line)
            if not m:
                # 随机长类名兜底
                m2 = _RANDOM_CLASS_RE.search(line)
                if m2:
                    signals.append(m2.group(0))
                continue
            cls = m.group(1)
            if _SUSPICIOUS_CLASS_RE.search(cls) or _RANDOM_CLASS_RE.search(cls):
                if cls not in signals:
                    signals.append(cls)
        return signals

    @staticmethod
    def analyze_jstack(text: str) -> List[str]:
        """解析 ``jstack`` 输出，提取异常线程信号."""
        if not text:
            return []
        signals = []
        for line in text.splitlines():
            if _SUSPICIOUS_THREAD_RE.search(line):
                # 提取线程名
                tm = re.search(r'"(.*?)"', line)
                name = tm.group(1) if tm else line.strip()
                if name and name not in signals:
                    signals.append(name)
        return signals

    @staticmethod
    def analyze_proc_maps(text: str) -> dict:
        """解析 ``/proc/PID/maps`` 文本，提取 Agent/外连信号（启发式）."""
        out = {"agent_signals": [], "conn_signals": [], "evidence": []}
        if not text:
            return out
        for m in _AGENT_SIG_RE.finditer(text):
            s = m.group(0)
            if s not in out["agent_signals"]:
                out["agent_signals"].append(s)
        for m in _CONN_RE.finditer(text):
            ip = m.group(1)
            if ip not in out["conn_signals"]:
                out["conn_signals"].append(ip)
        return out

    @staticmethod
    def build_memory_shell(
        pid: int,
        process_name: str,
        shell_type: str,
        class_signals: List[str],
        agent_signals: List[str],
        conn_signals: List[str],
        thread_signals: List[str],
        evidence: List[str],
        confidence: str,
        detect_method: str,
    ) -> dict:
        """构造内存码证据 dict（pid 为与进程富化的关联锚点）."""
        return {
            "pid": pid,
            "process_name": process_name,
            "type": shell_type,
            "evidence": "; ".join(evidence) if evidence else "内存马特征命中",
            "class_signals": class_signals,
            "agent_signals": agent_signals,
            "conn_signals": conn_signals,
            "thread_signals": thread_signals,
            "confidence": confidence,
            "detect_method": detect_method,
        }

    # ── 平台探针（best-effort，安全隔离）──────────────────────
    def _probe_java_linux(self, pid: int, process_name: str) -> Optional[dict]:
        """Linux Java 进程 JVM 探针（jcmd/jstack/maps）."""
        signals: dict = {
            "class_signals": [], "agent_signals": [], "conn_signals": [],
            "thread_signals": [], "evidence": [],
        }
        confidence = "low"
        detect_methods = []

        # 1) jcmd GC.class_histogram
        try:
            hist = run_command(f"jcmd {pid} GC.class_histogram 2>/dev/null", timeout=25)
            if hist and "class" in hist.lower():
                signals["class_signals"] = self.analyze_class_histogram(hist)
                detect_methods.append("jcmd_class_histogram")
        except Exception as exc:
            logger.debug("jcmd 失败 pid=%s: %s", pid, exc)

        # 2) jstack
        try:
            js = run_command(f"jstack {pid} 2>/dev/null", timeout=25)
            if js:
                signals["thread_signals"] = self.analyze_jstack(js)
                detect_methods.append("jstack")
        except Exception as exc:
            logger.debug("jstack 失败 pid=%s: %s", pid, exc)

        # 3) /proc/PID/maps 字符串
        try:
            maps = read_file_safe(f"/proc/{pid}/maps")
            if maps:
                mp = self.analyze_proc_maps(maps)
                signals["agent_signals"].extend(mp["agent_signals"])
                signals["conn_signals"].extend(mp["conn_signals"])
                detect_methods.append("proc_maps")
        except Exception as exc:
            logger.debug("/proc/%s/maps 读取失败: %s", pid, exc)

        # 证据与置信度
        if signals["class_signals"]:
            confidence = "high"
            signals["evidence"].append("异常类: " + ", ".join(signals["class_signals"][:5]))
        if signals["agent_signals"]:
            signals["evidence"].append("Agent探针: " + ", ".join(signals["agent_signals"][:5]))
        if signals["conn_signals"]:
            signals["evidence"].append("可疑外连: " + ", ".join(signals["conn_signals"][:5]))
        if signals["thread_signals"]:
            signals["evidence"].append("异常线程: " + ", ".join(signals["thread_signals"][:5]))

        # 无任何信号 → 跳过（不产出噪音）
        if not (signals["class_signals"] or signals["agent_signals"]
                or signals["conn_signals"] or signals["thread_signals"]):
            return None

        shell_type = "java_filter" if signals["class_signals"] else (
            "java_agent" if signals["agent_signals"] else "unknown"
        )
        return self.build_memory_shell(
            pid, process_name, shell_type,
            signals["class_signals"], signals["agent_signals"],
            signals["conn_signals"], signals["thread_signals"],
            signals["evidence"], confidence,
            "+".join(detect_methods) or "unknown",
        )

    def _probe_php_windows(self, pid: int, process_name: str) -> Optional[dict]:
        """Windows PHP/IIS 进程探针（best-effort 降级）.

        Windows 无 /proc，内存读取需特权 API；此处仅做进程模块 / 命令行启发式，
        标 ``confidence: low`` 表示降级路径。
        """
        signals: dict = {"agent_signals": [], "conn_signals": [], "evidence": []}
        try:
            modules = run_command(
                f'wmic process where ProcessId={pid} get CommandLine /format:list 2>nul',
                timeout=15,
            )
            if modules:
                if _AGENT_SIG_RE.search(modules):
                    signals["agent_signals"].append("javaagent-like")
                for m in _CONN_RE.finditer(modules):
                    signals["conn_signals"].append(m.group(1))
                if signals["agent_signals"] or signals["conn_signals"]:
                    signals["evidence"].append("进程命令行异常: " + modules.strip()[:120])
        except Exception as exc:
            logger.debug("Windows PHP 探针失败 pid=%s: %s", pid, exc)

        if not (signals["agent_signals"] or signals["conn_signals"]):
            return None
        return self.build_memory_shell(
            pid, process_name, "php",
            [], signals["agent_signals"], signals["conn_signals"], [],
            signals["evidence"], "low", "wmic_cmdline",
        )

    # ── 主采集流程 ────────────────────────────────────────────
    def collect(self) -> List[dict]:
        """执行内存码采集.

        Returns:
            memory_shells[] 列表（每项含 pid/type/evidence/class_signals/...）。
            未定位到目标进程或探针全部降级失败时返回空列表。
        """
        processes = self._get_processes()
        targets = self._select_targets(processes)
        if not targets:
            logger.info("未定位到 Java/PHP/IIS 目标进程，跳过内存码采集")
            return []

        results: List[dict] = []
        for pid, name, kind in targets:
            try:
                if kind == "java" and is_linux():
                    item = self._probe_java_linux(pid, name)
                elif kind == "php" and is_windows():
                    item = self._probe_php_windows(pid, name)
                else:
                    # 跨平台降级：Linux PHP 用 /proc 字符串，Windows Java 暂不支持
                    item = self._probe_fallback(pid, name, kind)
                if item:
                    results.append(item)
            except Exception as exc:
                logger.warning("内存码探针异常 pid=%s: %s", pid, exc)
        logger.info("内存码采集完成，命中 %d 个", len(results))
        return results

    @staticmethod
    def _get_processes() -> List[dict]:
        """获取进程列表（依赖 ProcessesCollector；失败返回空）."""
        try:
            from collectors.processes import ProcessesCollector
            data = ProcessesCollector().safe_collect()
            if isinstance(data, list):
                return data
        except Exception as exc:
            logger.warning("获取进程列表失败: %s", exc)
        return []

    @staticmethod
    def _select_targets(processes: List[dict]) -> List[tuple]:
        """筛选 Java（Linux）/ PHP·IIS（Windows）目标进程."""
        targets: List[tuple] = []
        for proc in processes:
            if not isinstance(proc, dict):
                continue
            name = str(proc.get("name", "")).lower()
            pid = proc.get("pid")
            if pid is None:
                continue
            if is_linux() and any(n in name for n in _JAVA_NAMES):
                targets.append((pid, proc.get("name", ""), "java"))
            elif is_windows() and (any(n in name for n in _PHP_NAMES) or any(n in name for n in _IIS_NAMES)):
                targets.append((pid, proc.get("name", ""), "php"))
        return targets

    def _probe_fallback(self, pid: int, name: str, kind: str) -> Optional[dict]:
        """跨平台降级探针（Linux PHP 读 /proc maps；其余返回 None）."""
        if kind == "php" and is_linux():
            try:
                maps = read_file_safe(f"/proc/{pid}/maps")
                mp = self.analyze_proc_maps(maps) if maps else {}
                if mp.get("agent_signals") or mp.get("conn_signals"):
                    return self.build_memory_shell(
                        pid, name, "php",
                        [], mp.get("agent_signals", []), mp.get("conn_signals", []), [],
                        ["PHP 进程内存映射异常"], "low", "proc_maps",
                    )
            except Exception as exc:
                logger.debug("Linux PHP 降级探针失败 pid=%s: %s", pid, exc)
        return None
