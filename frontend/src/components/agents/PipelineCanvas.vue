<template>
  <div class="pipeline-canvas">
    <!-- 左：节点面板 -->
    <aside class="pc-palette">
      <NodePalette @add-node="onAddNode" />

      <!-- 校验 / 运行 -->
      <div class="pc-actions">
        <el-button size="small" @click="store.seedFromSample" :loading="store.submitting">加载示例</el-button>
        <el-button size="small" @click="store.clear">清空</el-button>
        <el-button
          size="small"
          :type="connectMode ? 'warning' : 'default'"
          @click="toggleConnect"
        >
          {{ connectMode ? '连线中…' : '连线' }}
        </el-button>
        <el-button size="small" @click="onValidate">校验</el-button>
        <el-button size="small" type="primary" @click="onRun" :loading="store.submitting">运行</el-button>
      </div>

      <!-- 统计 -->
      <div class="pc-stat">
        <span>节点 <b>{{ store.nodeCount }}</b></span>
        <span>边 <b>{{ store.edgeCount }}</b></span>
      </div>

      <!-- 节点检视 / 连线提示 -->
      <div class="pc-inspector" v-if="connectMode">
        <div class="pc-insp-tip">
          <template v-if="!connectSource">点击「源节点」</template>
          <template v-else>已选源：<b>{{ nodeLabel(connectSource) }}</b>，点击「目标节点」完成连线</template>
        </div>
        <el-button size="small" text @click="cancelConnect">取消连线</el-button>
      </div>
      <div class="pc-inspector" v-else-if="selectedId">
        <div class="pc-insp-title">{{ nodeLabel(selectedId) }}</div>
        <el-input v-model="selectedLabel" size="small" @change="updateLabel" class="pc-insp-label" />
        <div class="pc-insp-connect">
          <span class="pc-insp-sub">连接到</span>
          <el-select v-model="targetForEdge" size="small" placeholder="选择目标" class="pc-insp-select">
            <el-option v-for="n in otherNodes" :key="n.node_id" :label="n.label" :value="n.node_id" />
          </el-select>
          <el-button size="small" type="primary" @click="addEdge">＋</el-button>
        </div>
        <el-button size="small" type="danger" text @click="removeSelected">删除节点</el-button>
      </div>
    </aside>

    <!-- 右：画布 -->
    <section class="pc-stage">
      <GraphPanel :nodes="store.graphNodes" :edges="store.graphEdges" @node-click="onNodeClick" />

      <!-- 校验结果浮层 -->
      <div class="pc-validate" v-if="showValidation">
        <el-alert
          v-for="(e, i) in store.validation.errors"
          :key="'e' + i"
          :title="e"
          type="error"
          :closable="false"
          class="pc-val-item"
        />
        <el-alert
          v-for="(w, i) in store.validation.warnings"
          :key="'w' + i"
          :title="w"
          type="warning"
          :closable="false"
          class="pc-val-item"
        />
        <el-alert
          v-if="store.validation.errors.length === 0 && store.validation.warnings.length === 0"
          title="校验通过：DAG 无环。"
          type="success"
          :closable="false"
          class="pc-val-item"
        />
      </div>

      <!-- 运行结果浮层 -->
      <div class="pc-run" v-if="store.currentRunId">
        <el-alert type="success" :closable="false" class="pc-run-alert">
          <template #title>
            已提交编排，运行 ID：<code>{{ store.currentRunId }}</code>
            <el-link type="primary" @click="goRun" class="pc-run-link">查看运行 →</el-link>
          </template>
          <div class="pc-run-note">当前 PipelineEngine 为执行空壳（M1 收敛后由 Orchestrator + SSE 驱动进度）。</div>
        </el-alert>
      </div>
    </section>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { usePipelineCanvasStore } from '@/stores/pipelineCanvas'
import { NODE_TYPE_LABELS } from '@/constants/agentLabels'
import GraphPanel from '@/components/agents/GraphPanel.vue'
import NodePalette from '@/components/agents/NodePalette.vue'

const router = useRouter()
const store = usePipelineCanvasStore()

const connectMode = ref(false)
const connectSource = ref(null)
const selectedId = ref(null)
const selectedLabel = ref('')
const targetForEdge = ref('')
const showValidation = ref(false)
const eventId = ref('SE-DEMO')

// ===== 节点操作 =====
function onAddNode(type) {
  const count = store.nodeCount
  const pos = { x: 120 + (count % 5) * 70, y: 120 + (count % 5) * 60 }
  store.addNode(type, pos)
  showValidation.value = false
}

function onNodeClick(node) {
  if (connectMode.value) {
    if (!connectSource.value) {
      connectSource.value = node.id
    } else if (connectSource.value !== node.id) {
      if (store.connect(connectSource.value, node.id)) {
        ElMessage.success('已连线')
      } else {
        ElMessage.warning('连线已存在或为自环')
      }
      connectSource.value = null
    }
    return
  }
  // 检视模式
  selectedId.value = node.id
  const n = store.nodes.find((x) => x.node_id === node.id)
  selectedLabel.value = n ? n.label : ''
}

const otherNodes = computed(() =>
  store.nodes.filter((n) => n.node_id !== selectedId.value)
)

function nodeLabel(id) {
  const n = store.nodes.find((x) => x.node_id === id)
  return n ? n.label : id
}

function updateLabel(val) {
  const n = store.nodes.find((x) => x.node_id === selectedId.value)
  if (n) n.label = val || NODE_TYPE_LABELS[n.type] || n.node_id
}

function addEdge() {
  if (!targetForEdge.value) return
  if (store.connect(selectedId.value, targetForEdge.value)) {
    ElMessage.success('已连线')
  } else {
    ElMessage.warning('连线已存在或为自环')
  }
  targetForEdge.value = ''
}

function removeSelected() {
  store.removeNode(selectedId.value)
  selectedId.value = null
}

// ===== 连线模式 =====
function toggleConnect() {
  connectMode.value = !connectMode.value
  connectSource.value = null
  selectedId.value = null
}
function cancelConnect() {
  connectMode.value = false
  connectSource.value = null
}

// ===== 校验 / 运行 =====
function onValidate() {
  store.validateGraph()
  showValidation.value = true
}

async function onRun() {
  const v = store.validateGraph()
  if (!v.valid) {
    showValidation.value = true
    ElMessage.error('DAG 校验未通过，请先修复错误（如环路）。')
    return
  }
  const res = await store.run(eventId.value)
  if (res && res.run_id) {
    ElMessage.success(`已提交，运行 ID：${res.run_id}`)
  } else if (res === null) {
    ElMessage.error('DAG 校验未通过，无法运行。')
  } else {
    ElMessage.success('已提交编排。')
  }
}

function goRun() {
  if (store.currentRunId) router.push(`/agent-orchestration/runs/${store.currentRunId}`)
}

onMounted(() => {
  if (store.nodeCount === 0) store.seedFromSample()
})
</script>

<style scoped>
.pipeline-canvas { display: flex; height: 100%; gap: 12px; }
.pc-palette {
  flex: 0 0 220px; display: flex; flex-direction: column; gap: 12px;
  background: var(--color-canvas-default); border: 0.5px solid var(--color-border-default);
  border-radius: 10px; padding: 12px; align-self: stretch; overflow-y: auto;
}
.pc-actions { display: flex; flex-wrap: wrap; gap: 6px; }
.pc-stat { display: flex; gap: 14px; font-size: 12px; color: var(--color-fg-muted); }
.pc-stat b { color: var(--color-fg-default); }
.pc-inspector {
  border-top: 0.5px solid var(--color-border-default); padding-top: 10px;
  display: flex; flex-direction: column; gap: 8px;
}
.pc-insp-tip { font-size: 12px; color: var(--color-fg-muted); line-height: 1.5; }
.pc-insp-title { font-size: 13px; font-weight: 600; color: var(--color-fg-default); }
.pc-insp-label { margin-bottom: 4px; }
.pc-insp-connect { display: flex; align-items: center; gap: 6px; }
.pc-insp-sub { font-size: 11px; color: var(--color-fg-subtle); white-space: nowrap; }
.pc-insp-select { flex: 1; min-width: 0; }

.pc-stage { flex: 1; min-width: 0; position: relative; border: 0.5px solid var(--color-border-default); border-radius: 10px; overflow: hidden; }

.pc-validate {
  position: absolute; top: 10px; left: 10px; right: 10px; z-index: 20;
  display: flex; flex-direction: column; gap: 6px; pointer-events: none;
}
.pc-val-item { pointer-events: auto; }

.pc-run { position: absolute; bottom: 10px; left: 10px; right: 10px; z-index: 20; }
.pc-run-alert code { font-family: ui-monospace, monospace; }
.pc-run-link { margin-left: 12px; }
.pc-run-note { font-size: 11px; color: var(--color-fg-subtle); margin-top: 2px; }
</style>
