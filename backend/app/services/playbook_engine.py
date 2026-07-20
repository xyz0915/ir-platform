"""剧本执行引擎 — 按 playbooks.yaml 定义逐步执行.

本模块负责"调查剧本"的逐步真实执行：
- ``query`` 步骤：依据 ``query_type`` 直接查询本地 SQLite 各业务表，返回真实数据；
- ``llm`` 步骤：把前序 ``depends_on`` 步骤的真实产出作为上下文，调用已配置的大模型，
  返回分析文本；未配置大模型时安全降级为提示文本。

对外保持 ``execute_step() -> (StepResult, step_type, params)`` 的签名不变，
但 ``StepResult.output`` 会被填上真实执行结果。
"""

import json
import logging
import time
from typing import Any

from app.database import get_connection
from app.models.ai_config import AiConfigProfile
from app.schemas.ai_advanced import PlaybookStep, PlaybookStatus, StepResult
from app.services.ai_service import AiService

logger = logging.getLogger(__name__)

# 日志/事件类步骤优先选用的两张候选表（都含 event_type 列）
_LOG_TABLE_CANDIDATES = ("normalized_logs", "security_events")

# 可作为"来源/目的 IP"提取的列名（按 PRAGMA 实际 schema 命中）
_IP_COLUMNS = (
    "source_ip",
    "dest_ip",
    "src_ip",
    "dst_ip",
    "target_ip",
    "remote_addr",
    "local_addr",
    "source_hostname",
    "target_hostname",
)


class PlaybookEngine:
    """剧本引擎 — 管理单个剧本的加载与执行."""

    def __init__(self):
        self._status: PlaybookStatus = PlaybookStatus()
        self._steps: list[PlaybookStep] = []

    @staticmethod
    def load_playbook(playbook_id: str) -> list[PlaybookStep]:
        """从 playbooks.yaml 加载剧本步骤."""
        import yaml
        import os
        yaml_path = os.path.join(os.path.dirname(__file__), "..", "data", "playbooks.yaml")
        if not os.path.exists(yaml_path):
            logger.warning("Playbook file not found: %s", yaml_path)
            return []
        with open(yaml_path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        for pb in data.get("playbooks", []):
            if pb.get("id") == playbook_id:
                return [PlaybookStep(**s) for s in pb.get("steps", [])]
        return []

    async def start(self, playbook_id: str, session_id: str) -> PlaybookStatus:
        """启动剧本执行."""
        steps = self.load_playbook(playbook_id)
        if not steps:
            return PlaybookStatus(playbook_id=playbook_id, session_id=session_id, status="failed")
        self._steps = steps
        self._status = PlaybookStatus(
            playbook_id=playbook_id, session_id=session_id,
            current_step=0, total_steps=len(steps),
            status="running", step_results=[],
            created_at=time.strftime("%Y-%m-%dT%H:%M:%S"),
        )
        return self._status

    async def get_status(self) -> PlaybookStatus:
        """获取当前执行状态."""
        return self._status

    async def control(self, action: str) -> PlaybookStatus:
        """控制剧本：pause / resume / skip / stop."""
        if action == "pause" and self._status.status == "running":
            self._status.status = "paused"
        elif action == "resume" and self._status.status == "paused":
            self._status.status = "running"
        elif action == "skip" and self._status.status == "running":
            self._status.current_step += 1
            if self._status.current_step >= self._status.total_steps:
                self._status.status = "completed"
        elif action == "stop":
            self._status.status = "stopped"
        return self._status

    # ------------------------------------------------------------------
    # 核心：真实执行单步
    # ------------------------------------------------------------------

    async def execute_step(self) -> "tuple[StepResult, str, dict]":
        """执行当前步骤，返回 (StepResult, step_type, params).

        真实执行逻辑：
        - ``query`` 步按 ``query_type`` 查询本地业务表，结果列表写入 ``output``；
        - ``llm`` 步调用已配置的大模型，分析文本写入 ``output``；
        两者都会把本步 ``StepResult``（含 ``output``）追加进 ``self._status.step_results``，
        供后续 ``llm`` 步通过 ``depends_on`` 引用前序真实产出。
        """
        if self._status.status != "running":
            return StepResult(step_id="", status="paused"), "", {}

        step = self._steps[self._status.current_step]
        now = time.strftime("%Y-%m-%dT%H:%M:%S")
        result = StepResult(
            step_id=step.id,
            status="completed",
            started_at=now,
        )

        try:
            if step.type == "query":
                output, summary = self._execute_query_step(step)
                result.output = output
                result.summary = summary
            elif step.type == "llm":
                result.output = await self._execute_llm_step(step)
            else:
                result.output = None
                result.summary = ""
        except Exception as exc:  # noqa: BLE001 — 单步失败不应中断整个剧本
            logger.exception("剧本步骤 %s 执行异常: %s", step.id, exc)
            result.status = "failed"
            result.error = str(exc)
            result.output = []
            result.summary = f"执行失败: {exc}"

        result.completed_at = time.strftime("%Y-%m-%dT%H:%M:%S")

        # 追加本步真实结果，供后续 llm 步依赖引用
        self._status.step_results.append(result)

        self._status.current_step += 1
        if self._status.current_step >= self._status.total_steps:
            self._status.status = "completed"

        return result, step.type, step.params

    # ------------------------------------------------------------------
    # query 步骤：按 query_type 分发真实 SQL
    # ------------------------------------------------------------------

    def _execute_query_step(self, step: PlaybookStep) -> "tuple[list, str]":
        """执行查询步骤，返回 (数据列表, 人类可读摘要)."""
        params: dict = step.params or {}
        query_type: str = params.get("query_type", "")
        limit: int = int(params.get("limit", 20) or 20)

        with get_connection() as conn:
            if query_type == "logs":
                event_type = params.get("event_type", "")
                table = self._resolve_log_table(conn, event_type)
                rows = conn.execute(
                    f"SELECT * FROM {table} WHERE event_type=? ORDER BY id DESC LIMIT ?",
                    (event_type, limit),
                ).fetchall()
                items = [dict(r) for r in rows]
                suffix = f"，event_type={event_type}" if event_type else ""
                return items, f"共 {len(items)} 条事件（来源表 {table}{suffix}）"

            if query_type == "alerts":
                sev = params.get("severity", "high")
                rows = conn.execute(
                    "SELECT * FROM alerts WHERE severity=? ORDER BY last_seen_at DESC LIMIT ?",
                    (sev, limit),
                ).fetchall()
                items = [dict(r) for r in rows]
                return items, f"共 {len(items)} 条告警（severity={sev}）"

            if query_type == "abnormal_processes":
                if not self._table_exists(conn, "abnormal_processes"):
                    return [], "abnormal_processes 表不存在，无数据"
                rows = conn.execute(
                    "SELECT * FROM abnormal_processes ORDER BY id DESC LIMIT ?", (limit,)
                ).fetchall()
                items = [dict(r) for r in rows]
                return items, f"共 {len(items)} 条异常进程"

            if query_type == "network_connections":
                if not self._table_exists(conn, "network_connections"):
                    return [], "network_connections 表不存在，无数据"
                rows = conn.execute(
                    "SELECT * FROM network_connections ORDER BY id DESC LIMIT ?", (limit,)
                ).fetchall()
                items = [dict(r) for r in rows]
                return items, f"共 {len(items)} 条网络连接"

            if query_type == "file_hashes":
                if not self._table_exists(conn, "file_hashes"):
                    return [], "file_hashes 表不存在，无数据"
                rows = conn.execute(
                    "SELECT * FROM file_hashes ORDER BY id DESC LIMIT ?", (limit,)
                ).fetchall()
                items = [dict(r) for r in rows]
                return items, f"共 {len(items)} 条文件哈希"

            if query_type == "extract_ips":
                table = self._resolve_log_table(conn, "")
                cols = [r["name"] for r in conn.execute(
                    f"PRAGMA table_info({table})").fetchall()]
                ip_cols = [c for c in cols if c in _IP_COLUMNS]
                if not ip_cols:
                    return [], f"{table} 无可用 IP 列，无法提取来源/目的 IP"
                union_parts = [
                    f"SELECT {c} AS ip FROM {table} WHERE {c} IS NOT NULL AND {c} <> ''"
                    for c in ip_cols
                ]
                sql = " UNION ".join(union_parts) + " ORDER BY ip LIMIT ?"
                rows = conn.execute(sql, (limit,)).fetchall()
                ips = [{"ip": r["ip"]} for r in rows]
                return ips, f"共 {len(ips)} 个去重 IP（来源表 {table}）"

            # 未支持的 query_type
            return [], f"未支持的 query_type: {query_type}"

    # ------------------------------------------------------------------
    # llm 步骤：调用大模型（带前序步骤上下文）
    # ------------------------------------------------------------------

    async def _execute_llm_step(self, step: PlaybookStep) -> str:
        """执行 LLM 分析步骤，返回分析文本字符串.

        把 ``depends_on`` 指向的前序步骤真实 ``output`` 摘要拼入 user_prompt，
        再调用已激活的大模型 Profile；无激活配置时安全降级返回提示文本。
        """
        params: dict = step.params or {}
        prompt: str = params.get("prompt", "")

        # 拼接前序依赖步骤的真实产出摘要
        context_parts: list[str] = []
        for dep_id in (step.depends_on or []):
            dep_snippet = self._get_dep_output_snippet(dep_id)
            if dep_snippet:
                context_parts.append(f"【步骤 {dep_id} 的真实结果摘要】\n{dep_snippet}")

        user_prompt = prompt
        if context_parts:
            user_prompt = prompt + "\n\n" + "\n\n".join(context_parts)

        # 调用已激活的大模型配置
        try:
            profile = AiConfigProfile.get_active()
            if not profile:
                return f"未配置大模型，跳过AI分析（步骤：{prompt[:20]}...）"

            api_key = AiService.decrypt_api_key(profile["api_key"])
            system_prompt = (
                profile.get("system_prompt")
                or "你是一个专业的网络安全应急响应分析专家。请基于给定的调查数据进行分析，"
                   "使用中文、结构清晰、结论明确，必要时给出证据与处置建议。"
            )
            llm_response = await AiService.call_llm(
                api_base_url=profile["api_base_url"],
                api_key=api_key,
                model=profile.get("model_name", "gpt-4o"),
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                max_tokens=int(profile.get("max_tokens", 1500) or 1500),
                temperature=float(profile.get("temperature", 0.3) or 0.3),
            )
            choices = llm_response.get("choices", [])
            if choices:
                content = choices[0].get("message", {}).get("content", "").strip()
                return content or "大模型返回为空，无法生成分析。"
            return "大模型返回为空，无法生成分析。"
        except Exception as exc:  # noqa: BLE001 — 降级而非崩溃
            logger.warning("剧本 LLM 步骤 %s 调用失败，降级返回: %s", step.id, exc)
            return f"大模型调用失败（已降级）: {prompt[:20]}... 错误: {exc}"

    # ------------------------------------------------------------------
    # 工具方法
    # ------------------------------------------------------------------

    def _table_exists(self, conn, table: str) -> bool:
        """判断表是否存在."""
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,)
        ).fetchone()
        return row is not None

    def _resolve_log_table(self, conn, event_type: str = "") -> str:
        """选择用于 logs / extract_ips 的事件表.

        - 优先从候选表中选出含 ``event_type`` 列且存在匹配行的表（PRAGMA 探明 schema）；
        - 若无匹配行，则优先返回 ``normalized_logs``（该表既含 event_type 又含
          source_ip/target_ip 等 IP 列，且与现有 ``/ai/query`` 的 logs 意图一致）；
        - 兜底返回首个含 event_type 列的候选表。
        """
        candidates: list[str] = []
        for tbl in _LOG_TABLE_CANDIDATES:
            if not self._table_exists(conn, tbl):
                continue
            cols = [r["name"] for r in conn.execute(
                f"PRAGMA table_info({tbl})").fetchall()]
            if "event_type" in cols:
                candidates.append(tbl)

        if not candidates:
            return "normalized_logs"  # 兜底，调用方会捕获后续异常

        if event_type:
            for tbl in candidates:
                try:
                    cnt = conn.execute(
                        f"SELECT COUNT(*) FROM {tbl} WHERE event_type=?", (event_type,)
                    ).fetchone()[0]
                except Exception:
                    cnt = 0
                if cnt > 0:
                    return tbl

        # 无匹配行时优先归一化日志表（含 IP 列，更有用）
        if "normalized_logs" in candidates:
            return "normalized_logs"
        return candidates[0]

    def _get_dep_output_snippet(self, dep_id: str) -> str:
        """从已执行步骤结果中取指定 step_id 的 output 摘要（截断）."""
        for sr in self._status.step_results:
            if sr.step_id == dep_id and sr.output is not None:
                out = sr.output
                if isinstance(out, list):
                    snippet = json.dumps(out[:3], ensure_ascii=False, default=str)
                    if len(snippet) > 1500:
                        snippet = snippet[:1500] + "...(截断)"
                    return f"前 {min(3, len(out))} 条样本（共 {len(out)} 条）：\n{snippet}"
                if isinstance(out, str):
                    return out[:1500]
                return str(out)[:1500]
        return ""
