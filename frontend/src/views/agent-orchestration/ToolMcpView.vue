<template>
  <div class="tool-mcp-view">
    <!-- 顶部工具栏：状态筛选 + 搜索 + 刷新（页面标题由 AgentOrchestrationLayout 提供） -->
    <div class="tm-toolbar">
      <el-radio-group v-model="statusFilter" size="small">
        <el-radio-button value="all">全部</el-radio-button>
        <el-radio-button value="online">在线</el-radio-button>
        <el-radio-button value="offline">离线</el-radio-button>
      </el-radio-group>
      <div class="tm-search">
        <el-icon class="tm-search-icon"><Search /></el-icon>
        <input
          v-model="searchQuery"
          class="tm-search-input"
          type="text"
          placeholder="搜索服务器 / 工具名称或 ID"
        />
      </div>
      <el-button class="tm-refresh" @click="store.refreshAll" :loading="store.loading">刷新</el-button>
    </div>

    <!-- MCP 服务器状态 -->
    <h3 class="tm-section">MCP 服务器 ({{ filteredMcpServers.length }})</h3>
    <div class="tm-mcp-grid">
      <div v-for="srv in filteredMcpServers" :key="srv.server_id" class="tm-mcp-card">
        <div class="tm-mcp-head">
          <div class="tm-mcp-name">
            <span class="tm-mcp-title" :title="srv.name">{{ srv.name }}</span>
            <span class="tm-mcp-id gv-mono">{{ srv.server_id }}</span>
          </div>
          <span
            class="tm-dot"
            :class="'dot-' + statusClass(srv.status)"
            :title="store.mcpStatusLabel(srv.status)"
          />
        </div>
        <div class="tm-mcp-meta gv-mono">
          <span>传输 {{ srv.transport }}</span>
          <span class="tm-sep">·</span>
          <span>工具 {{ srv.tools_count }}</span>
          <span class="tm-sep">·</span>
          <span>心跳 {{ relativeTime(srv.last_heartbeat) }}</span>
        </div>
      </div>
    </div>

    <!-- 工具清单（按分类分组） -->
    <h3 class="tm-section tm-mt">工具清单 ({{ filteredToolCount }})</h3>
    <div v-for="[category, list] in filteredToolsByCategory" :key="category" class="tm-cat">
      <div class="tm-cat-name">{{ category }} <span class="tm-cat-count">{{ list.length }}</span></div>
      <div class="tm-tool-grid">
        <ToolSchemaCard v-for="tool in list" :key="tool.tool_id" :tool="tool" />
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { Search } from '@element-plus/icons-vue'
import { useToolsStore } from '@/stores/tools'
import ToolSchemaCard from '@/components/agents/ToolSchemaCard.vue'
import { parseServerTime } from '@/utils/time'

const store = useToolsStore()

const statusFilter = ref('all') // all / online / offline
const searchQuery = ref('')

/** 状态点仅两色：在线（单绿 #16a34a）/ 离线（灰 #9ca3af），degraded 并入灰 */
function statusClass(status) {
  return status === 'online' ? 'ok' : 'off'
}

/** 状态筛选：online 视为 status === onlineStatus，其余（含 degraded/disabled）归离线 */
function matchStatus(status, onlineStatus) {
  if (statusFilter.value === 'online') return status === onlineStatus
  if (statusFilter.value === 'offline') return status !== onlineStatus
  return true
}

/** 搜索匹配：server name / tool name / tool_id 任一命中即保留 */
function matchSearch(...fields) {
  const q = searchQuery.value.trim().toLowerCase()
  if (!q) return true
  return fields.some((f) => String(f || '').toLowerCase().includes(q))
}

const filteredMcpServers = computed(() =>
  store.mcpServers.filter(
    (s) => matchStatus(s.status, 'online') && matchSearch(s.name, s.server_id),
  ),
)

const filteredToolsByCategory = computed(() => {
  const map = new Map()
  store.tools.forEach((t) => {
    if (!matchStatus(t.status, 'available')) return
    if (!matchSearch(t.name, t.tool_id)) return
    const key = t.category || '其他'
    if (!map.has(key)) map.set(key, [])
    map.get(key).push(t)
  })
  return Array.from(map.entries())
})

const filteredToolCount = computed(() =>
  filteredToolsByCategory.value.reduce((sum, [, list]) => sum + list.length, 0),
)

/** 心跳相对时间：刚刚 / X 分钟前 / X 小时前 / X 天前 */
function relativeTime(iso) {
  if (!iso) return '—'
  const t = parseServerTime(iso)
  if (!t) return iso
  const diffMs = Date.now() - t.getTime()
  const sec = Math.floor(diffMs / 1000)
  if (sec < 60) return '刚刚'
  const min = Math.floor(sec / 60)
  if (min < 60) return `${min} 分钟前`
  const hr = Math.floor(min / 60)
  if (hr < 24) return `${hr} 小时前`
  const day = Math.floor(hr / 24)
  return `${day} 天前`
}

onMounted(store.refreshAll)
</script>

<style scoped>
.tool-mcp-view { padding: 16px; }

/* ===== 顶部工具栏 ===== */
.tm-toolbar { display: flex; align-items: center; gap: 12px; margin-bottom: 12px; }
.tm-toolbar :deep(.el-radio-button__inner) {
  font-size: 12px;
  color: var(--color-fg-muted);
  background: var(--color-canvas-default);
  border-color: var(--color-border-default);
  padding: 6px 12px;
  box-shadow: none;
}
.tm-toolbar :deep(.el-radio-button__inner:hover) { color: #111827; }
.tm-toolbar :deep(.el-radio-button__original-radio:checked + .el-radio-button__inner) {
  background: #111827;
  border-color: #111827;
  color: #fff;
  box-shadow: none;
}
.tm-toolbar :deep(.el-radio-button:first-child .el-radio-button__inner) { border-radius: 8px 0 0 8px; }
.tm-toolbar :deep(.el-radio-button:last-child .el-radio-button__inner) { border-radius: 0 8px 8px 0; }

.tm-search {
  flex: 1;
  max-width: 360px;
  height: 30px;
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 0 10px;
  border: 1px solid var(--color-border-default);
  border-radius: 8px;
  background: var(--color-canvas-default);
  transition: border-color 0.15s;
}
.tm-search:focus-within { border-color: #9ca3af; }
.tm-search-icon { font-size: 14px; color: #9ca3af; }
.tm-search-input {
  flex: 1;
  min-width: 0;
  border: none;
  outline: none;
  background: transparent;
  font-size: 12px;
  color: var(--color-fg-default);
}
.tm-search-input::placeholder { color: #9ca3af; }
.tm-refresh { margin-left: auto; }

/* ===== 分区标题 ===== */
.tm-section { font-size: 13px; font-weight: 600; color: var(--color-fg-default); margin: 0 0 10px; }
.tm-mt { margin-top: 22px; }

/* ===== MCP 服务器卡片 ===== */
.tm-mcp-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(250px, 1fr)); gap: 12px; margin-bottom: 8px; }
.tm-mcp-card {
  background: var(--color-canvas-default);
  border: 0.5px solid var(--color-border-default);
  border-radius: 10px;
  padding: 12px 14px;
  display: flex;
  flex-direction: column;
  gap: 8px;
  transition: box-shadow 0.15s, border-color 0.15s;
}
.tm-mcp-card:hover {
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.05);
  border-color: #d1d5db;
}
.tm-mcp-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 8px; }
.tm-mcp-name { display: flex; flex-direction: column; gap: 2px; min-width: 0; }
.tm-mcp-title {
  font-size: 13px; font-weight: 600; color: var(--color-fg-default);
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
.tm-mcp-id { font-size: 11px; color: var(--color-fg-subtle); }
.tm-dot { width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; margin-top: 4px; }
.dot-ok { background: #16a34a; }
.dot-off { background: #9ca3af; }
.tm-mcp-meta {
  display: flex; align-items: center; gap: 6px;
  font-size: 11px; color: var(--color-fg-subtle);
  white-space: nowrap; overflow: hidden;
}
.tm-sep { color: var(--color-fg-light); }

/* ===== 工具分组 ===== */
.tm-cat { margin-bottom: 16px; }
.tm-cat-name { font-size: 13px; font-weight: 500; color: var(--color-fg-muted); margin: 0 0 8px; }
.tm-cat-count { font-size: 12px; color: var(--color-fg-subtle); margin-left: 4px; }
.tm-tool-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); gap: 12px; }
.gv-mono { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }
</style>
