/**
 * 智能体运行时已知类型常量（P2 前端预检）。
 *
 * ⚠️ 必须与后端 `backend/app/services/agents/execution_mode.py` 的
 * `ALL_KNOWN_TYPES` 保持一致（共享知识 #4）。修改任一端时同步另一端。
 *
 * - KNOWN_RUNNER_TYPES：与后端 PipelineEngine._get_node_runner 的 key 对齐
 *   （7 个应急响应节点 + branch + llm + trigger + guardrail）。
 * - BUILTIN_AGENT_NAMES：内置 Agent 类（triage / responder / reporter）。
 * - ALL_KNOWN_TYPES：全部已知类型。name ∈ 该集合 → 走内置真实逻辑，
 *   保存/编辑时不提示「摘要/自定义执行模式」warning。
 */

/** 已知运行类型（runner key）。 */
export const KNOWN_RUNNER_TYPES = [
  'file_analysis',
  'process_analysis',
  'network_analysis',
  'registry_analysis',
  'timeline',
  'root_cause',
  'threat_intel',
  'branch',
  'llm',
  'trigger',
  'guardrail',
]

/** 内置 Agent 类名称。 */
export const BUILTIN_AGENT_NAMES = ['triage', 'responder', 'reporter']

/** 全部已知类型（P2 判定）。 */
export const ALL_KNOWN_TYPES = [...KNOWN_RUNNER_TYPES, ...BUILTIN_AGENT_NAMES]

/** 由已知类型集合构建的 Set（O(1) 判成员）。 */
export const ALL_KNOWN_TYPES_SET = new Set(ALL_KNOWN_TYPES)
