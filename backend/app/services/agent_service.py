"""Agent 文件服务."""

import logging
from pathlib import Path
from typing import Optional

from app.config import settings

logger = logging.getLogger(__name__)


class AgentService:
    """Agent 文件服务层."""

    @staticmethod
    def get_agent_file(os_type: str) -> Optional[str]:
        """获取对应平台的 Agent 文件路径.

        Args:
            os_type: 操作系统类型 (windows / linux).

        Returns:
            Agent 文件路径，不存在时返回 None.
        """
        agents_dir = Path(settings.AGENT_DIR)
        agents_dir.mkdir(parents=True, exist_ok=True)

        # 可能的文件名（按优先级）
        candidate_names = {
            "windows": ["agent_windows.exe", "ir_agent.exe", "IR_Agent.exe"],
            "linux": ["agent_linux", "ir_agent", "IR_Agent"],
        }

        names = candidate_names.get(os_type, [])
        if not names:
            logger.warning("Unsupported OS type: %s", os_type)
            return None

        for name in names:
            agent_file = agents_dir / name
            if agent_file.exists():
                logger.info("Found agent file: %s", agent_file)
                return str(agent_file)

        logger.warning("Agent file not found for %s in %s (searched: %s)", os_type, agents_dir, names)
        return None

    @staticmethod
    def get_agent_filename(os_type: str) -> str:
        """获取 Agent 下载时的文件名（统一命名）.

        Args:
            os_type: 操作系统类型.

        Returns:
            下载时的文件名.
        """
        if os_type == "windows":
            return "ir_agent.exe"
        elif os_type == "linux":
            return "ir_agent"
        return "ir_agent"
