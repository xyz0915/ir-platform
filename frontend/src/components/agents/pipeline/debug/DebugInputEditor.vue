<template>
  <div class="dbg-input">
    <div v-if="!node" class="dbg-empty">未选中节点</div>
    <template v-else>
      <!-- 上下文变量 context_vars -->
      <div class="dbg-section">
        <div class="dbg-section-title">上下文变量 context_vars</div>
        <div class="dbg-row">
          <label>host_id</label>
          <el-input
            v-model="ctxForm.host_id"
            size="small"
            placeholder="可选，优先于 event_id"
            @input="onCtxChange"
          />
        </div>
        <div class="dbg-row">
          <label :class="{ 'dbg-req': isTrigger }">
            event_id<span v-if="isTrigger" class="dbg-asterisk">*</span>
          </label>
          <el-input
            v-model="ctxForm.event_id"
            size="small"
            :placeholder="isTrigger ? '必填：触发器（分诊）需要 event_id' : '可选，缺失时按 host_id 反查'"
            @input="onCtxChange"
          />
        </div>
        <div v-if="isTrigger" class="dbg-trigger-hint">
          ⚠ 触发器（分诊）需要 event_id：请填写上方 event_id，否则分诊将无法执行并返回失败提示。
        </div>
        <div v-if="extraVars.length" class="dbg-extra">
          <el-tag v-for="v in extraVars" :key="v.key" size="small" type="info">
            {{ v.key }}={{ v.value }}
          </el-tag>
        </div>
      </div>

      <!-- 输入参数 input_params：表单 / JSON 双模 -->
      <div class="dbg-section">
        <div class="dbg-section-title">
          输入参数 input_params
          <el-radio-group v-model="paramsMode" size="small" class="dbg-mode">
            <el-radio-button label="form">表单</el-radio-button>
            <el-radio-button label="json">JSON</el-radio-button>
          </el-radio-group>
        </div>

        <template v-if="paramsMode === 'form'">
          <div v-for="(row, i) in paramRows" :key="i" class="dbg-kv">
            <el-input v-model="row.k" size="small" placeholder="key" @input="onParamsChange" />
            <el-input v-model="row.v" size="small" placeholder="value" @input="onParamsChange" />
            <button class="dbg-del" type="button" @click="removeRow(i)">×</button>
          </div>
          <el-button size="small" class="dbg-add" @click="addRow">+ 添加参数</el-button>
        </template>

        <template v-else>
          <el-input
            v-model="paramJson"
            type="textarea"
            :rows="6"
            size="small"
            placeholder='{"max_files": 15}'
            @blur="onJsonBlur"
          />
          <div v-if="jsonError" class="dbg-json-err">JSON 解析失败：{{ jsonError }}</div>
        </template>
      </div>
    </template>
  </div>
</template>

<script setup>
import { ref, reactive, computed, watch } from 'vue'
import { usePipelineEditorStore } from '@/stores/pipelineEditor'
import { flattenVariables } from '@/constants/pipelineTypes'

const store = usePipelineEditorStore()
const node = computed(() => store.selectedNode)
const isTrigger = computed(() => node.value?.type === 'trigger')
const paramsMode = ref('form')

const ctxForm = reactive({ host_id: '', event_id: '' })
const paramRows = reactive([{ k: '', v: '' }])
const paramJson = ref('{}')
const jsonError = ref('')

const extraVars = computed(() => {
  if (!node.value) return []
  const flat = flattenVariables(node.value.variables)
  return Object.entries(flat)
    .filter(([k]) => k !== 'host_id' && k !== 'event_id')
    .map(([k, v]) => ({ key: k, value: v }))
})

function currentDraft() {
  const id = store.selectedNodeId
  if (!id) return { input_params: {}, context_vars: {}, mode: 'real' }
  return store.ensureDebugDraft(id)
}

function seed() {
  const id = store.selectedNodeId
  if (!id) return
  const d = store.ensureDebugDraft(id)
  const cv = d.context_vars || {}
  ctxForm.host_id = cv.host_id || ''
  ctxForm.event_id = cv.event_id || ''
  const ip = d.input_params || {}
  const keys = Object.keys(ip)
  if (keys.length) {
    paramRows.splice(0, paramRows.length, ...keys.map(k => ({ k, v: typeof ip[k] === 'string' ? ip[k] : JSON.stringify(ip[k]) })))
    paramsMode.value = 'form'
  } else {
    paramRows.splice(0, paramRows.length, { k: '', v: '' })
  }
  paramJson.value = JSON.stringify(ip, null, 2)
}

watch(() => store.selectedNodeId, () => { seed() }, { immediate: true })

function onCtxChange() {
  const id = store.selectedNodeId
  if (!id) return
  const base = node.value ? flattenVariables(node.value.variables) : {}
  const merged = { ...base }
  if (ctxForm.host_id) merged.host_id = ctxForm.host_id
  if (ctxForm.event_id) merged.event_id = ctxForm.event_id
  const d = currentDraft()
  store.saveDebugDraft(id, { ...d, context_vars: merged })
}

function parseVal(v) {
  if (v === '' || v == null) return v
  try { return JSON.parse(v) } catch { return v }
}

function onParamsChange() {
  const obj = {}
  paramRows.forEach(r => { if (r.k) obj[r.k] = parseVal(r.v) })
  const id = store.selectedNodeId
  if (!id) return
  const d = currentDraft()
  store.saveDebugDraft(id, { ...d, input_params: obj })
  paramJson.value = JSON.stringify(obj, null, 2)
}

function addRow() { paramRows.push({ k: '', v: '' }) }
function removeRow(i) { paramRows.splice(i, 1) }

function onJsonBlur() {
  try {
    const obj = JSON.parse(paramJson.value || '{}')
    jsonError.value = ''
    const id = store.selectedNodeId
    if (!id) return
    const d = currentDraft()
    store.saveDebugDraft(id, { ...d, input_params: obj })
    const keys = Object.keys(obj)
    paramRows.splice(0, paramRows.length, ...keys.map(k => ({
      k,
      v: typeof obj[k] === 'string' ? obj[k] : JSON.stringify(obj[k]),
    })))
  } catch (e) {
    jsonError.value = e.message
  }
}
</script>

<style scoped>
.dbg-input { padding: 4px 0; }
.dbg-empty { font-size: 11px; color: var(--color-fg-light); padding: 12px 0; }
.dbg-section { margin-bottom: 12px; }
.dbg-section-title {
  font-size: 11px;
  font-weight: 500;
  color: var(--color-fg-subtle);
  margin-bottom: 6px;
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.dbg-row { display: flex; align-items: center; gap: 8px; margin-bottom: 6px; }
.dbg-row label { width: 64px; font-size: 11px; color: var(--color-fg-muted); }
.dbg-req { color: var(--color-danger-fg) !important; font-weight: 600; }
.dbg-asterisk { margin-left: 2px; color: var(--color-danger-fg); }
.dbg-trigger-hint {
  font-size: 10px;
  color: var(--color-danger-fg);
  background: var(--color-danger-muted, rgba(248, 81, 73, 0.1));
  border: 0.5px solid var(--color-danger-fg);
  border-radius: var(--r-btn);
  padding: 4px 6px;
  margin: -2px 0 6px;
  line-height: 1.4;
}
.dbg-extra { display: flex; flex-wrap: wrap; gap: 4px; margin-top: 4px; }
.dbg-mode { margin-left: auto; }
.dbg-kv { display: flex; align-items: center; gap: 6px; margin-bottom: 6px; }
.dbg-kv .el-input { flex: 1; }
.dbg-del {
  width: 22px; height: 22px; flex-shrink: 0;
  border: 0.5px solid var(--color-border-default);
  background: var(--color-canvas-default);
  color: var(--color-fg-muted);
  border-radius: var(--r-btn);
  cursor: pointer;
}
.dbg-del:hover { color: var(--color-danger-fg); border-color: var(--color-danger-fg); }
.dbg-add { margin-top: 2px; }
.dbg-json-err { font-size: 10px; color: var(--color-danger-fg); margin-top: 4px; }
</style>
