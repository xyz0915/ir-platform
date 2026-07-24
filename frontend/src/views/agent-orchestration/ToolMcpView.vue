<template>
  <div class="tool-mcp-view">
    <!-- 顶部 -->
    <div class="tm-toolbar">
      <div class="tm-title">
        <h2>工具与 MCP</h2>
        <span class="tm-sub">ToolRegistry 工具清单 + MCP 服务器状态（Mock 适配层）</span>
      </div>
      <el-button @click="store.refreshAll" :loading="store.loading">刷新</el-button>
    </div>

    <!-- MCP 服务器状态 -->
    <h3 class="tm-section">MCP 服务器 ({{ store.mcpServers.length }})</h3>
    <div class="tm-mcp-grid">
      <div v-for="srv in store.mcpServers" :key="srv.server_id" class="tm-mcp-card">
        <div class="tm-mcp-head">
          <div class="tm-mcp-name">
            <span class="tm-mcp-title">{{ srv.name }}</span>
            <span class="tm-mcp-id gv-mono">{{ srv.server_id }}</span>
          </div>
          <span class="tm-dot" :class="'dot-' + srv.status" :title="store.mcpStatusLabel(srv.status)" />
        </div>
        <div class="tm-mcp-meta">
          <div><span class="mi-label">传输</span><span class="mi-value">{{ srv.transport }}</span></div>
          <div><span class="mi-label">工具数</span><span class="mi-value">{{ srv.tools_count }}</span></div>
          <div><span class="mi-label">状态</span>
            <el-tag :type="mcpTag(srv.status)" size="small" effect="light">{{ store.mcpStatusLabel(srv.status) }}</el-tag>
          </div>
        </div>
        <div class="tm-mcp-hb">心跳：{{ fmtTime(srv.last_heartbeat) }}</div>
      </div>
    </div>

    <!-- 工具清单（按分类分组） -->
    <h3 class="tm-section tm-mt">工具清单 ({{ store.toolCount }})</h3>
    <div v-for="[category, list] in store.toolsByCategory" :key="category" class="tm-cat">
      <div class="tm-cat-name">{{ category }} <span class="tm-cat-count">{{ list.length }}</span></div>
      <div class="tm-tool-grid">
        <ToolSchemaCard v-for="tool in list" :key="tool.tool_id" :tool="tool" />
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useToolsStore } from '@/stores/tools'
import ToolSchemaCard from '@/components/agents/ToolSchemaCard.vue'

const store = useToolsStore()

function mcpTag(status) {
  return { online: 'success', degraded: 'warning', offline: 'danger' }[status] || 'info'
}

function fmtTime(iso) {
  if (!iso) return '—'
  try {
    return new Date(iso).toLocaleString('zh-CN', { hour12: false })
  } catch {
    return iso
  }
}

onMounted(store.refreshAll)
</script>

<style scoped>
.tool-mcp-view { padding: 16px; }
.tm-toolbar { display: flex; align-items: center; justify-content: space-between; margin-bottom: 12px; }
.tm-title h2 { margin: 0; font-size: 18px; font-weight: 600; }
.tm-sub { display: block; font-size: 12px; color: var(--color-fg-subtle); margin-top: 2px; }
.tm-section { font-size: 14px; font-weight: 500; margin: 0 0 10px; }
.tm-mt { margin-top: 22px; }

.tm-mcp-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(240px, 1fr)); gap: 12px; margin-bottom: 8px; }
.tm-mcp-card {
  background: var(--color-canvas-default); border: 0.5px solid var(--color-border-default);
  border-radius: 10px; padding: 12px 14px; display: flex; flex-direction: column; gap: 8px;
}
.tm-mcp-head { display: flex; align-items: flex-start; justify-content: space-between; }
.tm-mcp-name { display: flex; flex-direction: column; gap: 2px; }
.tm-mcp-title { font-size: 13px; font-weight: 600; }
.tm-mcp-id { font-size: 11px; color: var(--color-fg-subtle); font-family: ui-monospace, monospace; }
.tm-dot { width: 9px; height: 9px; border-radius: 50%; flex-shrink: 0; }
.dot-online { background: #22C55E; }
.dot-degraded { background: #F59E0B; }
.dot-offline { background: #EF4444; }
.tm-mcp-meta { display: flex; gap: 14px; flex-wrap: wrap; }
.tm-mcp-meta > div { display: flex; flex-direction: column; gap: 2px; }
.mi-label { font-size: 11px; color: var(--color-fg-subtle); }
.mi-value { font-size: 12px; color: var(--color-fg-default); }
.tm-mcp-hb { font-size: 11px; color: var(--color-fg-subtle); }

.tm-cat { margin-bottom: 16px; }
.tm-cat-name { font-size: 12px; color: var(--color-fg-muted); margin: 0 0 8px; }
.tm-cat-count { color: var(--color-fg-subtle); margin-left: 4px; }
.tm-tool-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); gap: 12px; }
.gv-mono { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }
</style>
