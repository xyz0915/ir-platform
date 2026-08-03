/**
 * pipelineTypes — 工作流编排节点类型系统
 *
 * 定义：
 * - NodeType 枚举（6 种节点类型）
 * - NodeTypeMeta：每个类型的 label、SVG icon path、phase、track 索引
 * - PipelinePhase：5 个阶段的 id/label/x 坐标
 * - syncTo8px()：8px 基线对齐函数
 *
 * IR 设计规范：中性色系、无阴影、无渐变、0.5px 边框
 */

// ==========================================================================
// NodeType 枚举
// ==========================================================================

export const NodeType = {
  TRIGGER: 'trigger',
  LLM: 'llm',
  GUARD: 'guard',
  HITL: 'hitl',
  ACTION: 'action',
  OUTPUT: 'output',
  BRANCH: 'branch', // Phase 3 · 条件分支节点（手动指定结果）
  // ── 增量：7 个后端分析节点，值须与 pipeline_engine._get_node_runner 的 key 完全一致 ──
  FILE_ANALYSIS: 'file_analysis',
  PROCESS_ANALYSIS: 'process_analysis',
  NETWORK_ANALYSIS: 'network_analysis',
  REGISTRY_ANALYSIS: 'registry_analysis',
  TIMELINE: 'timeline',
  ROOT_CAUSE: 'root_cause',
  THREAT_INTEL: 'threat_intel',
  // ── 增量：11 节点真实化 6 个新节点，值须与 pipeline_engine._get_node_runner 的 key 完全一致 ──
  CONDITION: 'condition',
  PARALLEL: 'parallel',
  DATA_PROCESS: 'data-process',
  INTEL_QUERY: 'intel-query',
  MCP_TOOL: 'mcp-tool',
  INTEL_SOURCE: 'intel-source',
}

// ==========================================================================
// NodeTypeMeta — 每个类型的元信息
// ==========================================================================

/**
 * @typedef {Object} NodeTypeMetaEntry
 * @property {string}  label      — 中文显示名
 * @property {string}  icon       — Lucide SVG 路径片段（viewBox="0 0 24 24" 内）
 * @property {string}  phase      — 所属阶段 id
 * @property {string}  badgeColor — badge CSS class 后缀
 * @property {number}  track      — 所在轨道索引（0 = 上行，1 = 下行）
 */

/** @type {Object<string, NodeTypeMetaEntry>} */
export const NodeTypeMeta = {
  [NodeType.TRIGGER]: {
    label: '触发器',
    icon: '<circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/>',
    phase: 'input',
    badgeColor: 'badge-low',
    track: 0,
  },
  [NodeType.LLM]: {
    label: '大模型调用',
    icon: '<path d="M12 20h9"/><path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4L16.5 3.5z"/>',
    phase: 'analysis',
    badgeColor: 'badge-low',
    track: 0,
  },
  [NodeType.GUARD]: {
    label: '护栏',
    icon: '<rect x="3" y="11" width="18" height="11" rx="2" ry="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/>',
    phase: 'security',
    badgeColor: 'badge-critical',
    track: 1,
  },
  [NodeType.HITL]: {
    label: '人工审核',
    icon: '<path d="M9 12l2 2 4-4"/><path d="M5 18h14"/><rect x="3" y="4" width="18" height="14" rx="2"/>',
    phase: 'security',
    badgeColor: 'badge-medium',
    track: 1,
  },
  [NodeType.ACTION]: {
    label: '处置执行',
    icon: '<circle cx="12" cy="12" r="10"/><line x1="4.93" y1="4.93" x2="19.07" y2="19.07"/>',
    phase: 'remediation',
    badgeColor: 'badge-critical',
    track: 0,
  },
  [NodeType.OUTPUT]: {
    label: '报告输出',
    icon: '<path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"/><path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"/>',
    phase: 'output',
    badgeColor: 'badge-info',
    track: 0,
  },
  [NodeType.BRANCH]: {
    label: '条件分支',
    icon: '<circle cx="6" cy="6" r="3"/><circle cx="6" cy="18" r="3"/><circle cx="18" cy="12" r="3"/><path d="M6 9v6M15 12H9a3 3 0 0 1-3-3"/>',
    phase: 'security',
    badgeColor: 'badge-info',
    track: 0,
  },
  // ── 增量：7 个后端分析节点的元信息（phase:'analysis'、badge-info、track:0）──
  [NodeType.FILE_ANALYSIS]: {
    label: '文件分析',
    icon: '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><circle cx="11.5" cy="14.5" r="2.5"/><path d="m21 21-4.3-4.3"/>',
    phase: 'analysis', badgeColor: 'badge-info', track: 0,
  },
  [NodeType.PROCESS_ANALYSIS]: {
    label: '进程分析',
    icon: '<rect x="4" y="4" width="16" height="16" rx="2"/><rect x="9" y="9" width="6" height="6"/><path d="M9 1v2M15 1v2M9 21v2M15 21v2M21 9h2M21 14h2M3 9h2M3 14h2"/>',
    phase: 'analysis', badgeColor: 'badge-info', track: 0,
  },
  [NodeType.NETWORK_ANALYSIS]: {
    label: '网络分析',
    icon: '<rect x="9" y="9" width="6" height="6" rx="1"/><path d="M9 1v4M15 1v4M9 19v4M15 19v4M1 9h4M1 14h4M19 9h4M19 14h4"/>',
    phase: 'analysis', badgeColor: 'badge-info', track: 0,
  },
  [NodeType.REGISTRY_ANALYSIS]: {
    label: '注册表分析', // 语义：注册表 / 持久化分析
    icon: '<ellipse cx="12" cy="5" rx="9" ry="3"/><path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5"/><path d="M3 12c0 1.66 4 3 9 3s9-1.34 9-3"/>',
    phase: 'analysis', badgeColor: 'badge-info', track: 0,
  },
  [NodeType.TIMELINE]: {
    label: '时间线重建',
    icon: '<circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/>',
    phase: 'analysis', badgeColor: 'badge-info', track: 0,
  },
  [NodeType.ROOT_CAUSE]: {
    label: '根因定位',
    icon: '<circle cx="12" cy="12" r="10"/><line x1="22" y1="12" x2="18" y2="12"/><line x1="2" y1="12" x2="6" y2="12"/><line x1="12" y1="2" x2="12" y2="6"/><line x1="12" y1="18" x2="12" y2="22"/>',
    phase: 'analysis', badgeColor: 'badge-info', track: 0,
  },
  [NodeType.THREAT_INTEL]: {
    label: '威胁情报',
    icon: '<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/><path d="M12 8v4M12 16h.01"/>',
    phase: 'analysis', badgeColor: 'badge-info', track: 0,
  },
  // ── 增量：11 节点真实化 6 个新节点的元信息（值 = 后端 runner key）──
  [NodeType.CONDITION]: {
    label: '条件分支',
    icon: '<circle cx="6" cy="6" r="3"/><circle cx="6" cy="18" r="3"/><circle cx="18" cy="12" r="3"/><path d="M6 9v6M15 12H9a3 3 0 0 1-3-3"/>',
    phase: 'security', badgeColor: 'badge-info', track: 0,
  },
  [NodeType.PARALLEL]: {
    label: '并行分支',
    icon: '<circle cx="12" cy="12" r="10"/><line x1="8" y1="12" x2="16" y2="12"/>',
    phase: 'security', badgeColor: 'badge-info', track: 0,
  },
  [NodeType.DATA_PROCESS]: {
    label: '数据处理',
    icon: '<polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/>',
    phase: 'analysis', badgeColor: 'badge-info', track: 0,
  },
  [NodeType.INTEL_QUERY]: {
    label: '外部情报查询',
    icon: '<circle cx="12" cy="12" r="10"/><path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3"/><line x1="12" y1="17" x2="12.01" y2="17"/>',
    phase: 'analysis', badgeColor: 'badge-info', track: 0,
  },
  [NodeType.MCP_TOOL]: {
    label: 'MCP 工具',
    icon: '<path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>',
    phase: 'security', badgeColor: 'badge-info', track: 1,
  },
  [NodeType.INTEL_SOURCE]: {
    label: '情报源接入',
    icon: '<path d="M22 12h-4l-3 9L9 3l-3 9H2"/>',
    phase: 'analysis', badgeColor: 'badge-info', track: 0,
  },
}

// ==========================================================================
// PipelinePhase — 阶段定义
// ==========================================================================

/**
 * @typedef {Object} PhaseEntry
 * @property {string} id    — 阶段标识
 * @property {string} label — 显示文字
 * @property {number} x     — 阶段标签在画布中的 x 坐标
 */

/** @type {PhaseEntry[]} */
export const PipelinePhase = [
  { id: 'input', label: '阶段 1 · 输入', x: 80 },
  { id: 'analysis', label: '阶段 2 · 分析', x: 380 },
  { id: 'security', label: '阶段 3 · 安全控制', x: 680 },
  { id: 'remediation', label: '阶段 4 · 处置', x: 1040 },
  { id: 'output', label: '阶段 5 · 输出', x: 1340 },
]

/**
 * 预置模型列表（供 ConfigPanel 下拉选择）。
 */
export const AVAILABLE_MODELS = [
  'gpt-4',
  'gpt-4-turbo',
  'gpt-3.5-turbo',
  'claude-3-opus',
  'claude-3-sonnet',
  'claude-3-haiku',
  'deepseek-chat',
  'deepseek-reasoner',
  'qwen-max',
  'qwen-plus',
]

// ==========================================================================
// 辅助函数
// ==========================================================================

/**
 * 将 y 坐标对齐到最近的 8px 网格。
 * 所有节点、轨道、辅助线的 y 坐标必须经过此函数处理。
 *
 * @param {number} y — 原始 y 坐标
 * @returns {number} 对齐后的 y 坐标
 */
export function syncTo8px(y) {
  return Math.round(y / 8) * 8
}

// ==========================================================================
// 节点默认数据工厂
// ==========================================================================

let nodeIdCounter = 0

/**
 * 各节点类型的默认 input_params 骨架（写入 node.config.input_params）。
 * 后端 runner 从 agent_def.config.input_params / run 级 ctx 读取并合并；
 * 前端 config.input_params 供调试面板 / 配置面板读写（A4 存储约定）。
 */
export const NODE_DEFAULT_INPUT_PARAMS = {
  [NodeType.GUARD]: { policy: 'default', checks: [{ rule: 'default_policy', detail: '' }], block: false, reason: '' },
  [NodeType.HITL]: { action: 'export_report', target: { report_type: 'incident' }, auto_rollback_plan: {}, reason: '人工审核节点' },
  [NodeType.CONDITION]: { conditions: [{ label: '默认', expr: 'true' }], source: '' },
  [NodeType.PARALLEL]: { branches: [{ label: '分支A', target: '' }] },
  [NodeType.DATA_PROCESS]: { source: '', operations: [] },
  [NodeType.INTEL_QUERY]: { ioc_type: 'ip', ioc_value: '', provider_name: '' },
  [NodeType.ACTION]: { action: 'export_report', target: {}, operator: '', require_hitl: false },
  [NodeType.OUTPUT]: { keyword: '', category: '', limit: 5 },
  [NodeType.MCP_TOOL]: { tool_id: '', args: {} },
  [NodeType.INTEL_SOURCE]: { enabled_only: true, provider: '' },
  [NodeType.LLM]: { prompt: '', model: 'gpt-4', model_profile: '', agent_ref: '', allow_default_llm: false },
}

/** 处置动作下拉选项（guard/hitl/action 共用）。 */
export const ACTION_OPTIONS = [
  'block_ip',
  'isolate_host',
  'export_report',
  'mark_false_positive',
  'add_whitelist',
  'create_case',
  'add_note',
]

/**
 * 创建一个新的 PipelineNode 数据对象。
 *
 * @param {string} type  — NodeType 值
 * @param {{x: number, y: number}} position — 画布坐标（y 会自动 8px 对齐）
 * @param {string} [name] — 节点显示名称
 * @returns {object} PipelineNode 数据
 */
export function createNodeData(type, position, name) {
  const meta = NodeTypeMeta[type]
  if (!meta) throw new Error(`Unknown node type: ${type}`)

  nodeIdCounter += 1
  const id = `node-${nodeIdCounter}-${Date.now()}`

  return {
    id,
    type,
    typeLabel: meta.label,
    name: name || meta.label,
    position: {
      x: position.x,
      y: syncTo8px(position.y),
    },
    track: meta.track,
    badgeText: '',
    badgeType: meta.badgeColor,
    statText: '',
    hasInConnector: type !== NodeType.TRIGGER,
    hasOutConnector: type !== NodeType.OUTPUT,
    stepIndex: 0,
    selected: false,
    config: {
      name: name || meta.label,
      version: 'v1.0.0',
      model: '',
      temperature: 0.2,
      ...(type === NodeType.BRANCH ? { branches: [] } : {}),
      // 11 节点真实化：新/既有节点默认 input_params 骨架（A4 存储约定）
      ...(NODE_DEFAULT_INPUT_PARAMS[type]
        ? { input_params: JSON.parse(JSON.stringify(NODE_DEFAULT_INPUT_PARAMS[type])) }
        : {}),
    },
    dependencies: {
      upstream: [],
      downstream: [],
      dataflow: 'JSON',
    },
    tools: [],
    prompt: '',
    variables: [],
  }
}

/**
 * 将节点变量数组 [{key, value}] 展平为 context_vars 对象。
 * 用于单节点调试时把前端节点 variables 映射为后端 context_vars。
 *
 * @param {Array<{key: string, value: any}>} variables
 * @returns {Object} 展平后的 context_vars
 */
export function flattenVariables(variables) {
  const out = {}
  if (!Array.isArray(variables)) return out
  for (const v of variables) {
    if (v && v.key != null && v.key !== '') {
      out[v.key] = v.value
    }
  }
  return out
}
