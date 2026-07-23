"""智能体包 — 导出公共契约（BaseAgent / Orchestrator / AgentResult / prompts / AgentDefinition / AgentRegistry / preset_data）."""

from app.services.agents.base_agent import BaseAgent, AgentResult
from app.services.agents.orchestrator import Orchestrator
from app.services.agents import prompts
from app.services.agents.agent_definition import AgentDefinition
from app.services.agents.agent_registry import AgentRegistry
from app.services.agents.preset_data import seed_preset_agents

__all__ = [
    "BaseAgent",
    "AgentResult",
    "Orchestrator",
    "prompts",
    "AgentDefinition",
    "AgentRegistry",
    "seed_preset_agents",
]
