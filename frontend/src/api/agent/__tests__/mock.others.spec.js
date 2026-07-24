/**
 * M4/M5/M9/M1/M8/M3 Mock 适配器单元测试（剩余 6 个模块）。
 * 验证字段完整性与关键返回值形态，符合 01-api-spec.md 各模块实体定义。
 */
import { describe, it, expect, vi } from 'vitest'
import * as toolsMock from '../mock/tools'
import * as memoryMock from '../mock/memory'
import * as settingsMock from '../mock/settings'
import * as dashboardMock from '../mock/dashboard'
import * as observabilityMock from '../mock/observability'
import * as pipelineMock from '../mock/pipeline'

// 统一将延迟置为瞬时
vi.mock('../mock/util', async (importOriginal) => {
  const actual = await importOriginal()
  return { ...actual, delay: () => Promise.resolve() }
})

describe('M4 工具与 MCP Mock：字段完整 + 状态分布', () => {
  it('listTools 返回 ToolDef[] 且字段完整', async () => {
    const res = await toolsMock.listTools()
    expect(res.code).toBe(0)
    expect(Array.isArray(res.data)).toBe(true)
    expect(res.data.length).toBeGreaterThan(0)
    const t = res.data[0]
    ;['tool_id', 'name', 'schema', 'idempotency_key', 'timeout_ms', 'retries', 'status', 'category']
      .forEach((k) => expect(t).toHaveProperty(k))
  })

  it('listMcpServers 返回 McpServer[] 且字段完整', async () => {
    const res = await toolsMock.listMcpServers()
    expect(res.code).toBe(0)
    const s = res.data[0]
    ;['server_id', 'name', 'transport', 'status', 'tools_count', 'last_heartbeat']
      .forEach((k) => expect(s).toHaveProperty(k))
  })

  it('含多种工具状态与 MCP 状态（可用/降级/停用/在线/离线）', async () => {
    const tools = (await toolsMock.listTools()).data
    const statuses = new Set(tools.map((t) => t.status))
    expect(statuses.has('available')).toBe(true)
    expect(statuses.has('degraded')).toBe(true)
    expect(statuses.has('disabled')).toBe(true)

    const servers = (await toolsMock.listMcpServers()).data
    const sStatuses = new Set(servers.map((s) => s.status))
    expect(sStatuses.has('online')).toBe(true)
    expect(sStatuses.has('degraded')).toBe(true)
    expect(sStatuses.has('offline')).toBe(true)
  })
})

describe('M5 记忆与 RAG Mock：知识库字段 + 文档总量', () => {
  it('listKnowledgeBases 返回 KnowledgeBase[] 且字段完整', async () => {
    const res = await memoryMock.listKnowledgeBases()
    expect(res.code).toBe(0)
    const kb = res.data[0]
    ;['kb_id', 'name', 'embedding_model', 'vector_store', 'doc_count', 'updated_at']
      .forEach((k) => expect(kb).toHaveProperty(k))
  })

  it('doc_count 为数值且可累加', async () => {
    const kbs = (await memoryMock.listKnowledgeBases()).data
    const total = kbs.reduce((s, kb) => s + (Number(kb.doc_count) || 0), 0)
    expect(total).toBeGreaterThan(0)
  })
})

describe('M9 设置 Mock：模型 profile + 部署配置字段', () => {
  it('listModelProfiles 返回 ModelProfile[] 且字段完整', async () => {
    const res = await settingsMock.listModelProfiles()
    expect(res.code).toBe(0)
    const p = res.data[0]
    ;['profile_id', 'name', 'provider', 'model', 'enabled'].forEach((k) => expect(p).toHaveProperty(k))
  })

  it('getDeploymentConfig 返回 DeploymentConfig 且字段完整', async () => {
    const res = await settingsMock.getDeploymentConfig()
    expect(res.code).toBe(0)
    const d = res.data
    ;['stateless_enabled', 'redis_connected', 'sse_protocol', 'hitl_protocol']
      .forEach((k) => expect(d).toHaveProperty(k))
  })
})

describe('M1 Dashboard Mock：趋势 + 护栏拦截数', () => {
  it('getTrend 返回近 7 日成功率且数值在 [80,99]', async () => {
    const res = await dashboardMock.getTrend()
    expect(res.code).toBe(0)
    expect(res.data.length).toBe(7)
    res.data.forEach((p) => {
      expect(p).toHaveProperty('ts')
      expect(p).toHaveProperty('success_rate')
      expect(p.success_rate).toBeGreaterThanOrEqual(80)
      expect(p.success_rate).toBeLessThanOrEqual(99)
    })
  })

  it('getGuardrailBlocks 返回拦截数（命中记录中 !passed 的计数）', async () => {
    const res = await dashboardMock.getGuardrailBlocks()
    expect(res.code).toBe(0)
    expect(typeof res.data).toBe('number')
    // 种子 GUARDRAIL_HITS 含 1 条 passed:false
    expect(res.data).toBe(1)
  })
})

describe('M8 可观测性 Mock：getRun 命中/缺省', () => {
  it('getRun(已知 run_id) 返回 trace/log/resume_point', async () => {
    const res = await observabilityMock.getRun('run-002')
    expect(res.code).toBe(0)
    expect(res.data.run_id).toBe('run-002')
    expect(Array.isArray(res.data.trace)).toBe(true)
    expect(res.data.trace.length).toBeGreaterThan(0)
    expect(Array.isArray(res.data.logs)).toBe(true)
    expect(res.data.resume_point).toBeTruthy()
  })

  it('getRun(未知 run_id) 返回空 trace/resume_point=undefined', async () => {
    const res = await observabilityMock.getRun('run-unknown-xyz')
    expect(res.code).toBe(0)
    expect(res.data.run_id).toBe('run-unknown-xyz')
    expect(res.data.trace).toEqual([])
    expect(res.data.logs).toEqual([])
    expect(res.data.resume_point).toBeUndefined()
  })
})

describe('M3 流水线 DAG Mock：种子结构合法', () => {
  it('getSample 返回含 guardrail/end 节点的合法 DAG', async () => {
    const res = await pipelineMock.getSample()
    expect(res.code).toBe(0)
    const def = res.data
    expect(def.pipeline_id).toBeTruthy()
    expect(Array.isArray(def.nodes)).toBe(true)
    expect(Array.isArray(def.edges)).toBe(true)
    const types = def.nodes.map((n) => n.type)
    expect(types).toContain('guardrail')
    expect(types).toContain('end')
    // 边均为 {source,target} 且引用存在的节点
    const ids = new Set(def.nodes.map((n) => n.node_id))
    def.edges.forEach((e) => {
      expect(ids.has(e.source)).toBe(true)
      expect(ids.has(e.target)).toBe(true)
    })
  })
})
