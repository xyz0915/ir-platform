<template>
  <div class="kb-card">
    <!-- 图标 + 名称 -->
    <div class="kb-head">
      <div class="kb-icon">
        <el-icon :size="14"><Collection /></el-icon>
      </div>
      <div class="kb-name">
        <span class="kb-title" :title="kb.name">{{ kb.name }}</span>
        <span class="kb-id gv-mono">{{ kb.kb_id }}</span>
      </div>
    </div>

    <!-- 元数据紧凑 key: value 列表（文档数 / 向量库 / 嵌入模型） -->
    <div class="kb-meta">
      <div class="kb-meta-row">
        <span class="kb-meta-key">文档数</span>
        <span class="kb-meta-val gv-mono">{{ formatDocs(kb.doc_count) }}</span>
      </div>
      <div class="kb-meta-row">
        <span class="kb-meta-key">向量库</span>
        <span class="kb-meta-val gv-mono">{{ kb.vector_store || '—' }}</span>
      </div>
      <div class="kb-meta-row">
        <span class="kb-meta-key">嵌入模型</span>
        <span class="kb-meta-val gv-mono kb-model-val" :title="kb.embedding_model">{{ kb.embedding_model || '—' }}</span>
      </div>
    </div>

    <!-- 索引时间 / 更新时间（相对时间） -->
    <div class="kb-foot">
      <template v-if="kb.index_updated_at">索引 {{ relativeTime(kb.index_updated_at) }}</template>
      <template v-else>更新于 {{ relativeTime(kb.updated_at) }}</template>
    </div>
  </div>
</template>

<script setup>
import { Collection } from '@element-plus/icons-vue'

const props = defineProps({
  /** KnowledgeBase */
  kb: { type: Object, required: true },
})

function formatDocs(n) {
  const num = Number(n) || 0
  return num.toLocaleString('zh-CN')
}

/** 相对时间：刚刚 / X 分钟前 / X 小时前 / X 天前（与 ToolMcpView 心跳一致） */
function relativeTime(iso) {
  if (!iso) return '—'
  const t = new Date(iso)
  if (Number.isNaN(t.getTime())) return iso
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
</script>

<style scoped>
.kb-card {
  background: var(--color-canvas-default);
  border: 0.5px solid var(--color-border-default);
  border-radius: 10px;
  padding: 14px;
  display: flex;
  flex-direction: column;
  gap: 10px;
  height: 100%;
  transition: box-shadow 0.15s, border-color 0.15s;
}
.kb-card:hover {
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.05);
  border-color: #d1d5db;
}
.kb-head { display: flex; align-items: center; gap: 10px; }
.kb-icon {
  width: 28px; height: 28px; border-radius: 7px;
  background: var(--color-canvas-subtle); color: var(--color-fg-muted);
  display: flex; align-items: center; justify-content: center; flex-shrink: 0;
}
.kb-name { display: flex; flex-direction: column; gap: 2px; min-width: 0; }
.kb-title {
  font-size: 13px; font-weight: 600; color: var(--color-fg-default);
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
.kb-id { font-size: 11px; color: var(--color-fg-subtle); }

.kb-meta { display: flex; flex-direction: column; gap: 4px; }
.kb-meta-row {
  display: flex; align-items: baseline; justify-content: space-between;
  gap: 8px; min-width: 0;
}
.kb-meta-key { font-size: 11px; color: var(--color-fg-subtle); flex-shrink: 0; }
.kb-meta-val {
  font-size: 12px; color: var(--color-fg-default);
  min-width: 0; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
.kb-model-val { max-width: 70%; text-align: right; }

.kb-foot {
  font-size: 11px; color: var(--color-fg-subtle);
  border-top: 0.5px solid var(--color-border-default); padding-top: 8px;
}
.gv-mono { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }
</style>
