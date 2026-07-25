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
      </template>
    </div>
  </div>
</template>

<script setup>
import { computed, h } from 'vue'
import { ElMessage, ElMessageBox, ElSelect, ElOption } from 'element-plus'
import { usePipelineEditorStore } from '@/stores/pipelineEditor'
import { AVAILABLE_MODELS } from '@/constants/pipelineTypes'
import ConfigSection from './ConfigSection.vue'

const store = usePipelineEditorStore()

const node = computed(() => store.selectedNode)

const panelTitle = computed(() => {
  if (!node.value) return '配置面板'
  return `${node.value.name} · 配置`
})

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
