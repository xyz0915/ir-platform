"""进程树构建器 — 将进程列表转为树形结构用于可视化展示."""

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)


class ProcessTreeBuilder:
    """进程树构建器.

    将扁平的进程列表转为树形结构，用于前端 ECharts tree series 渲染。
    支持异常进程标记、攻击路径标注、孤儿进程处理。
    """

    @staticmethod
    def build(processes: list, abnormal_pids: set, pid_to_info: dict) -> dict:
        """构建进程树.

        Args:
            processes: 所有进程列表（扁平结构）.
            abnormal_pids: 异常进程 PID 集合.
            pid_to_info: PID→进程信息映射（来自 AbnormalProcess 数据，含 risk_score/matched_rules/attack_path）.

        Returns:
            树形结构字典，用于 ECharts tree series 渲染。
            格式: {name, children: [...]} 每个节点含 pid, name, process_name, process_path,
            command_line, is_abnormal, risk_score, matched_rules 等属性。
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
                abnormal_pids, pid_to_info, set()
            )
            root_nodes.append(node)

        # 处理孤儿进程（有 ppid 但父进程不在列表中的，已在 _find_roots 中处理）
        # 如果只有一个根节点直接返回它，否则包裹在虚拟根节点中
        if len(root_nodes) == 1:
            return root_nodes[0]
        elif len(root_nodes) > 1:
            return {
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
    ) -> dict:
        """递归构建子树.

        Args:
            pid: 当前进程 PID.
            pid_to_proc: PID→进程映射.
            pid_to_children: PID→子进程列表映射.
            abnormal_pids: 异常 PID 集合.
            pid_to_info: PID→异常进程信息映射.
            visited: 已访问的 PID 集合，用于检测循环引用防止无限递归.

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
            return {
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
                abnormal_pids, pid_to_info, visited
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

        return node
