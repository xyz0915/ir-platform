/**
 * agentApi —— 智能体编排「统一适配层 / Facade」。
 *
 * 职责（01-arch-design.md §4 / 01-tasks.md T1）：
 *   - 所有 Pinia store 只调用本层，不直接调用现有 *.js 接口，也不直接调用 mock/*。
 *   - 真实模块（M2/M3 接口层/M6/M1 runs+stats）转发现有真实 API。
 *   - Mock 模块（M7/M4/M5/M9/M1 trend/M8 trace）调用 mock/*。
 *   - 所有返回与后端同构信封 { code, data, message }（后端经 axios 拦截器已解包）。
 *
 * 切换机制：USE_MOCK（mock-config.js）按模块粒度路由；后端就绪后将对应键置 false，
 * 并把下面的真实适配器（./real）接入，业务组件与 store 零改动。
 *   - 真实适配器 ./real/* 已按文档化端点实现，默认 USE_MOCK=true 时不会被走到；
 *     置 false 即自动切换为真实后端，调用方零改动（本文件 §切换生效）。
 */
import { USE_MOCK } from './mock-config'

// ── 真实接口（现有 *.js） ──
import {
  listAgents,
  createAgent,
  updateAgent,
  deleteAgent,
  validatePipeline,
  runPipeline,
  getRunStatus,
  cancelRun,
  resumeRun,
  getPipelineSSEUrl,
  listPresets,
  createPreset,
  deletePreset,
} from '@/api/agentManagement'
import {
  createAgentRun,
  listAgentRuns,
  getAgentRun,
  approveAgentRun,
  rejectAgentRun,
  listPendingApprovals,
} from '@/api/agentOrchestration'
import { getAgents, getAgentStats } from '@/api/agents'

// ── Mock 适配器 ──
import * as guardrailMock from './mock/guardrail'
import * as toolsMock from './mock/tools'
import * as memoryMock from './mock/memory'
import * as settingsMock from './mock/settings'
import * as dashboardMock from './mock/dashboard'
import * as observabilityMock from './mock/observability'
import * as pipelineMock from './mock/pipeline'

// ── 真实适配器（后端就绪后 USE_MOCK 置 false 即启用，详见 ./real） ──
import * as guardrailReal from './real/guardrail'
import * as toolsReal from './real/tools'
import * as memoryReal from './real/memory'
import * as settingsReal from './real/settings'
import * as dashboardReal from './real/dashboard'
import * as observabilityReal from './real/observability'

/**
 * 统一出口。真实方法直接转发真实 API；Mock 方法调用对应 mock 模块。
 * 每个 Mock 模块均受 USE_MOCK[module] 门控：false 时改走真实适配器。
 * @type {Record<string, any>}
 */
const agentApi = {
  // ── M2 智能体管理（真实） ──
  listAgents: (enabledOnly = false) => listAgents(enabledOnly),
  createAgent: (data) => createAgent(data),
  updateAgent: (name, data) => updateAgent(name, data),
  deleteAgent: (name) => deleteAgent(name),

  // ── M3 流水线 DAG（真实接口层 + Mock 种子） ──
  pipeline: {
    validate: (agents) => validatePipeline(agents),
    run: (eventId, agents, useCache = true) => runPipeline(eventId, agents, useCache),
    getRunStatus: (runId) => getRunStatus(runId),
    cancel: (runId) => cancelRun(runId),
    resume: (runId, approved, comment = '') => resumeRun(runId, approved, comment),
    getSSEUrl: (runId) => getPipelineSSEUrl(runId),
    getPresets: () => listPresets(),
    createPreset: (name, description, agents) => createPreset(name, description, agents),
    deletePreset: (presetId) => deletePreset(presetId),
    // 种子 DAG：当前走 Mock（后端 presets 就绪后切真实）
    getSample: () => pipelineMock.getSample(),
  },

  // ── M8 运行（真实） ──
  runs: {
    listAgentRuns: (params = {}) => listAgentRuns(params),
    getAgentRun: (runId) => getAgentRun(runId),
    createAgentRun: (payload = {}) => createAgentRun(payload),
  },

  // ── M1 运行统计（真实） ──
  stats: {
    getAgentStats: () => getAgentStats(),
  },

  // ── 设置页智能体列表（真实，带分页，区别于 M2 的 listAgents(enabledOnly)） ──
  agents: {
    list: (params = {}) => getAgents(params),
  },

  // ── M6 人工审核台（真实） ──
  hitl: {
    listPendingApprovals: (status = 'pending') => listPendingApprovals(status),
    approve: (runId, payload) => approveAgentRun(runId, payload),
    reject: (runId, payload) => rejectAgentRun(runId, payload),
  },

  // ── M7 护栏与安全（USE_MOCK 门控：false → 真实适配器） ──
  guardrail: {
    listPolicies: () => (USE_MOCK.guardrail ? guardrailMock.listPolicies() : guardrailReal.listPolicies()),
    createPolicy: (p) => (USE_MOCK.guardrail ? guardrailMock.createPolicy(p) : guardrailReal.createPolicy(p)),
    updatePolicy: (p) => (USE_MOCK.guardrail ? guardrailMock.updatePolicy(p) : guardrailReal.updatePolicy(p)),
    deletePolicy: (id) => (USE_MOCK.guardrail ? guardrailMock.deletePolicy(id) : guardrailReal.deletePolicy(id)),
    evaluate: (action, ctx) => (USE_MOCK.guardrail ? guardrailMock.evaluate(action, ctx) : guardrailReal.evaluate(action, ctx)),
    listHits: () => (USE_MOCK.guardrail ? guardrailMock.listHits() : guardrailReal.listHits()),
  },

  // ── M4 工具与 MCP（USE_MOCK 门控） ──
  tools: {
    listTools: () => (USE_MOCK.tools ? toolsMock.listTools() : toolsReal.listTools()),
    listMcpServers: () => (USE_MOCK.tools ? toolsMock.listMcpServers() : toolsReal.listMcpServers()),
  },

  // ── M5 记忆与 RAG（USE_MOCK 门控） ──
  memory: {
    listKnowledgeBases: () =>
      (USE_MOCK.memory ? memoryMock.listKnowledgeBases() : memoryReal.listKnowledgeBases()),
  },

  // ── M9 设置（USE_MOCK 门控） ──
  settings: {
    listModelProfiles: () =>
      (USE_MOCK.settings ? settingsMock.listModelProfiles() : settingsReal.listModelProfiles()),
    getDeploymentConfig: () =>
      (USE_MOCK.settings ? settingsMock.getDeploymentConfig() : settingsReal.getDeploymentConfig()),
  },

  // ── M1 Dashboard（真实 runs/stats + Mock trend/guardrailBlocks；趋势受门控） ──
  dashboard: {
    getTrend: () => (USE_MOCK.dashboardTrend ? dashboardMock.getTrend() : dashboardReal.getTrend()),
    getGuardrailBlocks: () =>
      (USE_MOCK.dashboardTrend ? dashboardMock.getGuardrailBlocks() : dashboardReal.getGuardrailBlocks()),
  },

  // ── M8 可观测性（USE_MOCK 门控：false → 真实 trace/log） ──
  observability: {
    getRun: (runId) => (USE_MOCK.observability ? observabilityMock.getRun(runId) : observabilityReal.getRun(runId)),
  },
}

/**
 * 护栏计算热插拔入口（01-arch-design.md Q2）。
 * HITL 上下文面板调用 useGuardrail().evaluate(action, ctx) 计算 GuardrailResult；
 * 当前为 Mock，后端 F8 就绪后将 USE_MOCK.guardrail 置 false 即切换为真实评估服务，调用方零改动。
 */
export function useGuardrail() {
  return agentApi.guardrail
}

export default agentApi
