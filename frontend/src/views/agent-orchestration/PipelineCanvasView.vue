<template>
  <div class="pipeline-canvas-view">
    <div class="pcv-toolbar">
      <div class="pcv-title">
        <h2>流水线 DAG 画布</h2>
        <span class="pcv-sub">拖拽节点 + 连线编排处置链路 · 经 agentApi.pipeline 调用真实接口层</span>
      </div>
      <el-button @click="goRuns">查看运行列表 →</el-button>
    </div>
    <div class="pcv-stage">
      <PipelineCanvas />
    </div>
  </div>
</template>

<script setup>
import { useRouter } from 'vue-router'
import PipelineCanvas from '@/components/agents/PipelineCanvas.vue'

const router = useRouter()
function goRuns() {
  router.push('/agent-orchestration/runs')
}
</script>

<style scoped>
.pipeline-canvas-view { display: flex; flex-direction: column; height: 100%; padding: 16px; gap: 12px; }
.pcv-toolbar { display: flex; align-items: center; justify-content: space-between; flex-shrink: 0; }
.pcv-title h2 { margin: 0; font-size: 18px; font-weight: 600; }
.pcv-sub { display: block; font-size: 12px; color: var(--color-fg-subtle); margin-top: 2px; }
.pcv-stage { flex: 1; min-height: 0; }
</style>
