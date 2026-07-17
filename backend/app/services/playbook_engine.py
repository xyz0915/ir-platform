"""剧本执行引擎 — 按 playbooks.yaml 定义逐步执行."""
import logging
import time
from typing import Any
from app.schemas.ai_advanced import PlaybookStep, PlaybookStatus, StepResult

logger = logging.getLogger(__name__)


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

    async def execute_step(self) -> "tuple[StepResult, str, dict]":
        """执行当前步骤，返回 (StepResult, step_type, params)."""
        if self._status.status != "running":
            return StepResult(step_id="", status="paused"), "", {}
        step = self._steps[self._status.current_step]
        result = StepResult(
            step_id=step.id, status="completed",
            started_at=time.strftime("%Y-%m-%dT%H:%M:%S"),
        )
        self._status.current_step += 1
        if self._status.current_step >= self._status.total_steps:
            self._status.status = "completed"
        return result, step.type, step.params
