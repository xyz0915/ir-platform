/**
 * Mock / 真实 切换开关（按模块粒度）。
 *
 * 后端就绪后，将对应键改为 false，并在 src/api/agent/index.js 的 agentApi
 * 中补真实实现即可，业务组件与 store 无需任何改动。
 *
 * 设计依据：01-arch-design.md §4.2 / 01-tasks.md T1。
 */
export const USE_MOCK = {
  guardrail: true, // M7 护栏（F8 后端未建）→ 全 Mock
  tools: true, // M4 工具/MCP（F1 后端未建）
  memory: true, // M5 记忆/RAG（F3 后端未建）
  settings: true, // M9 设置（F10/F14 后端未建）
  dashboardTrend: true, // M1 趋势/护栏拦截数无聚合端点
  observability: true, // M8 trace/log/resume_point 待 F7
  pipeline: false, // M3 接口层真实（执行空壳走 M1 收敛）
  hitl: false, // M6 真实
  agents: false, // M2 真实
  runs: false, // M1/M8 运行真实
}
