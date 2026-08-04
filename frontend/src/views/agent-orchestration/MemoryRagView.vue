<template>
  <div class="memory-rag-view">
    <!-- 顶部 -->
    <div class="mr-toolbar">
      <div class="mr-title">
        <h2>记忆与 RAG</h2>
        <span class="mr-sub">长期记忆 / 知识库 / 向量库（真实数据）</span>
      </div>
      <el-button @click="store.fetchKnowledgeBases" :loading="store.loading">刷新</el-button>
    </div>

    <!-- 概览指标 -->
    <div class="mr-stats">
      <div class="mr-stat">
        <span class="gs-label">知识库</span>
        <span class="gs-value">{{ store.knowledgeBases.length }}</span>
      </div>
      <div class="mr-stat">
        <span class="gs-label">向量文档总数</span>
        <span class="gs-value gs-blue">{{ store.vectorDocCount.toLocaleString('zh-CN') }}</span>
      </div>
      <div class="mr-stat">
        <span class="gs-label">已批准草稿</span>
        <span class="gs-value gs-green">{{ (store.stats.approved_drafts || 0).toLocaleString('zh-CN') }}</span>
      </div>
      <div class="mr-stat">
        <span class="gs-label">索引状态</span>
        <span class="gs-value gs-sm" :class="store.collectionReady ? 'gs-ok' : 'gs-warn'">
          {{ store.collectionReady ? '就绪' : '未就绪/降级关键词检索' }}
        </span>
      </div>
    </div>

    <!-- 知识库卡片 -->
    <h3 class="mr-section">知识库 / 向量库 ({{ store.knowledgeBases.length }})</h3>
    <div class="mr-grid" v-loading="store.loading">
      <KnowledgeBaseCard
        v-for="kb in store.knowledgeBases"
        :key="kb.kb_id"
        :kb="kb"
      />
      <el-empty
        v-if="!store.loading && store.knowledgeBases.length === 0"
        description="向量库未初始化，当前使用关键词检索降级"
      />
    </div>

    <!-- RAG 检索增强示意 -->
    <h3 class="mr-section mr-mt">检索增强 (RAG) 示意</h3>
    <el-card class="mr-hint-card" shadow="never">
      <p class="mr-hint">
        运行时，编排智能体可经由画布「知识库」节点从向量库检索相似上下文
        （文档块 + 向量相似度）注入到 Prompt，提升调查与处置的准确率。
        向量相似度检索服务由 <code>{{ vectorStore }}</code> 提供；
        知识增强注入需在流程中显式触发（画布知识库节点），自动注入开关见设置。
      </p>
      <div class="mr-flow">
        <span class="mr-flow-node">查询</span>
        <el-icon><Right /></el-icon>
        <span class="mr-flow-node">向量检索</span>
        <el-icon><Right /></el-icon>
        <span class="mr-flow-node">Top-K 文档块</span>
        <el-icon><Right /></el-icon>
        <span class="mr-flow-node">护栏评估</span>
        <el-icon><Right /></el-icon>
        <span class="mr-flow-node mr-node-accent">注入推理</span>
      </div>
    </el-card>
  </div>
</template>

<script setup>
import { computed, onMounted } from 'vue'
import { Right } from '@element-plus/icons-vue'
import { useMemoryStore } from '@/stores/memory'
import KnowledgeBaseCard from '@/components/agents/KnowledgeBaseCard.vue'

const store = useMemoryStore()
const vectorStore = computed(() => store.stats.vector_store || 'Chroma')

onMounted(store.fetchKnowledgeBases)
</script>

<style scoped>
.memory-rag-view { padding: 16px; }
.mr-toolbar { display: flex; align-items: center; justify-content: space-between; margin-bottom: 12px; }
.mr-title h2 { margin: 0; font-size: 18px; font-weight: 600; }
.mr-sub { display: block; font-size: 12px; color: var(--color-fg-subtle); margin-top: 2px; }

.mr-stats { display: flex; flex-wrap: wrap; gap: 12px; margin-bottom: 16px; }
.mr-stat {
  flex: 1; min-width: 150px; max-width: 240px; background: var(--color-canvas-default);
  border: 0.5px solid var(--color-border-default); border-radius: 8px;
  padding: 12px 16px; display: flex; flex-direction: column; gap: 4px;
}
.gs-label { font-size: 12px; color: var(--color-fg-subtle); }
.gs-value { font-size: 22px; font-weight: 700; color: var(--color-fg-default); font-family: ui-monospace, monospace; }
.gs-sm { font-size: 15px; line-height: 1.6; }
.gs-blue { color: #3B82F6; }
.gs-green { color: #10B981; }
.gs-ok { color: #10B981; }
.gs-warn { color: #F59E0B; }

.mr-section { font-size: 14px; font-weight: 500; margin: 0 0 10px; }
.mr-mt { margin-top: 22px; }
.mr-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 12px; }

.mr-hint-card { border-radius: 10px; border: 1px solid var(--color-border-default); }
.mr-hint { font-size: 13px; color: var(--color-fg-muted); line-height: 1.7; margin: 0 0 12px; }
.mr-hint code { background: var(--color-canvas-inset); padding: 1px 5px; border-radius: 4px; font-family: ui-monospace, monospace; }
.mr-flow { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.mr-flow-node {
  font-size: 12px; padding: 5px 12px; border-radius: 16px;
  background: var(--color-canvas-subtle); color: var(--color-fg-default); border: 0.5px solid var(--color-border-default);
}
.mr-node-accent { background: var(--color-accent-subtle); color: var(--color-accent-fg); border-color: var(--color-accent-fg); }
</style>
