<template>
  <div class="config-panel">
    <div class="config-head">
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <circle cx="12" cy="12" r="3"/>
        <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"/>
      </svg>
      <span>{{ panelTitle }}</span>
    </div>
    <div class="config-body">
      <!-- 空状态 (L3) -->
      <div v-if="!node" class="config-empty">
        <svg class="empty-icon" width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" style="color:var(--color-fg-light);margin-bottom:8px">
          <path d="M13 2L3 14h9l-1 8 10-12h-9l1-8z"/>
        </svg>
        <p>选择一个节点查看配置</p>
        <p class="empty-hint">点击左侧画布中的节点</p>
      </div>

      <!-- 配置内容 -->
      <template v-if="node">
        <!-- Agent 配置 -->
        <ConfigSection title="Agent 配置">
          <div class="cfg-row"><span class="lbl">名称</span><span class="val">{{ node.config.name }}</span><span class="edit" @click="onEdit('name')">编辑</span></div>
          <div class="cfg-row"><span class="lbl">版本</span><span class="val"><span class="badge badge-success">{{ node.config.version }}</span></span><span class="edit" @click="onEdit('version')">编辑</span></div>
          <div class="cfg-row"><span class="lbl">模型</span><span class="val">{{ node.config.model || '—' }}</span><span class="edit" @click="onEdit('model')">编辑</span></div>
          <div class="cfg-row"><span class="lbl">温度</span><span class="val"><span class="cfg-pill">{{ node.config.temperature }}</span></span><span class="edit" @click="onEdit('temperature')">编辑</span></div>
        </ConfigSection>

        <!-- 依赖链 -->
        <ConfigSection title="依赖链">
          <div class="cfg-var"><span class="key">上游</span><span v-for="u in (node.dependencies?.upstream || [])" :key="u" class="tag">{{ u }}</span><span v-if="!(node.dependencies?.upstream || []).length" style="color:var(--color-fg-light);font-size:11px">无上游依赖</span></div>
          <div class="cfg-var"><span class="key">下游</span><span v-for="d in (node.dependencies?.downstream || [])" :key="d" class="tag">{{ d }}</span><span v-if="!(node.dependencies?.downstream || []).length" style="color:var(--color-fg-light);font-size:11px">无下游依赖</span></div>
          <div class="cfg-var"><span class="key">数据流</span><span class="tag" style="background:var(--color-canvas-subtle);color:var(--color-fg-muted)">{{ node.dependencies?.dataflow || 'JSON' }}</span></div>
        </ConfigSection>

        <!-- 工具绑定 (C3) -->
        <ConfigSection title="工具绑定">
          <div v-if="node.tools && node.tools.length > 0">
            <div v-for="(tool, i) in node.tools" :key="i" class="cfg-row">
              <span class="lbl">{{ tool.name || `工具 ${i + 1}` }}</span>
              <span class="val" style="font-family:var(--font-mono, monospace);font-size:10px;color:var(--color-fg-light)">{{ tool.endpoint || tool }}</span>
              <span class="edit" @click="onRemoveTool(i)">删除</span>
            </div>
          </div>
          <div v-else style="font-size:11px;color:var(--color-fg-light);padding:4px 0">暂无绑定工具</div>
          <div class="cfg-add-btn" @click="onAddTool">+ 添加工具</div>
        </ConfigSection>

        <!-- 系统提示词 -->
        <ConfigSection title="系统提示词">
          <textarea
            class="cfg-prompt"
            :value="node.prompt"
            @input="onPromptChange($event.target.value)"
            placeholder="输入系统提示词..."
          ></textarea>
        </ConfigSection>

        <!-- 变量 (C4) -->
        <ConfigSection title="变量">
          <div v-if="node.variables && node.variables.length > 0">
            <div v-for="(v, i) in node.variables" :key="i" class="cfg-var">
              <span class="key">{{ v.key || v.name }}</span>
              <span class="tag">{{ v.value || v.source || 'system' }}</span>
              <span class="edit" @click="onRemoveVariable(i)">删除</span>
            </div>
          </div>
          <div v-else style="font-size:11px;color:var(--color-fg-light);padding:4px 0">暂无变量</div>
          <div class="cfg-add-btn" @click="onAddVariable">+ 添加变量</div>
        </ConfigSection>

        <!-- 节点参数（11 节点真实化 T04）— 读写 node.config.input_params -->
        <ConfigSection v-if="nodeParamsVisible" title="节点参数">
          <!-- guard -->
          <div v-if="node.type === NodeType.GUARD" class="node-params">
            <div class="cfg-row"><span class="lbl">策略</span><input class="cfg-input" :value="ip.policy" @input="updateInputParam('policy', $event.target.value)" placeholder="default" /></div>
            <div class="cfg-row"><span class="lbl">检查项</span><textarea class="cfg-prompt" :value="checksText" @input="onChecksText" placeholder='[{"rule":"default_policy","detail":""}]'></textarea></div>
            <div class="cfg-row"><span class="lbl">阻断</span><label class="cfg-switch"><input type="checkbox" :checked="!!ip.block" @change="updateInputParam('block', $event.target.checked)" /><span class="slider"></span></label></div>
            <div class="cfg-row"><span class="lbl">原因</span><input class="cfg-input" :value="ip.reason" @input="updateInputParam('reason', $event.target.value)" placeholder="阻断原因" /></div>
          </div>

          <!-- hitl -->
          <div v-if="node.type === NodeType.HITL" class="node-params">
            <div class="cfg-row"><span class="lbl">动作</span><select class="cfg-input" :value="ip.action" @change="updateInputParam('action', $event.target.value)"><option v-for="a in ACTION_OPTIONS" :key="a" :value="a">{{ a }}</option></select></div>
            <div class="cfg-row"><span class="lbl">目标</span><textarea class="cfg-prompt" :value="targetText" @input="onTargetText" placeholder='{"report_type":"incident"}'></textarea></div>
            <div class="cfg-row"><span class="lbl">原因</span><input class="cfg-input" :value="ip.reason" @input="updateInputParam('reason', $event.target.value)" placeholder="审批原因" /></div>
          </div>

          <!-- condition -->
          <div v-if="node.type === NodeType.CONDITION" class="node-params">
            <div class="cfg-row"><span class="lbl">来源</span><input class="cfg-input" :value="ip.source" @input="updateInputParam('source', $event.target.value)" placeholder="{dep:root_cause}" /></div>
            <div v-for="(c, i) in ip.conditions" :key="i" class="cfg-cond-row">
              <input class="cfg-input sm" :value="c.label" @input="updateCondition(i, 'label', $event.target.value)" placeholder="标签" />
              <input class="cfg-input grow" :value="c.expr" @input="updateCondition(i, 'expr', $event.target.value)" placeholder='{dep:x}.field == true' />
              <span class="edit" @click="removeCondition(i)">删除</span>
            </div>
            <div class="cfg-add-btn" @click="addCondition">+ 添加条件</div>
          </div>

          <!-- parallel -->
          <div v-if="node.type === NodeType.PARALLEL" class="node-params">
            <div v-for="(b, i) in ip.branches" :key="i" class="cfg-cond-row">
              <input class="cfg-input sm" :value="b.label" @input="updateBranch(i, 'label', $event.target.value)" placeholder="分支名" />
              <input class="cfg-input grow" :value="b.target" @input="updateBranch(i, 'target', $event.target.value)" placeholder="下游节点" />
              <span class="edit" @click="removeBranch(i)">删除</span>
            </div>
            <div class="cfg-add-btn" @click="addBranch">+ 添加分支</div>
          </div>

          <!-- data-process -->
          <div v-if="node.type === NodeType.DATA_PROCESS" class="node-params">
            <div class="cfg-row"><span class="lbl">来源</span><input class="cfg-input" :value="ip.source" @input="updateInputParam('source', $event.target.value)" placeholder="{dep:file_analysis}.structured.files" /></div>
            <div v-for="(o, i) in ip.operations" :key="i" class="cfg-op-row">
              <select class="cfg-input sm" :value="o.op" @change="updateOperation(i, 'op', $event.target.value)">
                <option value="select">select</option><option value="filter">filter</option><option value="rename">rename</option><option value="limit">limit</option>
              </select>
              <input v-if="o.op === 'select'" class="cfg-input grow" :value="selectText(o)" @input="updateSelect(i, $event.target.value)" placeholder="字段1,字段2" />
              <input v-if="o.op === 'filter'" class="cfg-input" :value="o.field" @input="updateOperation(i, 'field', $event.target.value)" placeholder="字段" />
              <input v-if="o.op === 'filter'" class="cfg-input grow" :value="o.regex" @input="updateOperation(i, 'regex', $event.target.value)" placeholder="正则，如 \.dll$" />
              <input v-if="o.op === 'rename'" class="cfg-input grow" :value="renameText(o)" @input="updateRename(i, $event.target.value)" placeholder='{"旧名":"新名"}' />
              <input v-if="o.op === 'limit'" class="cfg-input sm" type="number" :value="o.n" @input="updateOperation(i, 'n', Number($event.target.value))" placeholder="N" />
              <span class="edit" @click="removeOperation(i)">删除</span>
            </div>
            <div class="cfg-add-btn" @click="addOperation">+ 添加操作</div>
          </div>

          <!-- intel-query -->
          <div v-if="node.type === NodeType.INTEL_QUERY" class="node-params">
            <div class="cfg-row"><span class="lbl">类型</span><select class="cfg-input" :value="ip.ioc_type" @change="updateInputParam('ioc_type', $event.target.value)"><option value="ip">ip</option><option value="domain">domain</option></select></div>
            <div class="cfg-row"><span class="lbl">指标值</span><input class="cfg-input" :value="ip.ioc_value" @input="updateInputParam('ioc_value', $event.target.value)" placeholder="8.8.8.8" /></div>
            <div class="cfg-row"><span class="lbl">情报源</span><input class="cfg-input" :value="ip.provider_name" @input="updateInputParam('provider_name', $event.target.value)" placeholder="可选" /></div>
          </div>

          <!-- action -->
          <div v-if="node.type === NodeType.ACTION" class="node-params">
            <div class="cfg-row"><span class="lbl">动作</span><select class="cfg-input" :value="ip.action" @change="updateInputParam('action', $event.target.value)"><option v-for="a in ACTION_OPTIONS" :key="a" :value="a">{{ a }}</option></select></div>
            <div class="cfg-row"><span class="lbl">目标</span><textarea class="cfg-prompt" :value="targetText" @input="onTargetText" placeholder='{"ip":"8.8.8.8"}'></textarea></div>
            <div class="cfg-row"><span class="lbl">操作人</span><input class="cfg-input" :value="ip.operator" @input="updateInputParam('operator', $event.target.value)" placeholder="缺省 admin" /></div>
            <div class="cfg-row"><span class="lbl">需审批</span><label class="cfg-switch"><input type="checkbox" :checked="!!ip.require_hitl" @change="updateInputParam('require_hitl', $event.target.checked)" /><span class="slider"></span></label></div>
          </div>

          <!-- output -->
          <div v-if="node.type === NodeType.OUTPUT" class="node-params">
            <div class="cfg-row"><span class="lbl">关键词</span><input class="cfg-input" :value="ip.keyword" @input="updateInputParam('keyword', $event.target.value)" placeholder="如：勒索软件" /></div>
            <div class="cfg-row"><span class="lbl">分类</span><input class="cfg-input" :value="ip.category" @input="updateInputParam('category', $event.target.value)" placeholder="可选" /></div>
            <div class="cfg-row"><span class="lbl">条数</span><input class="cfg-input sm" type="number" :value="ip.limit" @input="updateInputParam('limit', Number($event.target.value))" /></div>
          </div>

          <!-- mcp-tool -->
          <div v-if="node.type === NodeType.MCP_TOOL" class="node-params">
            <div class="cfg-row"><span class="lbl">工具ID</span><input class="cfg-input" :value="ip.tool_id" @input="updateInputParam('tool_id', $event.target.value)" placeholder="如：vt_scan" /></div>
            <div class="cfg-row"><span class="lbl">参数</span><textarea class="cfg-prompt" :value="argsText" @input="onArgsText" placeholder='{"hash":"..."}'></textarea></div>
          </div>

          <!-- intel-source -->
          <div v-if="node.type === NodeType.INTEL_SOURCE" class="node-params">
            <div class="cfg-row"><span class="lbl">仅启用</span><label class="cfg-switch"><input type="checkbox" :checked="!!ip.enabled_only" @change="updateInputParam('enabled_only', $event.target.checked)" /><span class="slider"></span></label></div>
            <div class="cfg-row"><span class="lbl">情报源</span><input class="cfg-input" :value="ip.provider" @input="updateInputParam('provider', $event.target.value)" placeholder="可选过滤" /></div>
          </div>

          <!-- llm（11 节点真实化：增加 allow_default_llm 开关） -->
          <div v-if="node.type === NodeType.LLM" class="node-params">
            <div class="cfg-row"><span class="lbl">Profile</span><input class="cfg-input" :value="ip.model_profile" @input="updateInputParam('model_profile', $event.target.value)" placeholder="可选" /></div>
            <div class="cfg-row"><span class="lbl">Agent引用</span><input class="cfg-input" :value="ip.agent_ref" @input="updateInputParam('agent_ref', $event.target.value)" placeholder="可选" /></div>
            <div class="cfg-row"><span class="lbl">默认LLM</span><label class="cfg-switch"><input type="checkbox" :checked="!!ip.allow_default_llm" @change="updateInputParam('allow_default_llm', $event.target.checked)" /><span class="slider"></span></label></div>
          </div>
        </ConfigSection>
      </template>
    </div>
  </div>
</template>

<script setup>
import { computed, h } from 'vue'
import { ElMessage, ElMessageBox, ElSelect, ElOption } from 'element-plus'
import { usePipelineEditorStore } from '@/stores/pipelineEditor'
import { NodeType, ACTION_OPTIONS, AVAILABLE_MODELS } from '@/constants/pipelineTypes'
import ConfigSection from './ConfigSection.vue'

const store = usePipelineEditorStore()

const node = computed(() => store.selectedNode)

const panelTitle = computed(() => {
  if (!node.value) return '配置面板'
  return `${node.value.name} · 配置`
})

// ===== 11 节点真实化 T04：节点参数区（读写 node.config.input_params）=====

/** 有节点参数表单的节点类型集合。 */
const NODE_PARAMS_TYPES = [
  NodeType.GUARD, NodeType.HITL, NodeType.CONDITION, NodeType.PARALLEL,
  NodeType.DATA_PROCESS, NodeType.INTEL_QUERY, NodeType.ACTION, NodeType.OUTPUT,
  NodeType.MCP_TOOL, NodeType.INTEL_SOURCE, NodeType.LLM,
]

const nodeParamsVisible = computed(() =>
  !!node.value && NODE_PARAMS_TYPES.includes(node.value.type),
)

/** 当前节点 input_params（缺省 {}）。 */
const ip = computed(() => node.value?.config?.input_params || {})

function updateInputParam(key, value) {
  if (!node.value) return
  store.updateNodeConfig(node.value.id, {
    input_params: { ...(node.value.config.input_params || {}), [key]: value },
  })
}

/** JSON 字段编辑（解析失败保留原值，不阻断输入）。 */
function updateJsonField(key, value) {
  if (!node.value) return
  let parsed
  try {
    parsed = JSON.parse(value)
  } catch {
    parsed = (node.value.config.input_params || {})[key]
  }
  updateInputParam(key, parsed)
}

const targetText = computed(() => JSON.stringify(ip.value.target || {}, null, 2))
function onTargetText(e) { updateJsonField('target', e.target.value) }

const checksText = computed(() => JSON.stringify(ip.value.checks || [], null, 2))
function onChecksText(e) { updateJsonField('checks', e.target.value) }

const argsText = computed(() => JSON.stringify(ip.value.args || {}, null, 2))
function onArgsText(e) { updateJsonField('args', e.target.value) }

// ---- condition: conditions[] ----
function addCondition() {
  const list = Array.isArray(ip.value.conditions) ? [...ip.value.conditions] : []
  list.push({ label: '', expr: 'true' })
  updateInputParam('conditions', list)
}
function updateCondition(i, key, value) {
  const list = Array.isArray(ip.value.conditions) ? [...ip.value.conditions] : []
  list[i] = { ...(list[i] || {}), [key]: value }
  updateInputParam('conditions', list)
}
function removeCondition(i) {
  const list = Array.isArray(ip.value.conditions) ? [...ip.value.conditions] : []
  list.splice(i, 1)
  updateInputParam('conditions', list)
}

// ---- parallel: branches[] ----
function addBranch() {
  const list = Array.isArray(ip.value.branches) ? [...ip.value.branches] : []
  list.push({ label: '', target: '' })
  updateInputParam('branches', list)
}
function updateBranch(i, key, value) {
  const list = Array.isArray(ip.value.branches) ? [...ip.value.branches] : []
  list[i] = { ...(list[i] || {}), [key]: value }
  updateInputParam('branches', list)
}
function removeBranch(i) {
  const list = Array.isArray(ip.value.branches) ? [...ip.value.branches] : []
  list.splice(i, 1)
  updateInputParam('branches', list)
}

// ---- data-process: operations[] ----
function addOperation() {
  const list = Array.isArray(ip.value.operations) ? [...ip.value.operations] : []
  list.push({ op: 'select', fields: [], field: '', regex: '', mapping: {}, n: 10 })
  updateInputParam('operations', list)
}
function updateOperation(i, key, value) {
  const list = Array.isArray(ip.value.operations) ? [...ip.value.operations] : []
  list[i] = { ...(list[i] || {}), [key]: value }
  updateInputParam('operations', list)
}
function removeOperation(i) {
  const list = Array.isArray(ip.value.operations) ? [...ip.value.operations] : []
  list.splice(i, 1)
  updateInputParam('operations', list)
}
function selectText(op) {
  return Array.isArray(op.fields) ? op.fields.join(',') : ''
}
function updateSelect(i, text) {
  updateOperation(i, 'fields', text.split(',').map(s => s.trim()).filter(Boolean))
}
function renameText(op) {
  try {
    return JSON.stringify(op.mapping || {})
  } catch {
    return '{}'
  }
}
function updateRename(i, text) {
  let parsed = {}
  try { parsed = JSON.parse(text) } catch { parsed = {} }
  updateOperation(i, 'mapping', parsed)
}

function onEdit(field) {
  if (!node.value) return
  const currentVal = node.value.config[field]

  if (field === 'name') {
    ElMessageBox.prompt('节点名称', '编辑', {
      inputValue: currentVal,
      validate: (v) => (v && v.trim() ? true : '名称不能为空'),
    }).then(({ value }) => {
      store.updateNodeConfig(node.value.id, { name: value })
      ElMessage.success('名称已更新')
    }).catch(() => {})
  } else if (field === 'version') {
    ElMessageBox.prompt('版本号', '编辑', {
      inputValue: currentVal,
    }).then(({ value }) => {
      store.updateNodeConfig(node.value.id, { version: value })
      ElMessage.success('版本已更新')
    }).catch(() => {})
  } else if (field === 'model') {
    // M1: 使用 ElSelect 下拉选择
    const options = AVAILABLE_MODELS.map(m => ({
      value: m,
      label: m,
    }))
    let selectedValue = currentVal || ''
    ElMessageBox({
      title: '选择模型',
      message: h('div', { class: 'model-select-wrap' }, [
        h(ElSelect, {
          modelValue: selectedValue,
          'onUpdate:modelValue': (val) => { selectedValue = val },
          style: { width: '100%' },
          placeholder: '请选择模型',
        }, () => options.map(opt =>
          h(ElOption, { key: opt.value, label: opt.label, value: opt.value })
        )),
      ]),
      showCancelButton: true,
      confirmButtonText: '确认',
      beforeClose: (action, instance, done) => {
        if (action === 'confirm') {
          if (selectedValue) {
            store.updateNodeConfig(node.value.id, { model: selectedValue })
            ElMessage.success('模型已更新')
          }
        }
        done()
      },
    })
  } else if (field === 'temperature') {
    ElMessageBox.prompt('温度值 (0-1，步长 0.05)', '编辑', {
      inputValue: String(currentVal ?? 0.2),
      validate: (v) => {
        const num = parseFloat(v)
        if (isNaN(num) || num < 0 || num > 1) return '温度值必须在 0 到 1 之间'
        return true
      },
    }).then(({ value }) => {
      store.updateNodeConfig(node.value.id, { temperature: parseFloat(value) })
      ElMessage.success('温度已更新')
    }).catch(() => {})
  }
}

// ===== C3: 工具管理 =====

function onAddTool() {
  if (!node.value) return
  ElMessageBox({
    title: '添加工具',
    message: h('div', { class: 'tool-form' }, [
      h('div', { class: 'form-field' }, [
        h('label', '工具名称'),
        h('input', { id: 'toolName', class: 'el-input__inner', placeholder: '如: virustotal' }),
      ]),
      h('div', { class: 'form-field' }, [
        h('label', '端点 URL'),
        h('input', { id: 'toolEndpoint', class: 'el-input__inner', placeholder: 'https://api.example.com/scan' }),
      ]),
      h('div', { class: 'form-field' }, [
        h('label', 'Schema（可选）'),
        h('input', { id: 'toolSchema', class: 'el-input__inner', placeholder: '{ "type": "function", ... }' }),
      ]),
    ]),
    showCancelButton: true,
    confirmButtonText: '添加',
    beforeClose: (action, instance, done) => {
      if (action === 'confirm') {
        const name = document.getElementById('toolName').value
        if (!name.trim()) {
          ElMessage.warning('工具名称不能为空')
          return
        }
        store.addNodeTool(node.value.id, {
          name: name.trim(),
          endpoint: document.getElementById('toolEndpoint').value.trim(),
          schema: document.getElementById('toolSchema').value.trim(),
        })
        ElMessage.success('工具已添加')
      }
      done()
    },
  })
}

function onRemoveTool(index) {
  if (!node.value) return
  store.removeNodeTool(node.value.id, index)
  ElMessage.success('工具已删除')
}

// ===== C4: 变量管理 =====

function onAddVariable() {
  if (!node.value) return
  ElMessageBox({
    title: '添加变量',
    message: h('div', { class: 'var-form' }, [
      h('div', { class: 'form-field' }, [
        h('label', '变量名'),
        h('input', { id: 'varKey', class: 'el-input__inner', placeholder: '如: threshold' }),
      ]),
      h('div', { class: 'form-field' }, [
        h('label', '值 / 来源'),
        h('input', { id: 'varValue', class: 'el-input__inner', placeholder: '如: 0.8 或 {{case.severity}}' }),
      ]),
    ]),
    showCancelButton: true,
    confirmButtonText: '添加',
    beforeClose: (action, instance, done) => {
      if (action === 'confirm') {
        const key = document.getElementById('varKey').value
        if (!key.trim()) {
          ElMessage.warning('变量名不能为空')
          return
        }
        store.addNodeVariable(node.value.id, {
          key: key.trim(),
          value: document.getElementById('varValue').value.trim(),
        })
        ElMessage.success('变量已添加')
      }
      done()
    },
  })
}

function onRemoveVariable(index) {
  if (!node.value) return
  store.removeNodeVariable(node.value.id, index)
  ElMessage.success('变量已删除')
}

function onPromptChange(value) {
  if (node.value) {
    store.updateNodePrompt(node.value.id, value)
  }
}
</script>

<style scoped>
.config-panel {
  background: var(--color-canvas-default);
  border-left: 0.5px solid var(--color-border-default);
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.config-head {
  padding: 14px 16px;
  border-bottom: 0.5px solid var(--color-border-default);
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  font-weight: 500;
}
.config-head svg {
  color: var(--color-fg-light);
}
.config-body {
  flex: 1;
  overflow-y: auto;
}
.config-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 48px 16px;
  font-size: 12px;
  color: var(--color-fg-light);
}
.empty-hint {
  font-size: 11px;
  color: var(--color-fg-light);
  margin-top: 4px;
}

.cfg-row {
  display: flex;
  align-items: center;
  padding: 5px 0;
  font-size: 12px;
  gap: 8px;
}
.cfg-row .lbl {
  color: var(--color-fg-subtle);
  min-width: 56px;
  font-size: 11px;
}
.cfg-row .val {
  flex: 1;
  color: var(--color-fg-default);
  font-size: 12px;
}
.cfg-row .edit {
  font-size: 11px;
  color: var(--color-accent-fg);
  cursor: pointer;
  padding: 1px 6px;
  border-radius: 3px;
  border: 0.5px solid transparent;
}
.cfg-row .edit:hover {
  background: var(--color-accent-subtle);
  border-color: var(--color-accent-subtle);
}

.cfg-pill {
  display: inline-flex;
  align-items: center;
  height: 20px;
  padding: 0 7px;
  border-radius: 4px;
  font-size: 11px;
  font-weight: 500;
  background: var(--color-canvas-subtle);
  color: var(--color-fg-subtle);
}

.cfg-var {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 3px 0;
  font-size: 11px;
}
.cfg-var .key {
  font-family: 'SF Mono', 'Consolas', monospace;
  font-size: 10px;
  color: var(--color-fg-light);
  min-width: 56px;
}
.cfg-var .tag {
  display: inline-flex;
  align-items: center;
  height: 18px;
  padding: 0 6px;
  background: var(--color-accent-subtle);
  color: var(--color-accent-fg);
  border-radius: 3px;
  font-size: 10px;
  font-weight: 500;
}

.cfg-add-btn {
  font-size: 11px;
  color: var(--color-accent-fg);
  cursor: pointer;
  padding: 6px 0 2px;
  font-weight: 500;
}
.cfg-add-btn:hover {
  opacity: 0.8;
}

/* 11 节点真实化 T04：节点参数区控件 */
.node-params {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.cfg-input {
  border: 0.5px solid var(--color-border-default);
  border-radius: var(--r-btn);
  padding: 5px 8px;
  font-size: 11px;
  background: var(--color-canvas-subtle);
  color: var(--color-fg-muted);
  outline: none;
  font-family: inherit;
  flex: 1;
  min-width: 0;
  box-sizing: border-box;
}
.cfg-input:focus {
  border-color: var(--color-accent-fg);
  background: var(--color-canvas-default);
}
.cfg-input.sm {
  flex: 0 0 auto;
  width: 84px;
}
.cfg-input.grow {
  flex: 1;
}
.cfg-cond-row,
.cfg-op-row {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 4px;
}
.cfg-op-row {
  flex-wrap: wrap;
}
.cfg-switch {
  position: relative;
  display: inline-flex;
  align-items: center;
  cursor: pointer;
  margin-left: 2px;
}
.cfg-switch input {
  opacity: 0;
  width: 0;
  height: 0;
  position: absolute;
}
.cfg-switch .slider {
  width: 28px;
  height: 16px;
  background: var(--color-canvas-subtle);
  border: 0.5px solid var(--color-border-default);
  border-radius: 999px;
  position: relative;
  transition: background 0.15s, border-color 0.15s;
}
.cfg-switch .slider::after {
  content: '';
  position: absolute;
  width: 12px;
  height: 12px;
  border-radius: 50%;
  background: var(--color-fg-light);
  top: 1.5px;
  left: 2px;
  transition: transform 0.15s;
}
.cfg-switch input:checked + .slider {
  background: var(--color-accent-fg);
  border-color: var(--color-accent-fg);
}
.cfg-switch input:checked + .slider::after {
  transform: translateX(12px);
  background: #fff;
}

.cfg-prompt {
  border: 0.5px solid var(--color-border-default);
  border-radius: var(--r-btn);
  padding: 8px 10px;
  font-size: 11px;
  color: var(--color-fg-muted);
  background: var(--color-canvas-subtle);
  min-height: 44px;
  font-family: inherit;
  line-height: 1.6;
  resize: none;
  width: 100%;
  outline: none;
  transition: border-color 0.12s;
}
.cfg-prompt:focus {
  border-color: var(--color-accent-fg);
  background: var(--color-canvas-default);
}

.badge {
  display: inline-flex;
  align-items: center;
  height: 18px;
  padding: 0 6px;
  border-radius: 3px;
  font-size: 10px;
  font-weight: 500;
}
.badge-success {
  background: var(--color-success-subtle);
  color: var(--color-success-fg);
}

/* 弹窗表单字段 */
.form-field {
  margin-bottom: 12px;
}
.form-field label {
  display: block;
  font-size: 12px;
  color: var(--color-fg-subtle);
  margin-bottom: 4px;
}
.form-field input {
  width: 100%;
  box-sizing: border-box;
}
</style>
