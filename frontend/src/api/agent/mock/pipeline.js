/**
 * M3 流水线 DAG Mock 种子适配器。
 *
 * 暴露：getSample() —— 返回示例 PipelineDef（DAG 初始种子）。
 * 接口层（validate/run 等）走真实 agentManagement.js，仅种子用 Mock。
 *
 * 设计依据：01-api-spec.md §3 / demo mocks/pipelines.ts。
 */
import { clone, delay, ok } from './util'

/** 示例流水线定义（DAG 配置层） */
const SAMPLE_PIPELINE = {
  pipeline_id: 'pipe-incident-response',
  name: '事件响应编排（示例）',
  status: 'draft',
  requires_guardrail: true,
  requires_hitl: true,
  created_at: '2026-07-01T09:00:00.000Z',
  nodes: [
    { node_id: 'n-trigger', type: 'trigger', label: '告警触发', position: { x: 80, y: 200 } },
    { node_id: 'n-investigate', type: 'investigate', label: '初步调查', position: { x: 320, y: 200 } },
    { node_id: 'n-forensic', type: 'forensic', label: '取证实录', position: { x: 560, y: 120 } },
    { node_id: 'n-guardrail', type: 'guardrail', label: '护栏校验', position: { x: 560, y: 300 } },
    { node_id: 'n-remediate', type: 'remediate', label: '处置响应', position: { x: 800, y: 300 } },
    { node_id: 'n-end', type: 'end', label: '结束', position: { x: 1040, y: 300 } },
  ],
  edges: [
    { source: 'n-trigger', target: 'n-investigate' },
    { source: 'n-investigate', target: 'n-forensic' },
    { source: 'n-investigate', target: 'n-guardrail' },
    { source: 'n-guardrail', target: 'n-remediate' },
    { source: 'n-remediate', target: 'n-end' },
  ],
}

export async function getSample() {
  await delay()
  return ok(clone(SAMPLE_PIPELINE))
}

// ══════════════════════════════════════════
// Phase 3 · 单节点调试 Mock（离线开发，USE_MOCK.nodeDebug 默认 true）
// ══════════════════════════════════════════

/** 各节点类型的合成 fixture（结构对齐后端 node_fixtures.py §4.2）。 */
const NODE_FIXTURES = {
  file_analysis: {
    output_text: '# 文件分析报告\n检测到 3 条文件创建事件（命中规则）：\n  📄 ransom_note.txt\n     路径: C:\\Users\\victim\\Desktop\\ransom_note.txt',
    structured: {
      count: 3,
      files: [{ file_name: 'ransom_note.txt', path: 'C:\\Users\\victim\\Desktop\\ransom_note.txt', matched_rules: ['T1486_file_encryption'] }],
      summary: '在受感染主机上发现勒索信、加密配置与可疑 DLL，疑似勒索软件投放。',
    },
    confidence: 0.75,
    evidence: [{ type: 'file_events', ref: 'security_events.id=12', file_name: 'ransom_note.txt' }],
  },
  process_analysis: {
    output_text: '# 进程分析报告\n共记录 4 个进程事件。\n  powershell.exe → 3 个子进程',
    structured: {
      process_count: 4,
      tree: [{ parent: 'powershell.exe', child: 'rundll32.exe', pid: 2241 }],
      suspicious: [{ process_name: 'rundll32.exe', pid: 2241, cmd: 'rundll32.exe C:\\ProgramData\\evil\\config.bin' }],
      summary: 'powershell 拉起 rundll32/cmd/wscript，符合无文件攻击链特征。',
    },
    confidence: 0.7,
    evidence: [{ type: 'process_events', ref: 'process_events.id=881', process_name: 'rundll32.exe', pid: 2241 }],
  },
  network_analysis: {
    output_text: '# 网络连接分析报告\n共记录 5 条网络连接。\n## 威胁连接: 2 条\n  🔴 10.0.0.15:49158 → 185.220.101.32:443 (tcp)',
    structured: {
      connection_count: 5,
      threat_connections: [{ local_addr: '10.0.0.15', remote_addr: '185.220.101.32', process_name: 'rundll32.exe', threat_level: 'high' }],
      external_connections: [{ local_addr: '10.0.0.15', remote_addr: '185.220.101.32' }],
      summary: '检测到与已知 Tor 出口节点建立的高危外联，疑似 C2 通信。',
    },
    confidence: 0.75,
    evidence: [{ type: 'network_connection', ref: 'network_connections.id=551', local_addr: '10.0.0.15', remote_addr: '185.220.101.32' }],
  },
  registry_analysis: {
    output_text: '# 注册表/持久化分析报告\n检测到 2 条注册表相关安全事件。\n## 按规则分组:\n  ⚠️ persistence_run_key — 1 次命中',
    structured: {
      count: 2,
      rule_groups: [{ rule_name: 'persistence_run_key', hits: 1 }],
      summary: '在 Run 键值与计划任务中均发现可疑自启动项。',
    },
    confidence: 0.8,
    evidence: [{ type: 'registry_events', ref: 'security_events.id=31', detail: 'HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run\\Updater' }],
  },
  timeline: {
    output_text: '# 事件时间线\n共 4 个时间节点：\n  🔴 2026-07-06T09:12:01 [high] file_create',
    structured: {
      count: 4,
      events: [{ timestamp: '2026-07-06T09:12:01', event_type: 'file_create', severity: 'high', rule_name: 'T1486_file_encryption' }],
      summary: '从文件落地、进程拉起、外联到持久化的完整攻击链时间线。',
    },
    confidence: 0.7,
    evidence: [],
  },
  root_cause: {
    output_text: '## 根因分析\n第一触发点为 powershell.exe 下载并执行了加密载荷。',
    structured: {
      root_cause: 'powershell.exe 下载并执行了加密载荷',
      attack_chain: ['投递', '持久化', 'C2 外联', '加密'],
      affected_assets: ['host-abc123'],
      summary: '钓鱼文档触发 powershell 下载载荷，建立 C2 后加密文件。',
      used_llm: true,
    },
    confidence: 0.85,
    evidence: [],
  },
  threat_intel: {
    output_text: '# 威胁情报关联分析\n命中 2 条 IOC。\n## IOC 匹配结果\n  🔴 ip: 185.220.101.32',
    structured: {
      count: 2,
      iocs: [{ ioc_type: 'ip', ioc_value: '185.220.101.32', severity: 'high', source: 'tor_exit_node' }],
      summary: '外联 IP 命中 Tor 出口节点情报，域名命中 OSINT 黑名单。',
    },
    confidence: 0.8,
    evidence: [{ type: 'ioc_hits', ref: '185.220.101.32', ioc_type: 'ip' }],
  },
  branch: {
    output_text: '# 分支节点\n手动指定分支结果（本期不做表达式求值，仅手动选择）。',
    structured: { chosen_branch: null, options: [], downstream_active: [] },
    confidence: 1.0,
    evidence: [],
  },
  llm: {
    output_text: '# 自定义大模型节点\n（模拟）基于节点 prompt 与输入参数合成的结论摘要。',
    structured: { summary: '（模拟）这是自定义 LLM 节点的合成摘要输出。', prompt_used: '（模拟）未配置真实 prompt', model: '（模拟）未指定模型' },
    confidence: 0.6,
    evidence: [],
  },
  _default: {
    output_text: '# 节点模拟输出\n（模拟）该节点类型暂无专门的 fixture，返回通用合成结果。',
    structured: { summary: '（模拟）通用合成结果。' },
    confidence: 0.5,
    evidence: [],
  },
}

/** Mock 内存历史（演示用，真实后端由 agent_runs 表承载）。 */
let _debugHistory = []

function _pickFixture(nodeType) {
  return NODE_FIXTURES[nodeType] || NODE_FIXTURES._default
}

/** 单节点执行（Mock 合成，零外部 IO）。 */
export async function runNode(payload = {}) {
  await delay()
  const nodeType = payload.node_type || 'file_analysis'
  const nodeName = payload.node_name || nodeType
  const mode = payload.mode || 'real'
  const fx = _pickFixture(nodeType)
  const runId = `debug-${Math.random().toString(16).slice(2, 14)}`
  const contextVars = payload.context_vars || {}
  const inputReceived = {
    input_params: payload.input_params || {},
    context_vars: contextVars,
    resolved_host_id: contextVars.host_id || null,
  }
  const record = {
    run_id: runId,
    node_name: nodeName,
    node_type: nodeType,
    mode,
    status: 'success',
    elapsed_ms: Math.floor(20 + Math.random() * 80),
    confidence: fx.confidence,
    timestamp: new Date().toISOString(),
    input: {
      mode,
      input_params: payload.input_params || {},
      context_vars: contextVars,
      resolved_host_id: inputReceived.resolved_host_id,
    },
    output: {
      output_text: fx.output_text,
      structured: fx.structured,
      confidence: fx.confidence,
      evidence: fx.evidence,
    },
    error: null,
  }
  _debugHistory.unshift(record)
  if (_debugHistory.length > 50) _debugHistory.pop()
  return ok(clone({
    status: 'success',
    node_type: nodeType,
    node_name: nodeName,
    result: {
      input_received: inputReceived,
      output_text: fx.output_text,
      structured: fx.structured,
    },
    output_text: fx.output_text,
    elapsed_ms: record.elapsed_ms,
    error: null,
    confidence: fx.confidence,
    evidence: fx.evidence,
    input_received: inputReceived,
    mode,
    run_id: runId,
    timestamp: record.timestamp,
  }))
}

/** 分支模拟（Mock 纯图计算 BFS）。 */
export async function simulateBranch(payload = {}) {
  await delay()
  const { node_name, branches = [], chosen_branch, connections = [] } = payload
  const chosen = chosen_branch || (branches[0] && branches[0].label)
  const adj = {}
  connections.forEach((c) => {
    const s = c.sourceId || c.source
    const t = c.targetId || c.target
    if (s && t) (adj[s] = adj[s] || []).push(t)
  })
  const _bfs = (start) => {
    const seen = new Set()
    const q = start ? [start] : []
    while (q.length) {
      const cur = q.shift()
      if (seen.has(cur)) continue
      seen.add(cur)
      ;(adj[cur] || []).forEach((n) => { if (!seen.has(n)) q.push(n) })
    }
    return seen
  }
  const chosenTarget = (branches.find((b) => b.label === chosen) || {}).target
  const active = _bfs(chosenTarget)
  const prunedTargets = branches.filter((b) => b.label !== chosen).map((b) => b.target)
  let pruned = new Set()
  prunedTargets.forEach((pt) => _bfs(pt).forEach((n) => pruned.add(n)))
  pruned = new Set([...pruned].filter((n) => !active.has(n)))
  const prunedEdges = connections
    .filter((c) => pruned.has(c.sourceId || c.source))
    .map((c) => ({ sourceId: c.sourceId || c.source, targetId: c.targetId || c.target }))
  return ok(clone({
    node_name,
    chosen_branch: chosen,
    chosen_target: chosenTarget,
    active_nodes: [...active],
    pruned_nodes: [...pruned],
    pruned_edges: prunedEdges,
    downstream_active_count: active.size,
  }))
}

/** 查询单节点调试历史（Mock 内存）。 */
export async function getNodeRuns(params = {}) {
  await delay()
  let list = clone(_debugHistory)
  if (params.node_name) list = list.filter((r) => r.node_name === params.node_name)
  if (params.mode) list = list.filter((r) => r.mode === params.mode)
  const limit = params.limit || 20
  return ok(clone({ items: list.slice(0, limit), total: list.length }))
}
