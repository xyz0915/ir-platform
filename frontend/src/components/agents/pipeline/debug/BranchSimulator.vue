<template>
  <div v-if="node && node.type === 'branch'" class="dbg-branch">
    <div class="dbg-section-title">分支模拟（手动指定）</div>
    <div v-if="!branches.length" class="dbg-empty">该分支节点尚无 branches 配置</div>
    <template v-else>
      <el-radio-group :model-value="chosen" @change="onPick">
        <el-radio v-for="b in branches" :key="b.label" :label="b.label" border>{{ b.label }}</el-radio>
      </el-radio-group>
      <div class="dbg-branch-info">
        下游激活 {{ activeCount }} · 剪枝 {{ prunedCount }}
      </div>
    </template>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { usePipelineEditorStore } from '@/stores/pipelineEditor'
import { NodeType } from '@/constants/pipelineTypes'

const store = usePipelineEditorStore()
const node = computed(() => store.selectedNode)
const branches = computed(() => (node.value?.config?.branches) || [])
const chosen = computed(
  () => store.branchSelection[store.selectedNodeId] || (branches.value[0]?.label),
)
const activeCount = computed(() => store.branchPath?.activeNodes?.size || 0)
const prunedCount = computed(() => (store.branchPath?.prunedEdges?.length) || 0)

function onPick(label) {
  const id = store.selectedNodeId
  if (id) store.applyBranchSelection(id, label)
}
</script>

<style scoped>
.dbg-branch { padding: 4px 0; }
.dbg-empty { font-size: 11px; color: var(--color-fg-light); padding: 12px 0; }
.dbg-section-title {
  font-size: 11px; font-weight: 500; color: var(--color-fg-subtle);
  margin-bottom: 6px;
}
.dbg-branch-info { font-size: 10px; color: var(--color-fg-muted); margin-top: 8px; }
</style>
