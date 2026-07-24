<template>
  <div class="kb-card">
    <!-- 图标 + 名称 -->
    <div class="kb-head">
      <div class="kb-icon">
        <el-icon :size="18"><Collection /></el-icon>
      </div>
      <div class="kb-name">
        <span class="kb-title">{{ kb.name }}</span>
        <span class="kb-id gv-mono">{{ kb.kb_id }}</span>
      </div>
    </div>

    <!-- 指标 -->
    <div class="kb-metrics">
      <div class="kb-metric">
        <span class="km-value">{{ formatDocs(kb.doc_count) }}</span>
        <span class="km-label">文档数</span>
      </div>
      <div class="kb-metric">
        <span class="km-value">{{ kb.vector_store }}</span>
        <span class="km-label">向量库</span>
      </div>
    </div>

    <!-- 嵌入模型 -->
    <div class="kb-model">
      <span class="km-label">嵌入模型</span>
      <span class="kv-value gv-mono">{{ kb.embedding_model }}</span>
    </div>

    <!-- 更新时间 -->
    <div class="kb-foot">更新于 {{ fmtTime(kb.updated_at) }}</div>
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

function fmtTime(iso) {
  if (!iso) return '—'
  try {
    return new Date(iso).toLocaleString('zh-CN', { hour12: false })
  } catch {
    return iso
  }
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
  gap: 12px;
  height: 100%;
}
.kb-head { display: flex; align-items: center; gap: 10px; }
.kb-icon {
  width: 36px; height: 36px; border-radius: 9px;
  background: var(--color-accent-subtle); color: var(--color-accent-fg);
  display: flex; align-items: center; justify-content: center; flex-shrink: 0;
}
.kb-name { display: flex; flex-direction: column; gap: 2px; min-width: 0; }
.kb-title { font-size: 14px; font-weight: 600; color: var(--color-fg-default); }
.kb-id { font-size: 11px; color: var(--color-fg-subtle); }

.kb-metrics { display: flex; gap: 16px; }
.kb-metric { display: flex; flex-direction: column; gap: 2px; }
.km-value { font-size: 16px; font-weight: 700; color: var(--color-fg-default); }
.km-label { font-size: 11px; color: var(--color-fg-subtle); }

.kb-model { display: flex; flex-direction: column; gap: 2px; }
.kv-value { font-size: 12px; color: var(--color-fg-default); }

.kb-foot { font-size: 11px; color: var(--color-fg-subtle); border-top: 0.5px solid var(--color-border-default); padding-top: 8px; }
.gv-mono { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }
</style>
