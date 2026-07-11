"""R2-3 只读派发服务（v1.3.0「AI 分析作战化」）.

后端子进程直调 Agent 只读采集器：
- 仅接收 ``auto_runnable=true`` 的只读采集动作（command_or_api 来自 AI 的 recommended_actions）。
- 子进程执行 ``timeout=120s``，超时即中断（不阻塞主流程）。
- 全程经 ``AuditService.log_call`` 审计。
- **红线**：绝不执行 kill / 隔离 / 改配类命令，命令含危险关键字一律拒绝。
- 采集结果写 ``ai_evidence_refills`` 表回填证据，**不触发 AI 重算、不自动处置**。
- 任务状态存内存字典，前端经 ``GET /dispatch/{task_id}`` 轮询。
"""

import asyncio
import logging
import time
from typing import Any, Optional

from app.models.ai_evidence_refill import AiEvidenceRefill
from app.models.host import Host
from app.services.audit_service import AuditService

logger = logging.getLogger(__name__)


# v1.3.0 派发红线：禁止任何会改变系统状态 / 中断业务 / 隔离主机的命令关键字
_DANGEROUS_KEYWORDS = (
    "stop-process", "taskkill", "kill ", "kill\t", "kill\n",
    "remove-item", "remove-childitem", "rm -rf", "rm -r ", "del /f", "format ",
    "shutdown", "restart-computer", "restart-service", "stop-service",
    "net stop", "sc delete", "sc stop", "disable-", "set-service",
    "reg delete", "reg add", "netsh advfirewall set", "Disable-NetAdapter",
    "disable-computerrestore", "wbadmin delete", "bcdedit /set",
    "takeown", "icacls", "net user", "net localgroup",
)


DISPATCH_TIMEOUT_SECONDS: int = 120


class DispatchService:
    """只读派发任务管理器（进程内存态）."""

    _tasks: dict[str, dict] = {}
    _cancel_events: dict[str, asyncio.Event] = {}
    _counter: int = 0
    _lock = asyncio.Lock()

    # ──────────────────────────────────────────────
    # 公共接口
    # ──────────────────────────────────────────────

    @classmethod
    async def dispatch_readonly(
        cls,
        host_id: int,
        action_type: str,
        target: str,
        command_or_api: str,
        auto_runnable: bool = False,
        user: Optional[dict] = None,
    ) -> dict:
        """提交一条只读采集派发任务.

        Args:
            host_id: 主机 ID.
            action_type: 动作类型（见 _VALID_ACTION_TYPES）.
            target: 作用对象.
            command_or_api: 可复制的命令或 API（来自 AI recommended_actions）.
            auto_runnable: 是否声明为只读可自动执行（必须为 True 才允许派发）.
            user: 当前用户字典（用于审计 user_id）.

        Returns:
            派发任务字典（含 task_id / status）.

        Raises:
            ValueError: 非法 / 危险 / 非只读动作.
        """
        cmd = (command_or_api or "").strip()
        if not cmd:
            raise ValueError("command_or_api 不能为空")
        if not auto_runnable:
            raise ValueError("仅允许派发 auto_runnable=true 的只读采集动作（绝不自动处置）")
        cls._reject_dangerous(cmd)

        # 证据回填优先查库：network/wmi/logs 三类缺口先查 DB，
        # 已有数据则直接返回证据，不派 Agent 重采
        existing = cls.check_existing_evidence(host_id, action_type)
        if existing.get("found"):
            evidence = existing["evidence"]
            # 写入证据回填表
            refill = AiEvidenceRefill.create(
                host_id=host_id,
                dispatch_task_id="db-cached",
                evidence_json=evidence,
                action_type=action_type,
                target=target,
                status="completed",
            )
            host = Host.get_by_id(host_id)
            host_name = host.get("hostname", "") if host else ""
            AuditService.log_call(
                host_id=host_id,
                host_name=host_name,
                profile_id=None,
                profile_name="",
                model_name="readonly-collector",
                status="cached",
                error_message=f"dispatch:{action_type}:db-cached({existing.get('source', '')})",
            )
            return {
                "task_id": f"cache_{int(time.time() * 1000)}",
                "host_id": host_id,
                "action_type": action_type,
                "target": target,
                "command_or_api": cmd,
                "status": "completed",
                "evidence": evidence,
                "refill_id": refill.get("id") if refill else None,
                "error": None,
                "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                "cached": True,
                "source": existing.get("source", ""),
            }

        # 生成任务 ID（进程内唯一）
        async with cls._lock:
            cls._counter += 1
            task_id = f"disp_{int(time.time() * 1000)}_{cls._counter}"
            cls._cancel_events[task_id] = asyncio.Event()

        host = Host.get_by_id(host_id)
        host_name = host.get("hostname", "") if host else ""

        cls._tasks[task_id] = {
            "task_id": task_id,
            "host_id": host_id,
            "action_type": action_type,
            "target": target,
            "command_or_api": cmd,
            "status": "running",
            "evidence": None,
            "refill_id": None,
            "error": None,
            "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        }

        # 审计：只读采集派发
        AuditService.log_call(
            host_id=host_id,
            host_name=host_name,
            profile_id=None,
            profile_name="",
            model_name="readonly-collector",
            status="success",
            error_message=f"dispatch:{action_type}",
            user_id=user.get("id") if isinstance(user, dict) else None,
        )

        # 后台执行（不阻塞请求）
        asyncio.create_task(
            cls._run(task_id, host_id, host_name, action_type, target, cmd)
        )
        return dict(cls._tasks[task_id])

    @classmethod
    def get_status(cls, task_id: str) -> Optional[dict]:
        """查询派发任务状态（供轮询）."""
        task = cls._tasks.get(task_id)
        if not task:
            return None
        return dict(task)

    @classmethod
    def cancel(cls, task_id: str) -> bool:
        """取消正在执行的只读派发任务（仅中断采集，绝不 kill/隔离主机）."""
        ev = cls._cancel_events.get(task_id)
        if ev:
            ev.set()
            t = cls._tasks.get(task_id)
            if t and t.get("status") == "running":
                t["status"] = "cancelled"
                t["error"] = "用户取消"
                return True
        return False

    # ──────────────────────────────────────────────
    # 内部执行
    # ──────────────────────────────────────────────

    @classmethod
    async def _run(
        cls,
        task_id: str,
        host_id: int,
        host_name: str,
        action_type: str,
        target: str,
        cmd: str,
    ) -> None:
        start = time.time()
        evidence: dict[str, Any] = {
            "command": cmd,
            "target": target,
            "action_type": action_type,
            "stdout": "",
            "stderr": "",
            "return_code": None,
            "executed_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "read_only": True,
        }
        status = "completed"
        try:
            proc = await asyncio.create_subprocess_shell(
                cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                stdout_b, stderr_b = await asyncio.wait_for(
                    proc.communicate(), timeout=DISPATCH_TIMEOUT_SECONDS
                )
            except asyncio.TimeoutError:
                # 超时中断：终止子进程（仅采集进程，绝不触及主机业务）
                proc.kill()
                await proc.wait()
                evidence["stdout"] = (stdout_b or b"").decode("utf-8", "replace")
                evidence["stderr"] = (
                    (stderr_b or b"").decode("utf-8", "replace")
                    + f"\n[只读采集超时 {DISPATCH_TIMEOUT_SECONDS}s 已中断，仅返回部分结果]"
                )
                evidence["return_code"] = None
                status = "timeout"
            else:
                evidence["stdout"] = stdout_b.decode("utf-8", "replace") if stdout_b else ""
                evidence["stderr"] = stderr_b.decode("utf-8", "replace") if stderr_b else ""
                evidence["return_code"] = proc.returncode

            # 写入证据回填表（不触发 AI 重算、不自动处置）
            refill = AiEvidenceRefill.create(
                host_id=host_id,
                dispatch_task_id=task_id,
                evidence_json=evidence,
                action_type=action_type,
                target=target,
                status=status,
            )
            task = cls._tasks.get(task_id)
            if task:
                task["status"] = status
                task["evidence"] = evidence
                task["refill_id"] = refill.get("id")
        except Exception as exc:  # noqa: BLE001
            logger.exception("只读派发执行失败 task=%s", task_id)
            evidence["stderr"] = f"{evidence['stderr']}\n[执行异常] {exc}"
            status = "error"
            try:
                refill = AiEvidenceRefill.create(
                    host_id=host_id,
                    dispatch_task_id=task_id,
                    evidence_json=evidence,
                    action_type=action_type,
                    target=target,
                    status=status,
                )
                task = cls._tasks.get(task_id)
                if task:
                    task["status"] = status
                    task["evidence"] = evidence
                    task["refill_id"] = refill.get("id")
                    task["error"] = str(exc)
            except Exception:
                logger.exception("写入证据回填失败 task=%s", task_id)
        finally:
            latency_ms = int((time.time() - start) * 1000)
            AuditService.log_call(
                host_id=host_id,
                host_name=host_name,
                model_name="readonly-collector",
                status=status,
                latency_ms=latency_ms,
                error_message=f"dispatch:{action_type}:{status}",
            )
            cls._cancel_events.pop(task_id, None)

    @staticmethod
    def _reject_dangerous(cmd: str) -> None:
        """防御性拒绝任何会改变系统状态 / 隔离 / 中断业务的命令."""
        low = cmd.lower()
        for kw in _DANGEROUS_KEYWORDS:
            if kw in low:
                raise ValueError(f"拒绝执行可能改变系统状态的命令（命中红线关键字：{kw.strip()}）")

    @staticmethod
    def check_existing_evidence(host_id: int, action_type: str) -> dict:
        """证据回填优先查库：对 network/wmi/logs 三类缺口先查 DB 是否有数据.

        有数据 → 直接提取作为证据，不派 Agent；没有 → 返回空，调用方继续派发。

        Args:
            host_id: 主机 ID.
            action_type: 动作类型（如 network_extract, wmi_subscription, security_logs）.

        Returns:
            {"found": bool, "evidence": dict | None, "source": str}
        """
        action_lower = (action_type or "").lower()

        # ── 网络连接类 ──
        if any(kw in action_lower for kw in ("network", "connection", "netconn")):
            try:
                from app.models.analysis import NetworkConnection
                conns = NetworkConnection.list_by_host(host_id)
                if conns:
                    evidence_data = {
                        "network_connections": [
                            {
                                "local": f"{c.get('local_addr', '')}:{c.get('local_port', '')}",
                                "remote": f"{c.get('remote_addr', '')}:{c.get('remote_port', '')}",
                                "protocol": c.get("protocol", ""),
                                "process": c.get("process_name", ""),
                                "state": c.get("state", ""),
                                "pid": c.get("pid"),
                            }
                            for c in conns[:200]
                        ],
                        "total_count": len(conns),
                    }
                    logger.info(
                        "证据回填命中（network）: host=%d, count=%d, 跳过 Agent 派发",
                        host_id, len(conns),
                    )
                    return {"found": True, "evidence": evidence_data, "source": "network_connections_db"}
            except Exception as e:
                logger.warning("check_existing_evidence(network) failed: %s", e)

        # ── WMI 订阅类 ──
        if any(kw in action_lower for kw in ("wmi", "subscription", "event_filter")):
            try:
                from app.models.analysis import WmiSubscription
                wmis = WmiSubscription.list_by_host(host_id)
                if wmis:
                    evidence_data = {
                        "wmi_subscriptions": [
                            {
                                "name": w.get("name", ""),
                                "type": w.get("binding_type", ""),
                                "event_filter": str(w.get("event_filter", "")),
                                "event_consumer": str(w.get("event_consumer", "")),
                            }
                            for w in wmis
                        ],
                        "total_count": len(wmis),
                    }
                    logger.info(
                        "证据回填命中（wmi）: host=%d, count=%d, 跳过 Agent 派发",
                        host_id, len(wmis),
                    )
                    return {"found": True, "evidence": evidence_data, "source": "wmi_subscriptions_db"}
            except Exception as e:
                logger.warning("check_existing_evidence(wmi) failed: %s", e)

        # ── 安全事件日志类 ──
        if any(kw in action_lower for kw in ("security_log", "event_log", "security_event")):
            try:
                import json as _json
                from pathlib import Path as _Path

                from app.models.host import Host
                host = Host.get_by_id(host_id)
                raw_path = host.get("raw_json_path", "") if host else ""
                if raw_path:
                    raw_file = _Path(raw_path)
                    if raw_file.exists():
                        with open(raw_file, "r", encoding="utf-8") as f:
                            raw_data = _json.load(f)
                        logs_section = raw_data.get("logs", {}) if isinstance(raw_data, dict) else {}
                        security_logs = logs_section.get("security", [])
                        if isinstance(security_logs, list) and security_logs:
                            target_event_ids = {"4688", "4697", "4104"}
                            filtered = [
                                e for e in security_logs
                                if str(e.get("EventID", "")) in target_event_ids
                            ][:100]
                            evidence_data = {
                                "security_event_logs": filtered,
                                "total_raw_count": len(security_logs),
                                "filtered_count": len(filtered),
                            }
                            logger.info(
                                "证据回填命中（security_logs）: host=%d, raw=%d, filtered=%d, 跳过 Agent 派发",
                                host_id, len(security_logs), len(filtered),
                            )
                            return {"found": True, "evidence": evidence_data, "source": "raw_json_security_logs"}
            except Exception as e:
                logger.warning("check_existing_evidence(security_logs) failed: %s", e)

        return {"found": False, "evidence": None, "source": ""}
