// frontend/src/constants/design-tokens.js
// 统一 Design Tokens — 供所有时间线相关组件引用

// ── Severity ──
export const SEVERITY = {
  COLOR: {
    high: '#F56C6C',      // 红色
    medium: '#E6A23C',     // 橙色
    low: '#909399',       // 灰色
    info: '#C0C4CC',      // 浅灰
    critical: '#FF0000',  // 深红（攻击链命中）
  },
  SYMBOL_SIZE: {
    high: 16,
    medium: 12,
    low: 8,
    info: 6,
    critical: 20,
  },
  LABEL: {
    high: '高危',
    medium: '中危',
    low: '低危',
    info: '信息',
    critical: '严重',
  },
}

// ── Event Type ──
export const EVENT_TYPE = {
  COLOR: {
    process: '#409EFF',     // 蓝色
    network: '#67C23A',     // 绿色
    file: '#E6A23C',       // 橙色
    log: '#909399',         // 灰色
    persistence: '#F56C6C', // 红色
    system: '#9B59B6',      // 紫色
    other: '#95A5A6',       // 暗灰
  },
  ICON: {
    process: 'Cpu',
    network: 'Connection',
    file: 'Document',
    log: 'Notebook',
    persistence: 'Lock',
    system: 'Setting',
    other: 'QuestionFilled',
  },
  LABEL: {
    process: '进程',
    network: '网络',
    file: '文件',
    log: '日志',
    persistence: '持久化',
    system: '系统',
    other: '其他',
  },
}

// ── Kill Chain Stages ──
export const KILL_CHAIN = {
  STAGES: [
    { key: 'reconnaissance', label: '侦查', ta_id: 'TA0043' },
    { key: 'resource_development', label: '武器化', ta_id: 'TA0042' },
    { key: 'initial_access', label: '初始访问', ta_id: 'TA0001' },
    { key: 'execution', label: '执行', ta_id: 'TA0002' },
    { key: 'persistence', label: '持久化', ta_id: 'TA0003' },
    { key: 'privilege_escalation', label: '提权', ta_id: 'TA0004' },
    { key: 'defense_evasion', label: '防御规避', ta_id: 'TA0005' },
    { key: 'credential_access', label: '凭据访问', ta_id: 'TA0006' },
    { key: 'discovery', label: '发现', ta_id: 'TA0007' },
    { key: 'lateral_movement', label: '横向移动', ta_id: 'TA0008' },
    { key: 'collection', label: '采集', ta_id: 'TA0009' },
    { key: 'command_and_control', label: 'C2', ta_id: 'TA0011' },
    { key: 'exfiltration', label: '数据渗出', ta_id: 'TA0010' },
    { key: 'impact', label: '影响', ta_id: 'TA0040' },
  ],
}

// ── 泳道图使用的7个核心阶段（简化版） ──
export const KILL_CHAIN_SWIMLANE = [
  { key: 'reconnaissance', label: '侦查', color: '#909399' },
  { key: 'weaponization', label: '武器化', color: '#E6A23C' },
  { key: 'delivery', label: '投递', color: '#F56C6C' },
  { key: 'exploitation', label: '利用', color: '#FF0000' },
  { key: 'installation', label: '安装', color: '#9B59B6' },
  { key: 'c2', label: 'C2通信', color: '#409EFF' },
  { key: 'actions', label: '目标行动', color: '#67C23A' },
]

// ── Spacing ──
export const SPACING = {
  xs: '4px',
  sm: '8px',
  md: '16px',
  lg: '24px',
  xl: '32px',
}

// ── Event Status ──
export const EVENT_STATUS = {
  new: { label: '新建', color: '#909399' },
  triaging: { label: '研判中', color: '#E6A23C' },
  contained: { label: '已遏制', color: '#409EFF' },
  closed: { label: '已关闭', color: '#67C23A' },
}

// ── SLA ──
export const SLA = {
  TIMEOUT_HOURS: 24,        // 24h 未处置视为超时
  WARNING_HOURS: 12,        // 12h 预警
}
