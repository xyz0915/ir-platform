"""进程树构建器 — 将进程列表转为树形结构用于可视化展示.

向后兼容说明：
- ``build`` / ``_build_tree_recursive`` 在签名末尾新增可选关键字参数 ``enrich``
  （默认 ``False``）。当 ``enrich=False`` 时，输出节点 dict 与历史版本**逐字段一致**，
  旧前端（``ProcessTreeChart``）可照常工作。
- 当 ``enrich=True`` 时，仅在节点 dict 上**增量追加**新字段（severity / parent_pid /
  parent_name / start_time / user / threads / status / connections /
  attack_chain_step / attack_chain_total / session），旧字段全部保留。
"""

import json
import logging
import re
from typing import Any, Optional

logger = logging.getLogger(__name__)

# attack_path 解析用正则（模块级编译，避免重复编译）。
# 约定 A：显式 "N/M"（step/total）字符串。
_ATTACK_CHAIN_NM_RE = re.compile(r"^\s*(\d+)\s*/\s*(\d+)\s*$")
# 主解析：进程名之间用分隔符连接，支持 " → " / "->" / "=>" / "—>"。
_ATTACK_CHAIN_SEP_RE = re.compile(r"\s*(?:->|→|=>|—>)\s*")


class ProcessTreeBuilder:
    """进程树构建器.

    将扁平的进程列表转为树形结构，用于前端 ECharts tree series 渲染。
    支持异常进程标记、攻击路径标注、孤儿进程处理。
    """

    @staticmethod
    def build(
        processes: list,
        abnormal_pids: set,
        pid_to_info: dict,
        enrich: bool = False,
    ) -> dict:
        """构建进程树.

        Args:
            processes: 所有进程列表（扁平结构）.
            abnormal_pids: 异常进程 PID 集合.
            pid_to_info: PID→进程信息映射（来自 AbnormalProcess 数据，含 risk_score/matched_rules/attack_path）.
            enrich: 是否增量追加增强字段（severity/parent_name/connections/...）。
                默认 False → 行为与历史版本完全一致，旧前端可继续工作。

        Returns:
            树形结构字典。
            格式: {name, children: [...]} 每个节点含 pid, name, process_name, process_path,
            command_line, is_abnormal, risk_score, matched_rules, attack_path 等属性；
            当 enrich=True 时额外含 severity/parent_pid/parent_name/start_time/user/threads/
            status/connections/attack_chain_step/attack_chain_total/session。
        """
        if not processes:
            return {"name": "(empty)", "children": []}

        # 构建 pid→children 映射
        pid_to_children: dict[int, list] = {}
        pid_to_proc: dict[int, dict] = {}

        for proc in processes:
            if not isinstance(proc, dict):
                continue
            pid = proc.get("pid")
            if pid is None:
                continue
            pid_to_proc[pid] = proc
            ppid = proc.get("ppid", 0)
            if ppid not in pid_to_children:
                pid_to_children[ppid] = []
            pid_to_children[ppid].append(proc)

        # 找根进程（ppid=0 或 ppid 不在进程列表中）
        roots = ProcessTreeBuilder._find_roots(processes, pid_to_proc)

        # 递归构建子树（传入空 visited set 以检测循环引用）
        root_nodes = []
        for root_proc in roots:
            root_pid = root_proc.get("pid", 0)
            node = ProcessTreeBuilder._build_tree_recursive(
                root_pid, pid_to_proc, pid_to_children,
                abnormal_pids, pid_to_info, set(), enrich,
            )
            root_nodes.append(node)

        # 处理孤儿进程（有 ppid 但父进程不在列表中的，已在 _find_roots 中处理）
        # 如果只有一个根节点直接返回它，否则包裹在虚拟根节点中
        if len(root_nodes) == 1:
            return root_nodes[0]
        elif len(root_nodes) > 1:
            root = {
                "name": "All Processes",
                "children": root_nodes,
                "pid": None,
                "process_name": "",
                "process_path": "",
                "command_line": "",
                "is_abnormal": False,
                "risk_score": 0,
                "matched_rules": [],
            }
            if enrich:
                # 虚拟根不是真实进程，增强字段全部取默认值；其 status 应保持 "运行中"
                # （无 state 信息，不应判为僵尸），故显式置为 "运行中"。
                root.update(
                    ProcessTreeBuilder._build_enrich_fields(
                        {}, {}, False, {}, None, "All Processes"
                    )
                )
                root["status"] = "运行中"
            return root
        else:
            return {"name": "(empty)", "children": []}

    @staticmethod
    def _find_roots(processes: list, pid_to_proc: dict) -> list:
        """找根进程.

        根进程定义：ppid=0 或 ppid 不在进程列表中。
        孤儿进程（有 ppid 但父进程不在列表中）作为独立根节点，name 标注 "(orphan process)".

        Args:
            processes: 进程列表.
            pid_to_proc: PID→进程映射.

        Returns:
            根进程列表.
        """
        roots = []
        for proc in processes:
            if not isinstance(proc, dict):
                continue
            ppid = proc.get("ppid", 0)
            # ppid=0 或父进程不在列表中 → 根进程/孤儿进程
            if ppid == 0 or ppid not in pid_to_proc:
                # 如果 ppid != 0 且父不在列表，标注为孤儿进程
                if ppid != 0 and ppid not in pid_to_proc:
                    proc_name = proc.get("name", "")
                    proc["_is_orphan"] = True
                roots.append(proc)
        return roots

    @staticmethod
    def _build_tree_recursive(
        pid: int,
        pid_to_proc: dict,
        pid_to_children: dict,
        abnormal_pids: set,
        pid_to_info: dict,
        visited: set,
        enrich: bool = False,
    ) -> dict:
        """递归构建子树.

        Args:
            pid: 当前进程 PID.
            pid_to_proc: PID→进程映射.
            pid_to_children: PID→子进程列表映射.
            abnormal_pids: 异常 PID 集合.
            pid_to_info: PID→异常进程信息映射.
            visited: 已访问的 PID 集合，用于检测循环引用防止无限递归.
            enrich: 是否增量追加增强字段（见 ``build`` 说明）.

        Returns:
            子树节点字典.
        """
        # 检测循环引用：如果当前 PID 已在 visited 中，说明存在循环引用
        # 直接返回一个标记节点，不再继续递归
        if pid in visited:
            proc = pid_to_proc.get(pid, {})
            proc_name = proc.get("name", "unknown")
            logger.warning(
                "Circular reference detected in process tree: PID %s "
                "(process: %s) already visited, skipping further recursion.",
                pid, proc_name,
            )
            circular = {
                "name": f"{proc_name} (circular reference)",
                "pid": pid,
                "process_name": proc_name,
                "process_path": proc.get("path", ""),
                "command_line": proc.get("command_line", ""),
                "is_abnormal": pid in abnormal_pids,
                "risk_score": 0,
                "matched_rules": [],
                "attack_path": None,
                "children": [],
            }
            if enrich:
                circular.update(
                    ProcessTreeBuilder._build_enrich_fields(
                        proc, pid_to_info.get(pid, {}), pid in abnormal_pids,
                        pid_to_proc, None, proc_name,
                    )
                )
            return circular

        # 将当前 PID 加入 visited 集合
        visited = visited | {pid}

        proc = pid_to_proc.get(pid, {})
        is_orphan = proc.get("_is_orphan", False)
        is_abnormal = pid in abnormal_pids

        # 获取异常进程额外信息
        info = pid_to_info.get(pid, {})
        risk_score = info.get("risk_score", 0) if is_abnormal else 0
        matched_rules = info.get("matched_rules", []) if is_abnormal else []
        attack_path = info.get("attack_path", None) if is_abnormal else None

        # 构建节点名称
        proc_name = proc.get("name", "unknown")
        if is_orphan:
            display_name = f"{proc_name} (orphan process)"
        else:
            display_name = proc_name

        # 构建子节点
        children_procs = pid_to_children.get(pid, [])
        children_nodes = []
        for child_proc in children_procs:
            child_pid = child_proc.get("pid", 0)
            child_node = ProcessTreeBuilder._build_tree_recursive(
                child_pid, pid_to_proc, pid_to_children,
                abnormal_pids, pid_to_info, visited, enrich,
            )
            children_nodes.append(child_node)

        node = {
            "name": display_name,
            "pid": pid,
            "process_name": proc_name,
            "process_path": proc.get("path", ""),
            "command_line": proc.get("command_line", ""),
            "is_abnormal": is_abnormal,
            "risk_score": risk_score,
            "matched_rules": matched_rules,
            "attack_path": attack_path,
            "children": children_nodes,
        }

        # 增量增强：仅在 enrich=True 时追加新字段，旧字段保持不变。
        if enrich:
            node.update(
                ProcessTreeBuilder._build_enrich_fields(
                    proc, info, is_abnormal, pid_to_proc, attack_path, proc_name
                )
            )

        return node

    @staticmethod
    def _build_enrich_fields(
        proc: Any,
        info: Any,
        is_abnormal: bool,
        pid_to_proc: dict,
        attack_path: Any,
        proc_name: str,
    ) -> dict:
        """构建 enrich=True 时增量追加的增强字段.

        数据来源：
        - severity：异常进程取 ``pid_to_info[pid].get("severity")``，非异常为 ``None``。
        - parent_pid：原始 proc 的 ppid。
        - parent_name：异常优先取异常表 parent_name；否则取父进程（pid_to_proc[ppid]）的 name；兜底 ""。
        - start_time / user / threads / connections：直接透传 proc 对应字段（采集端已提供）。
          threads 仅作为展示字段存入节点 ``threads``，不再用于判定 status。
        - status：派生字段，仅当 proc 显式 ``state`` ∈ {z, zombie, defunct} 时为 "疑似僵尸"，
          其余（含 threads==0、state 缺失或非僵尸状态）均为 "运行中"。
          这样可避免回退采集环境（wmic/tasklist 给每个进程写死 threads=0）误报僵尸。
        - session：当前无数据源，留 ""（前端标注"无数据"降级）。
        - attack_chain_step / attack_chain_total：由 ``_parse_attack_chain`` 解析 attack_path 得到。

        Args:
            proc: 当前进程原始 dict（可能为空 dict，如虚拟根）.
            info: 异常进程信息 dict（pid_to_info[pid]，可能为空 dict）.
            is_abnormal: 是否为异常进程.
            pid_to_proc: PID→原始进程映射（用于推导 parent_name）.
            attack_path: 异常表的攻击路径字符串（可能为空）.
            proc_name: 当前进程名（用于 attack_path 定位 step）.

        Returns:
            增强字段 dict.
        """
        proc = proc if isinstance(proc, dict) else {}
        info = info if isinstance(info, dict) else {}
        pid_to_proc = pid_to_proc if isinstance(pid_to_proc, dict) else {}

        ppid = proc.get("ppid", 0) or 0

        # severity：仅异常进程取异常表值，否则 None（前端按"无严重度"处理）。
        severity = info.get("severity") if is_abnormal else None

        # parent_name：异常优先取异常表 parent_name；否则取父进程 name；兜底 ""。
        if is_abnormal and info.get("parent_name"):
            parent_name = info.get("parent_name")
        elif ppid:
            parent_name = pid_to_proc.get(ppid, {}).get("name", "")
        else:
            parent_name = ""

        start_time = proc.get("start_time", "") or ""
        user = proc.get("user", "") or ""
        threads = proc.get("threads", 0) or 0
        # status 仅由进程显式 state 判定僵尸，不再用 threads==0（回退采集环境
        # 会把每个进程 threads 写死为 0，导致全判"疑似僵尸"误报）。
        state = (proc.get("state") or "").strip().lower()
        status = "疑似僵尸" if state in ("z", "zombie", "defunct") else "运行中"
        connections = proc.get("connections", []) or []
        session = ""  # 无数据源，降级为空

        step, total = ProcessTreeBuilder._parse_attack_chain(attack_path, proc_name)

        return {
            "severity": severity,
            "parent_pid": ppid,
            "parent_name": parent_name,
            "start_time": start_time,
            "user": user,
            "threads": threads,
            "status": status,
            "connections": connections,
            "attack_chain_step": step,
            "attack_chain_total": total,
            "session": session,
        }

    @staticmethod
    def _parse_attack_chain(attack_path: Any, proc_name: str) -> tuple:
        """解析 attack_path，得到 (attack_chain_step, attack_chain_total)。

        本代码库中 attack_path 的真实序列化格式（见
        ``rules/rule_engine.py:_match_attack_chain`` 与
        ``analysis/anomaly_detector.py``）：
        - **主格式**：进程名字符串，用 " → "（或 "->" / "=>"）连接，
          例如 ``"explorer.exe → WINWORD.EXE → powershell.exe → cmd.exe → certutil.exe"``。
          解析时按进程名（大小写不敏感）在链中定位当前进程，得到 1-based step；
          total = 链长度。
        - **约定 A（兼容）**：``"N/M"`` 字符串，直接得到 step=N, total=M。
        - **约定 B（兼容）**：JSON 数组 / list of names，total=长度，step 按进程名反查。
        - 解析失败 / 空 / 非异常进程 → (None, None)。

        注意：本方法**只读取** attack_path，绝不修改异常检测 / 落库逻辑。

        Args:
            attack_path: 异常进程 attack_path（可能为空 / 字符串 / 列表）。
            proc_name: 当前进程名，用于在主格式中定位 step。

        Returns:
            (step, total) —— 任一不可得时为 None。
        """
        if not attack_path:
            return (None, None)

        name = (proc_name or "").strip().lower()

        # 约定 A：显式 "N/M"
        if isinstance(attack_path, str):
            m = _ATTACK_CHAIN_NM_RE.match(attack_path)
            if m:
                return (int(m.group(1)), int(m.group(2)))

        # 列表 / JSON 数组（约定 B）
        chain_names = None
        if isinstance(attack_path, (list, tuple)):
            chain_names = [str(x) for x in attack_path]
        elif isinstance(attack_path, str):
            s = attack_path.strip()
            if s.startswith("["):
                try:
                    parsed = json.loads(s)
                    if isinstance(parsed, (list, tuple)):
                        chain_names = [str(x) for x in parsed]
                except (ValueError, TypeError):
                    chain_names = None

        # 主格式：进程名用分隔符连接
        if chain_names is None and isinstance(attack_path, str):
            chain_names = [
                p.strip()
                for p in _ATTACK_CHAIN_SEP_RE.split(attack_path)
                if p.strip()
            ]

        if chain_names:
            total = len(chain_names)
            step = None
            if name:
                for i, c in enumerate(chain_names, start=1):
                    if c.strip().lower() == name:
                        step = i
                        break
            return (step, total)

        return (None, None)
