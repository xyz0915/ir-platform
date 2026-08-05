/**
 * Mock / 真实 切换开关（按模块粒度）。
 *
 * 后端就绪后，将对应键改为 false，并在 src/api/agent/index.js 的 agentApi
 * 中补真实实现即可，业务组件与 store 无需任何改动。
 *
 * 设计依据：01-arch-design.md §4.2 / 01-tasks.md T1。
 */
export const USE_MOCK = {
  // ── C 档已翻 false（F8/F7 后端已建且接线就绪） ──
  guardrail: false, // M7 护栏（F8 后端已建，evaluate 载荷/whitelist 解析已修 → 真实）
  tools: false, // M4 工具/MCP（F7 后端已建，Fix A 切换真实 GET /api/mcp/tools）

  // ── B 档已启用（拆键后各自门控，07 §5.5） ──
  memory: false, // M5 记忆/RAG（F3 映射已就绪 → 真实）
  observability: false, // M8 trace/log/resume_point 已就绪 → 真实
  settings: false, // M9 仅管 listModelProfiles（F10 重定向已就绪 → 真实）
  settingsDeployment: false, // M9 管 getDeploymentConfig（后端 /api/settings/deployment 已存在且形状同构 → 真实）
  dashboardTrend: false, // M1 仅管 getTrend（指 /api/agents/dashboard 已就绪 → 真实）
  dashboardGuardrailBlocks: false, // M1 管 getGuardrailBlocks（改指 /api/agent-guardrails/hits → 真实）

  // ── 既有真实模块 ──
  pipeline: false, // M3 接口层真实（执行空壳走 M1 收敛）
  hitl: false, // M6 真实
  agents: false, // M2 真实
  runs: false, // M1/M8 运行真实

  // ── Phase 3 节点级调试（后端已就绪，置 false 接真实后端） ──
  nodeDebug: false, // 单节点 run / 分支模拟 / 历史查询均路由真实后端（@/api/agentManagement.runNode → POST /api/agent-management/pipeline/node/run）
}
