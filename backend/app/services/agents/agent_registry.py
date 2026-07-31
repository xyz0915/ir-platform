"""Agent 注册表单例 — 管理 Agent 定义、依赖图解析、环检测、预置数据注入。"""

import logging
from typing import Optional

from app.models.agent_definition import AgentDefinitionModel
from app.services.agents.agent_definition import AgentDefinition

logger = logging.getLogger(__name__)


class AgentRegistry:
    """Agent 注册表单例 — CRUD + 依赖校验 + 环检测。"""

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def init(self) -> None:
        """初始化：注入预置数据（仅首次运行）。"""
        if self._initialized:
            logger.info("AgentRegistry already initialized, skipping seed")
            return
        from app.services.agents.preset_data import seed_preset_agents
        count = seed_preset_agents(self)
        logger.info("AgentRegistry initialized with %d preset agents", count)
        self._initialized = True

    def register(self, agent_def: AgentDefinition) -> AgentDefinition:
        """注册 Agent。校验 name 唯一性后写入 DB。

        Args:
            agent_def: Agent 定义对象。

        Returns:
            注册后的 AgentDefinition 实例。

        Raises:
            ValueError: 如果 Agent 名称已存在。
        """
        existing = AgentDefinitionModel.get(agent_def.name)
        if existing:
            raise ValueError(f"Agent '{agent_def.name}' already exists")
        data = agent_def.to_dict()
        # 确保必填字段
        data.pop('created_at', None)
        data.pop('updated_at', None)
        result = AgentDefinitionModel.create(data)
        return AgentDefinition.from_dict(result)

    def unregister(self, name: str) -> None:
        """注销 Agent。

        Args:
            name: Agent 名称。

        Raises:
            ValueError: 如果 Agent 无法删除（被其他记录引用或不存在）。
        """
        success = AgentDefinitionModel.delete(name)
        if not success:
            raise ValueError(
                f"Agent '{name}' cannot be deleted (other records may reference it)"
            )

    def update(self, name: str, updates: dict) -> AgentDefinition:
        """更新 Agent。仅更新提供的字段。

        Args:
            name: Agent 名称。
            updates: 要更新的字段字典。

        Returns:
            更新后的 AgentDefinition 实例。

        Raises:
            ValueError: 如果 Agent 不存在。
        """
        result = AgentDefinitionModel.update(name, updates)
        if not result:
            raise ValueError(f"Agent '{name}' not found")
        return AgentDefinition.from_dict(result)

    def get(self, name: str) -> Optional[AgentDefinition]:
        """按名称获取 Agent。

        Args:
            name: Agent 名称。

        Returns:
            AgentDefinition 实例，如果不存在则返回 None。
        """
        data = AgentDefinitionModel.get(name)
        return AgentDefinition.from_dict(data) if data else None

    def list_agents(self, enabled_only: bool = True) -> list[AgentDefinition]:
        """列出所有 Agent。

        Args:
            enabled_only: 是否只返回已启用的 Agent。

        Returns:
            AgentDefinition 实例列表。
        """
        rows = AgentDefinitionModel.list(enabled_only=enabled_only)
        return [AgentDefinition.from_dict(r) for r in rows]

    def get_dependency_graph(
        self, agent_names: list[str]
    ) -> dict[str, list[str]]:
        """生成依赖图（邻接表）。

        只返回 agent_names 中涉及的依赖，不展开全部。

        Args:
            agent_names: Agent 名称列表。

        Returns:
            邻接表字典: {agent_name: [dep_name, ...]}。
        """
        graph: dict[str, list[str]] = {}
        all_agents = {a.name: a for a in self.list_agents(enabled_only=True)}
        for name in agent_names:
            agent = all_agents.get(name)
            if not agent:
                continue
            # 只保留在 agent_names 范围内或已存在的依赖
            deps = [
                d for d in agent.depends_on
                if d in agent_names or d in all_agents
            ]
            graph[name] = deps
        return graph

    def detect_cycle(
        self, graph: dict[str, list[str]]
    ) -> Optional[list[str]]:
        """DFS 三色标记环检测。

        Args:
            graph: 邻接表表示的依赖图。

        Returns:
            环路径（如 ['a', 'b', 'c', 'a']），如果无环则返回 None。
        """
        WHITE, GRAY, BLACK = 0, 1, 2
        color: dict[str, int] = {node: WHITE for node in graph}
        cycle_path: list[str] = []

        def dfs(node: str) -> Optional[list[str]]:
            color[node] = GRAY
            cycle_path.append(node)
            for neighbor in graph.get(node, []):
                if neighbor not in color:
                    continue
                if color[neighbor] == GRAY:
                    # 发现环
                    cycle_start = cycle_path.index(neighbor)
                    return cycle_path[cycle_start:] + [neighbor]
                if color[neighbor] == WHITE:
                    result = dfs(neighbor)
                    if result:
                        return result
            cycle_path.pop()
            color[node] = BLACK
            return None

        for node in graph:
            if color[node] == WHITE:
                result = dfs(node)
                if result:
                    return result
        return None

    def validate_pipeline(self, agent_names: list[str]) -> list[str]:
        """验证管道配置。返回警告/错误消息列表。

        检查项:
        - 所有 Agent 都存在且启用
        - 无循环依赖
        - 依赖的 Agent 在列表中

        Args:
            agent_names: 管道中的 Agent 名称列表。

        Returns:
            警告/错误消息列表（空列表表示验证通过）。
        """
        messages: list[str] = []
        all_agents = {a.name: a for a in self.list_agents(enabled_only=False)}
        enabled_names = {a.name for a in self.list_agents(enabled_only=True)}

        for name in agent_names:
            agent = all_agents.get(name)
            if not agent:
                messages.append(f"Agent '{name}' not found")
                continue
            if not agent.enabled:
                messages.append(f"Agent '{name}' is currently disabled")

        # 检查依赖完整性
        for name in agent_names:
            agent = all_agents.get(name)
            if not agent:
                continue
            for dep in agent.depends_on:
                if dep not in agent_names:
                    messages.append(
                        f"Agent '{name}' depends on '{dep}' which is not in pipeline"
                    )

        # 环检测
        graph = self.get_dependency_graph(agent_names)
        cycle = self.detect_cycle(graph)
        if cycle:
            messages.append(
                f"Circular dependency detected: {' → '.join(cycle)}"
            )

        # P2-2: 引用未声明依赖的输出 → warning（建议声明依赖，否则同批并发可能读到半成品）
        for name in agent_names:
            agent = all_agents.get(name)
            if not agent:
                continue
            cfg = agent.config or {}
            input_params = cfg.get("input_params") or {}
            if not isinstance(input_params, dict):
                continue
            for key, val in input_params.items():
                if isinstance(val, str) and val.startswith("{dep:") and val.endswith("}"):
                    dep_name = val[len("{dep:"):-1]
                    if dep_name and dep_name not in agent.depends_on:
                        messages.append(
                            f"Agent '{name}' input_params.{key} 引用 '{dep_name}' 的输出，"
                            f"但 '{dep_name}' 未在 depends_on 声明——建议声明依赖，"
                            f"否则同批并发可能读到半成品"
                        )

        return messages
