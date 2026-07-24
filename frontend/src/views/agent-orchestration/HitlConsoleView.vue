<template>
  <div class="hitl-console">
    <el-empty v-if="!isAdmin" description="HITL 审批仅限管理员操作" :image-size="70" />

    <template v-else>
      <div class="hc-toolbar">
        <div class="hc-title">
          <el-icon><Stamp /></el-icon>
          待审批处置队列
          <el-tag type="warning" size="small" effect="light">{{ store.pendingCount }} 条</el-tag>
        </div>
        <el-button size="small" :loading="store.loading" @click="refresh">
          <el-icon><Refresh /></el-icon> 刷新
        </el-button>
      </div>

      <div class="hc-body">
        <!-- 左：队列 -->
        <div class="hc-list" v-loading="store.loading">
          <el-empty v-if="!store.loading && store.approvals.length === 0" description="暂无待审批处置" :image-size="60" />

          <div
            v-for="item in store.approvals"
            :key="item.id"
            class="hc-item"
            :class="{ active: selected?.id === item.id }"
            @click="selected = item"
          >
            <div class="hc-item-head">
              <span class="hc-item-action">{{ itemAction(item) }}</span>
              <StatusBadge type="hitl" :value="item.status" />
            </div>
            <div class="hc-item-meta">
              <span class="mono">{{ item.run_id }}</span>
              <span class="hc-item-time">{{ relativeTime(item.created_at) }}</span>
            </div>
          </div>
        </div>

        <!-- 右：上下文面板 -->
        <div class="hc-detail">
          <HitlContextPanel :task="selected" @resolved="onResolved" />
        </div>
      </div>
    </template>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useAuthStore } from '@/stores/auth'
import { useAgentOrchestrationStore } from '@/stores/agents'
import { Stamp, Refresh } from '@element-plus/icons-vue'
import StatusBadge from '@/components/agents/StatusBadge.vue'
import HitlContextPanel from '@/components/agents/HitlContextPanel.vue'

const authStore = useAuthStore()
const store = useAgentOrchestrationStore()
const isAdmin = computed(() => authStore.user?.role === 'admin')
const selected = ref(null)

onMounted(() => {
  if (isAdmin.value) {
    store.fetchApprovals().then(() => {
      if (store.approvals.length) selected.value = store.approvals[0]
    })
  }
})

function refresh() {
  store.fetchApprovals().then(() => {
    if (selected.value && !store.approvals.find((a) => a.id === selected.value.id)) {
      selected.value = store.approvals[0] || null
    }
  })
}

function onResolved() {
  refresh()
}

function itemAction(item) {
  if (item.action) return item.action
  const raw = item.target_json || item.target
  if (typeof raw === 'string' && raw) {
    try {
      const o = JSON.parse(raw)
      if (o.host) return `隔离主机 ${o.host}`
      if (o.ip) return `处置 ${o.ip}`
    } catch { /* ignore */ }
  }
  return '待处置动作'
}

function relativeTime(val) {
  if (!val) return ''
  const diff = Math.floor((Date.now() - new Date(val).getTime()) / 1000)
  if (diff < 60) return '刚刚'
  if (diff < 3600) return `${Math.floor(diff / 60)} 分钟前`
  if (diff < 86400) return `${Math.floor(diff / 3600)} 小时前`
  return `${Math.floor(diff / 86400)} 天前`
}
</script>

<style scoped>
.hitl-console { display: flex; flex-direction: column; height: 100%; }
.hc-toolbar { display: flex; align-items: center; justify-content: space-between; margin-bottom: 12px; }
.hc-title { display: inline-flex; align-items: center; gap: 8px; font-size: 15px; font-weight: 600; color: var(--color-fg-default); }
.hc-title .el-icon { color: var(--color-warning-fg, #d97706); }
.hc-body { flex: 1; display: flex; gap: 16px; min-height: 0; }
.hc-list {
  flex: 0 0 340px;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 8px;
  border: 1px solid var(--color-border-default);
  border-radius: 12px;
  padding: 10px;
  background: var(--color-canvas-default);
}
.hc-item {
  border: 1px solid var(--color-border-default);
  border-radius: 8px;
  padding: 10px 12px;
  cursor: pointer;
  background: var(--color-canvas-subtle);
  transition: all 0.15s;
}
.hc-item:hover { border-color: var(--color-accent-fg); }
.hc-item.active { border-color: var(--color-accent-fg); background: var(--color-accent-subtle); }
.hc-item-head { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.hc-item-action { font-weight: 600; font-size: 13px; color: var(--color-fg-default); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.hc-item-meta { display: flex; align-items: center; justify-content: space-between; margin-top: 6px; font-size: 11px; color: var(--color-fg-subtle); }
.mono { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }
.hc-detail {
  flex: 1;
  min-width: 0;
  border: 1px solid var(--color-border-default);
  border-radius: 12px;
  padding: 14px;
  background: var(--color-canvas-default);
  overflow-y: auto;
}
</style>
