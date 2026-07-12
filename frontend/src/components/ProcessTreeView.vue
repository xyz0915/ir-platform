<template>
  <div class="ptv">
    <!-- KPI 条 -->
    <div class="ptv-kpis">
      <div class="ptv-kpi ptv-crit"><div class="ptv-num">{{ kpis.total }}</div><div class="ptv-lbl">进程总数</div></div>
      <div class="ptv-kpi ptv-high"><div class="ptv-num">{{ kpis.high }}</div><div class="ptv-lbl">高危</div></div>
      <div class="ptv-kpi ptv-chain"><div class="ptv-num">{{ kpis.chain }}</div><div class="ptv-lbl">攻击链</div></div>
      <div class="ptv-kpi ptv-crit"><div class="ptv-num">{{ kpis.c2 }}</div><div class="ptv-lbl">C2 外连</div></div>
    </div>

    <!-- 工具栏 -->
    <div class="ptv-toolbar">
      <input class="ptv-search" v-model="search" placeholder="搜索进程名 / PID / 路径" />
      <button :class="['ptv-btn', 'ptv-ghost', { active: filterMode === 'all' }]" @click="filterMode = 'all'">全部</button>
      <button :class="['ptv-btn', 'ptv-high', { active: filterMode === 'high' }]" @click="filterMode = 'high'">高危及以上</button>
      <button :class="['ptv-btn', 'ptv-chain', { active: filterMode === 'chain' }]" @click="filterMode = 'chain'">仅攻击链</button>
      <button class="ptv-btn ptv-ghost" @click="toggleAll">展开 / 收起</button>
    </div>

    <div class="ptv-body">
      <!-- 树视图 -->
      <div class="ptv-tree-wrap">
        <div class="ptv-tree">
          <ul>
            <TreeNode
              v-for="(r, index) in displayRoots"
              :key="r.pid != null ? r.pid : 'root-' + index"
              :node="r"
            />
          </ul>
        </div>
      </div>

      <!-- 详情面板 -->
      <aside class="ptv-detail">
        <template v-if="selectedNode">
          <div class="ptv-d-head">
            <span class="ptv-ic" :style="{ color: iconColor(selectedNode) }" v-html="iconSvg(iconType(selectedNode))"></span>
            <div style="flex:1; min-width:0">
              <div class="ptv-d-name">{{ selectedNode.process_name || selectedNode.name || 'unknown' }}</div>
              <div class="ptv-d-sub">PID {{ selectedNode.pid != null ? selectedNode.pid : '—' }} · {{ selectedNode.severity ? severityLabel(selectedNode.severity) : '正常' }}</div>
            </div>
            <span class="ptv-risk" :style="riskStyle(selectedNode)">风险 {{ selectedNode.risk_score != null ? selectedNode.risk_score : 0 }}</span>
          </div>

          <div class="ptv-grid">
            <div><div class="ptv-lab">进程 ID</div><div class="ptv-val">{{ selectedNode.pid != null ? selectedNode.pid : '—' }}</div></div>
            <div><div class="ptv-lab">父进程 ID</div><div class="ptv-val">{{ selectedNode.parent_pid != null ? selectedNode.parent_pid : '—' }}</div></div>
            <div><div class="ptv-lab">父进程</div><div class="ptv-val">{{ parentLabel(selectedNode) }}</div></div>
            <div><div class="ptv-lab">启动时间</div><div class="ptv-val">{{ selectedNode.start_time || '—' }}</div></div>
            <div><div class="ptv-lab">状态</div><div class="ptv-val" :style="{ color: statusColor(selectedNode.status) }">{{ selectedNode.status || '运行中' }}</div></div>
            <div><div class="ptv-lab">会话</div><div class="ptv-val">{{ selectedNode.session || '无数据' }}</div></div>
            <div style="grid-column:1 / span 2">
              <div class="ptv-lab">路径</div>
              <div class="ptv-val" style="font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:12px">{{ selectedNode.process_path || '—' }}</div>
            </div>
          </div>

          <div v-if="selectedNode.attack_chain_step != null && selectedNode.attack_chain_total != null" class="ptv-sec" style="color:#185FA5;font-size:12px">
            位于攻击链：<b>第 {{ selectedNode.attack_chain_step }} 跳 / 共 {{ selectedNode.attack_chain_total }} 跳</b>
          </div>

          <div class="ptv-sec">
            <div class="ptv-lab">命中规则</div>
            <div class="ptv-chips">
              <span v-for="(rn, i) in selectedRules" :key="i" class="ptv-chip">{{ rn }}</span>
              <span v-if="!selectedRules.length" style="font-size:11px;color:#94A3B8">无</span>
            </div>
          </div>

          <div v-if="selectedC2.length" class="ptv-sec">
            <div class="ptv-lab">外连情报</div>
            <div v-for="(c, i) in selectedC2" :key="i" class="ptv-conn">
              <span class="ptv-dot"></span>C2 外连 · {{ c.remote_address }}:{{ c.remote_port }} ({{ c.protocol || 'TCP' }})<br />
              <span style="color:#791F1F">状态: {{ c.state || '未知' }}</span>
            </div>
          </div>

          <div class="ptv-actions">
            <button class="ptv-btn ptv-ghost">标记误报</button>
            <button class="ptv-btn ptv-chain">加入时间线</button>
          </div>
        </template>
        <div v-else class="ptv-detail-empty">点击左侧节点查看详情</div>
      </aside>
    </div>

    <!-- 图例 -->
    <div class="ptv-legend">
      <span style="font-weight:500;color:#0F172A">图例</span>
      <span><span class="ptv-sw" style="background:#A32D2D"></span>严重</span>
      <span><span class="ptv-sw" style="background:#993C1D"></span>高</span>
      <span><span class="ptv-sw" style="background:#854F0B"></span>中</span>
      <span><span class="ptv-sw" style="background:#5F5E5A"></span>低 / 正常</span>
      <span><span class="ptv-sw" style="background:#185FA5"></span>攻击链节点</span>
      <span><span class="ptv-sw" style="border-radius:50%;background:#A32D2D"></span>C2 外连</span>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, watch, reactive, provide, inject, defineComponent, h } from 'vue'

const props = defineProps({
  treeData: { type: Object, default: () => ({}) },
  abnormalPids: { type: Array, default: () => [] },
})

/* ── 工具函数（纯函数，供 ProcessTreeView 与递归 TreeNode 共用） ── */

const SEVERITY_COLORS = {
  critical: '#A32D2D',
  high: '#993C1D',
  medium: '#854F0B',
  low: '#5F5E5A',
}
const SEVERITY_LABELS = { critical: '严重', high: '高', medium: '中', low: '低' }

function severityClass(sev) {
  if (!sev) return ''
  return 'sev-' + sev
}
function severityLabel(sev) {
  return SEVERITY_LABELS[sev] || '正常'
}
function severityColor(sev) {
  return SEVERITY_COLORS[sev] || '#5F5E5A'
}
function statusColor(status) {
  if (status === '疑似僵尸') return '#BA7517'
  return '#639922'
}

function iconType(node) {
  const n = (node && (node.process_name || node.name) || '').toLowerCase()
  if (/(^|[^a-z])(system|smss|csrss|wininit|services|lsass|svchost|winlogon|explorer|spoolsv|dwm|audiodg|conhost|registry|fontdrvhost|idle|init|launchd|systemd)([^a-z]|$)/.test(n)) return 'system'
  if (/\.(docx?|pdf|xlsx?|pptx?|txt|rtf)$/.test(n) || /(winword|excel|powerpnt|acrord|notepad|wordpad)/.test(n)) return 'doc'
  if (/(powershell|wscript|cscript|cmd|certutil|iexplore|terminal|bash|perl|python|java|node|sh)/.test(n)) return 'terminal'
  return 'generic'
}
const ICON_SVGS = {
  system: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="4" y="4" width="16" height="16" rx="2"/><rect x="9" y="9" width="6" height="6"/><path d="M9 1v3M15 1v3M9 20v3M15 20v3M20 9h3M20 14h3M1 9h3M1 14h3"/></svg>',
  doc: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6"/></svg>',
  terminal: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M4 17l6-6-6-6M12 19h8"/></svg>',
  generic: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="18" height="18" rx="2"/><path d="M3 9h18M9 21V9"/></svg>',
}
function iconSvg(type) {
  return ICON_SVGS[type] || ICON_SVGS.generic
}
function iconColor(node) {
  return node && node.severity ? severityColor(node.severity) : '#5F5E5A'
}

/** 判断一条网络连接是否为对外（C2）连接：remote 为非私网/非回环 IP 或域名。 */
function isExternalConn(conn) {
  if (!conn || typeof conn !== 'object') return false
  const r = conn.remote_address != null ? String(conn.remote_address).trim() : ''
  if (!r) return false
  if (/^\d{1,3}(\.\d{1,3}){3}$/.test(r)) {
    const p = r.split('.').map(Number)
    if (p[0] === 10) return false
    if (p[0] === 172 && p[1] >= 16 && p[1] <= 31) return false
    if (p[0] === 192 && p[1] === 168) return false
    if (p[0] === 127) return false
    if (p[0] === 169 && p[1] === 254) return false
    if (p[0] === 0) return false
    return true
  }
  // IPv6 或域名 → 视为外连候选
  return true
}
function nodeC2List(node) {
  const conns = (node && node.connections) || []
  if (!Array.isArray(conns)) return []
  return conns.filter(isExternalConn)
}
function matchedRuleNames(node) {
  const mr = (node && node.matched_rules) || []
  if (!Array.isArray(mr)) return []
  // 展示优先取中文 label，缺 label 时降级为 name（历史数据仅有 name 不报错/不空白）
  return mr
    .map((r) => (typeof r === 'string' ? r : (r && (r.label || r.name) ? (r.label || r.name) : '')))
    .filter(Boolean)
}
function parentLabel(node) {
  const ppid = node && node.parent_pid
  if (ppid == null || ppid === 0) return '— (内核)'
  if (node.parent_name) return `${node.parent_name} (${ppid})`
  return `未知 (PID ${ppid} 不在列表)`
}
function isSpoof(node) {
  return matchedRuleNames(node).some((n) => /spoof/i.test(n))
}
function isSuspect(node) {
  return matchedRuleNames(node).some((n) => /zombie/i.test(n))
}
function pidText(node) {
  return node && node.pid != null ? 'PID ' + node.pid : 'PID —'
}
function riskStyle(node) {
  const c = severityColor(node && node.severity) || '#5F5E5A'
  return { border: `1px solid ${c}`, background: '#fff', color: c }
}

/* ── 递归树节点组件（render function，便于在单文件内自包含递归） ── */

const TreeNode = defineComponent({
  name: 'ProcessTreeNode',
  props: {
    node: { type: Object, required: true },
    depth: { type: Number, default: 0 },
  },
  setup(props) {
    const ctx = inject('treeCtx')

    return () => {
      if (!ctx || !ctx.isVisible(props.node.pid)) return null

      const node = props.node
      const hasChildren = node.children && node.children.length > 0
      const expanded = ctx.getExpanded(node.pid)

      const nodeClass = ['node']
      const sc = severityClass(node.severity)
      if (sc) nodeClass.push(sc)
      if (ctx.isSelected(node.pid)) nodeClass.push('selected')

      // 标题行：进程名 / PID / 徽标
      const row = []
      row.push(h('span', { class: 'nm' }, node.process_name || node.name || 'unknown'))
      row.push(h('span', { class: 'pid' }, pidText(node)))
      if (node.severity) {
        row.push(h('span', { class: `badge b-sev-${node.severity}` }, severityLabel(node.severity)))
      }
      if (node.attack_chain_step != null && node.attack_chain_total != null) {
        row.push(h('span', { class: 'badge b-chain' }, `链 ${node.attack_chain_step}/${node.attack_chain_total}`))
      }
      const c2 = nodeC2List(node)
      if (c2.length) {
        const c = c2[0]
        row.push(h('span', { class: 'badge b-c2' }, `C2 ↗ ${c.remote_address}:${c.remote_port}`))
      }
      if (isSpoof(node)) row.push(h('span', { class: 'badge b-spoof' }, '伪装'))
      if (isSuspect(node)) row.push(h('span', { class: 'badge b-suspect' }, '疑似'))

      // 元信息行：父进程 / 启动时间 / 状态 / 命中规则
      const meta = []
      meta.push(h('span', {}, `父: ${parentLabel(node)}`))
      meta.push(h('span', {}, `启动 ${node.start_time || '—'}`))
      meta.push(h('span', { style: { color: statusColor(node.status) } }, node.status || '运行中'))
      const names = matchedRuleNames(node)
      if (names.length) {
        const col = severityColor(node.severity) || '#993C1D'
        meta.push(h('span', { style: { color: col } }, `命中: ${names.join(', ')}`))
      }

      // 节点主体
      const headEls = []
      if (hasChildren) {
        headEls.push(
          h('button', {
            class: 'toggle',
            onClick: (e) => { e.stopPropagation(); ctx.toggleNode(node.pid) },
          }, expanded ? '−' : '+')
        )
      }
      headEls.push(
        h('span', { class: 'ic', style: { color: iconColor(node) }, innerHTML: iconSvg(iconType(node)) })
      )
      headEls.push(
        h('div', { style: { flex: '1', minWidth: '0' } }, [
          h('div', { class: 'node-row' }, row),
          h('div', { class: 'meta' }, meta),
        ])
      )

      const nodeDiv = h('div', {
        class: nodeClass,
        onClick: () => ctx.selectNode(node),
      }, headEls)

      const liChildren = [nodeDiv]
      if (hasChildren && expanded) {
        liChildren.push(
          h('ul', {}, node.children.map((c) => h(TreeNode, { node: c, depth: props.depth + 1, key: c.pid != null ? c.pid : `c-${props.depth}-${Math.random()}` })))
        )
      }

      return h('li', {}, liChildren)
    }
  },
})

/* ── 顶层状态 ── */

const search = ref('')
const filterMode = ref('all') // 'all' | 'high' | 'chain'
const selectedNode = ref(null)
const selectedPid = ref(null)
const globalExpanded = ref(true)
const override = reactive({}) // pid -> 强制 collapsed 状态（布尔）

const displayRoots = computed(() => {
  const t = props.treeData
  if (!t || typeof t !== 'object') return []
  if (t.pid == null && t.name === 'All Processes' && Array.isArray(t.children) && t.children.length) {
    return t.children
  }
  return [t]
})

const kpis = computed(() => {
  let total = 0
  let high = 0
  let chain = 0
  const c2set = new Set()
  const walk = (n) => {
    if (!n || typeof n !== 'object') return
    if (n.pid != null) total += 1
    if (n.severity === 'critical' || n.severity === 'high') high += 1
    if (n.attack_chain_total != null) chain += 1
    const conns = n.connections || []
    if (Array.isArray(conns)) {
      conns.forEach((c) => {
        if (isExternalConn(c)) c2set.add(`${c.remote_address}:${c.remote_port}`)
      })
    }
    ;(n.children || []).forEach(walk)
  }
  walk(props.treeData)
  return { total, high, chain, c2: c2set.size }
})

const selectedC2 = computed(() => (selectedNode.value ? nodeC2List(selectedNode.value) : []))
const selectedRules = computed(() => (selectedNode.value ? matchedRuleNames(selectedNode.value) : []))

/* ── 可见性过滤 ── */

const visibleMap = ref({})
function recomputeVisible() {
  const map = {}
  const q = (search.value || '').trim().toLowerCase()
  const walk = (n) => {
    if (!n || typeof n !== 'object') return false
    let self = true
    if (q) {
      const hay = `${n.process_name || ''} ${n.pid != null ? n.pid : ''} ${n.process_path || ''}`.toLowerCase()
      self = hay.includes(q)
    }
    if (filterMode.value === 'high') self = self && (n.severity === 'critical' || n.severity === 'high')
    else if (filterMode.value === 'chain') self = self && (n.attack_chain_total != null)
    let childAny = false
    ;(n.children || []).forEach((c) => { if (walk(c)) childAny = true })
    const vis = self || childAny
    if (n.pid != null) map[n.pid] = vis
    return vis
  }
  walk(props.treeData)
  visibleMap.value = map
}
watch([search, filterMode, () => props.treeData], recomputeVisible, { immediate: true })
function isVisible(pid) {
  if (pid == null) return true
  return visibleMap.value[pid] !== false
}

/* ── 展开 / 收起 ── */

function getExpanded(pid) {
  const ov = override[pid]
  if (ov !== undefined) return !ov
  return globalExpanded.value
}
function toggleNode(pid) {
  const cur = getExpanded(pid)
  override[pid] = cur // 记录当前展开态为强制 collapsed 值 → 触发翻转
}
function toggleAll() {
  globalExpanded.value = !globalExpanded.value
  Object.keys(override).forEach((k) => delete override[k])
}

/* ── 选中 ── */

function selectNode(node) {
  selectedNode.value = node
  selectedPid.value = node && node.pid != null ? node.pid : null
}
function isSelected(pid) {
  return selectedPid.value != null && pid != null && selectedPid.value === pid
}

provide('treeCtx', {
  getExpanded,
  toggleNode,
  toggleAll,
  selectNode,
  isSelected,
  isVisible,
})
</script>

<!-- 注意：本组件使用全局（非 scoped）样式，并以 .ptv 前缀命名空间隔离，
     以确保 render function 生成的递归节点也能正确命中样式。 -->
<style>
.ptv { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, "PingFang SC", "Microsoft YaHei", sans-serif; font-size: 13px; line-height: 1.6; color: #0F172A; }

.ptv-kpis { display: flex; gap: 8px; }
.ptv-kpi { border-radius: 8px; padding: 6px 12px; text-align: center; min-width: 64px; }
.ptv-kpi .ptv-num { font-size: 15px; font-weight: 500; }
.ptv-kpi .ptv-lbl { font-size: 11px; }
.ptv-crit { background: #FCEBEB; border: 1px solid #F7C1C1; }
.ptv-crit .ptv-num { color: #A32D2D; } .ptv-crit .ptv-lbl { color: #791F1F; }
.ptv-high { background: #FAECE7; border: 1px solid #F5C4B3; }
.ptv-high .ptv-num { color: #993C1D; } .ptv-high .ptv-lbl { color: #712B13; }
.ptv-chain { background: #E6F1FB; border: 1px solid #B5D4F4; }
.ptv-chain .ptv-num { color: #185FA5; } .ptv-chain .ptv-lbl { color: #0C447C; }

.ptv-toolbar { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; padding: 10px 0 12px; border-bottom: 1px solid #E2E8F0; margin: 12px 0; }
.ptv-search { flex: 1; min-width: 180px; border: 1px solid #CBD5E1; border-radius: 8px; padding: 7px 10px; font-size: 13px; color: #0F172A; background: #fff; }
.ptv-btn { border-radius: 8px; padding: 7px 12px; font-size: 12px; cursor: pointer; white-space: nowrap; background: #fff; }
.ptv-btn.ptv-ghost { border: 1px solid #CBD5E1; color: #0F172A; }
.ptv-btn.ptv-high { border: 1px solid #993C1D; background: #FAECE7; color: #993C1D; }
.ptv-btn.ptv-chain { border: 1px solid #185FA5; background: #E6F1FB; color: #185FA5; }
.ptv-btn.active { outline: 2px solid #185FA5; outline-offset: -2px; }

.ptv-body { display: flex; gap: 16px; align-items: flex-start; }
.ptv-tree-wrap { flex: 1; min-width: 0; background: #fff; border: 1px solid #E2E8F0; border-radius: 12px; padding: 12px; }

.ptv-tree ul { list-style: none; margin: 0; padding: 0; position: relative; }
.ptv-tree > ul > li { padding-left: 0; }
.ptv-tree ul ul { margin-left: 13px; padding-left: 18px; }
.ptv-tree ul ul::before { content: ""; position: absolute; left: 0; top: 0; bottom: 24px; border-left: 1.5px solid #CBD5E1; }
.ptv-tree li { position: relative; list-style: none; }
.ptv-tree li::after { content: ""; position: absolute; top: 24px; left: -18px; width: 18px; border-top: 1.5px solid #CBD5E1; }
.ptv-tree > ul > li::after { display: none; }

.ptv-tree .node { display: flex; align-items: flex-start; gap: 8px; background: #fff; border: 1px solid #E2E8F0; border-left: 4px solid #5F5E5A; border-radius: 8px; padding: 9px 10px; margin: 4px 0; cursor: pointer; transition: background .12s; }
.ptv-tree .node:hover { background: #F8FAFC; }
.ptv-tree .node.sev-critical { border-color: #F7C1C1; border-left-color: #A32D2D; }
.ptv-tree .node.sev-high { border-color: #F5C4B3; border-left-color: #993C1D; }
.ptv-tree .node.sev-medium { border-color: #FAC775; border-left-color: #854F0B; }
.ptv-tree .node.sev-low { border-left-color: #5F5E5A; }
.ptv-tree .node.selected { background: #E6F1FB; border: 2px solid #185FA5; }
.ptv-tree .toggle { cursor: pointer; border: 1px solid #CBD5E1; background: #F8FAFC; border-radius: 4px; width: 18px; height: 18px; font-size: 12px; line-height: 1; color: #475569; display: inline-flex; align-items: center; justify-content: center; flex: none; margin-top: 2px; }
.ptv-tree .ic { width: 18px; display: inline-block; margin-top: 2px; flex: none; }
.ptv-tree .nm { font-size: 13px; font-weight: 500; }
.ptv-tree .pid { font-size: 11px; color: #64748B; }
.ptv-tree .node-row { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.ptv-tree .meta { display: flex; gap: 12px; flex-wrap: wrap; font-size: 12px; color: #64748B; margin-top: 3px; }
.ptv-tree .badge { font-size: 11px; border-radius: 999px; padding: 1px 7px; white-space: nowrap; }
.ptv-tree .b-sev-critical { border: 1px solid #A32D2D; background: #FCEBEB; color: #A32D2D; }
.ptv-tree .b-sev-high { border: 1px solid #993C1D; background: #FAECE7; color: #993C1D; }
.ptv-tree .b-sev-medium { border: 1px solid #854F0B; background: #FAEEDA; color: #854F0B; }
.ptv-tree .b-sev-low { border: 1px solid #5F5E5A; background: #F1EFE8; color: #444441; }
.ptv-tree .b-chain { border: 1px solid #185FA5; background: #E6F1FB; color: #185FA5; }
.ptv-tree .b-c2 { border: 1px solid #A32D2D; background: #FCEBEB; color: #A32D2D; }
.ptv-tree .b-spoof { border: 1px solid #A32D2D; background: #FCEBEB; color: #A32D2D; }
.ptv-tree .b-suspect { border: 1px solid #BA7517; background: #FAEEDA; color: #854F0B; }

.ptv-detail { width: 320px; flex: none; background: #fff; border: 1px solid #E2E8F0; border-radius: 12px; padding: 14px; }
.ptv-detail-empty { color: #94A3B8; font-size: 13px; padding: 20px 0; text-align: center; }
.ptv-d-head { display: flex; align-items: center; gap: 8px; padding-bottom: 10px; border-bottom: 1px solid #E2E8F0; }
.ptv-ic { width: 18px; display: inline-block; flex: none; }
.ptv-d-name { font-size: 14px; font-weight: 500; }
.ptv-d-sub { font-size: 11px; color: #64748B; }
.ptv-risk { font-size: 12px; border-radius: 999px; padding: 3px 10px; margin-left: auto; }
.ptv-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 8px 10px; padding: 12px 0; border-bottom: 1px solid #E2E8F0; }
.ptv-lab { font-size: 11px; color: #94A3B8; }
.ptv-val { font-size: 13px; }
.ptv-sec { padding: 10px 0; border-bottom: 1px solid #E2E8F0; }
.ptv-chips { display: flex; gap: 6px; flex-wrap: wrap; }
.ptv-chip { font-size: 11px; border: 1px solid #993C1D; background: #FAECE7; color: #993C1D; border-radius: 999px; padding: 2px 8px; }
.ptv-conn { border: 1px solid #F7C1C1; background: #FCEBEB; border-radius: 8px; padding: 8px; font-size: 12px; color: #A32D2D; margin-bottom: 6px; }
.ptv-dot { display: inline-block; width: 8px; height: 8px; border-radius: 50%; background: #A32D2D; margin-right: 6px; }
.ptv-actions { display: flex; gap: 8px; padding-top: 10px; }
.ptv-actions .ptv-btn { flex: 1; }

.ptv-legend { display: flex; gap: 16px; flex-wrap: wrap; align-items: center; padding: 14px 2px 4px; font-size: 12px; color: #64748B; }
.ptv-legend .ptv-sw { width: 10px; height: 10px; display: inline-block; margin-right: 5px; vertical-align: middle; }

@media (max-width: 880px) {
  .ptv-body { flex-direction: column; }
  .ptv-detail { width: 100%; border-left: none; border-top: 1px solid #E2E8F0; }
  .ptv-tree-wrap { overflow-x: auto; }
}
</style>
