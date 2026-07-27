<template>
  <div class="pipeline-redesign">
    <!-- 顶部导航 -->
    <div class="topbar">
      <div class="topbar-left">
        <div class="logo">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="var(--color-accent-fg)" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <rect x="3" y="3" width="7" height="7"/><rect x="14" y="3" width="7" height="7"/><rect x="3" y="14" width="7" height="7"/><rect x="14" y="14" width="7" height="7"/>
          </svg>
          <span>工作流编排</span>
        </div>
        <div class="breadcrumb">
          <span>智能体管理</span>
          <span>/</span>
          <strong>{{ store.pipelineName || '应急响应工作流' }}</strong>
        </div>
      </div>
      <div class="topbar-right">
        <span v-if="store.configDirty" class="unsaved-badge">未保存</span>
        <button
          class="btn"
          :class="{ 'btn-debug-on': store.debugMode }"
          :title="store.debugMode ? '关闭节点级调试' : '开启节点级调试'"
          @click="store.toggleDebug()"
        >
          🐞 调试模式
        </button>
        <button class="btn" @click="onLoadPreset">加载预设</button>
        <button class="btn" @click="onSaveAs">另存为</button>
        <button class="btn" @click="onSetDefault">设为默认</button>
        <button class="btn btn-primary" @click="onPublish">发布</button>
      </div>
    </div>

    <!-- 三栏布局 -->
    <div class="layout">
      <!-- 左侧：节点库 -->
      <NodeLibrary @node-drag-start="onNodeDragStart" />

      <!-- 中间：画布 -->
      <CanvasArea />

      <!-- 右侧：配置面板 -->
      <ConfigPanel />
    </div>

    <!-- Phase 3 · 节点级可视化调试面板（右 Drawer 覆盖式，盖住 ConfigPanel 区） -->
    <DebugPanel />

    <!-- 设为默认流程：场景条件弹窗 -->
    <el-dialog
      v-model="setDefaultDialogVisible"
      title="设为默认流程"
      width="520px"
      :close-on-click-modal="false"
    >
      <el-form :model="setDefaultForm" label-width="110px">
        <el-form-item label="Pipeline">
          <span class="preset-name">{{ store.pipelineName || '未命名流程' }}</span>
        </el-form-item>
        <el-form-item label="规则名称">
          <el-input
            v-model="setDefaultForm.name"
            placeholder="可选，缺省取 Pipeline 名称"
            clearable
          />
        </el-form-item>
        <el-form-item label="事件分类">
          <el-select
            v-model="setDefaultForm.category"
            clearable
            placeholder="可选（不约束 = 任意分类）"
            style="width: 100%"
          >
            <el-option v-for="c in categoryOptions" :key="c" :label="c" :value="c" />
          </el-select>
        </el-form-item>
        <el-form-item label="优先级">
          <el-select
            v-model="setDefaultForm.priority"
            clearable
            placeholder="可选（不约束 = 任意优先级）"
            style="width: 100%"
          >
            <el-option v-for="p in priorityOptions" :key="p" :label="p" :value="p" />
          </el-select>
        </el-form-item>
        <el-form-item label="设为全局默认">
          <el-switch v-model="setDefaultForm.isGlobal" />
          <span class="form-hint">无条件兜底（全表唯一）；关闭则按上面条件匹配</span>
        </el-form-item>
        <el-form-item label="排序">
          <el-input-number v-model="setDefaultForm.priorityOrder" :min="0" :max="999" />
          <span class="form-hint">场景规则确定性排序（小者优先）</span>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="setDefaultDialogVisible = false">取消</el-button>
        <el-button
          type="primary"
          :loading="setDefaultSubmitting"
          @click="onConfirmSetDefault"
        >
          保存为默认规则
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { h, ref } from 'vue'
import { onMounted, onUnmounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { usePipelineEditorStore } from '@/stores/pipelineEditor'
import agentApi from '@/api/agent'
import NodeLibrary from '@/components/agents/pipeline/NodeLibrary.vue'
import CanvasArea from '@/components/agents/pipeline/CanvasArea.vue'
import ConfigPanel from '@/components/agents/pipeline/ConfigPanel.vue'
import DebugPanel from '@/components/agents/pipeline/DebugPanel.vue'

const store = usePipelineEditorStore()

// ===== config-default-pipeline: 设为默认流程 =====

const setDefaultDialogVisible = ref(false)
const setDefaultSubmitting = ref(false)
const categoryOptions = [
  'ransomware', 'port_scan', 'phishing', 'malware',
  'intrusion', 'data_leak', 'ddos', 'brute_force', 'web_attack', 'insider',
]
const priorityOptions = ['P0', 'P1', 'P2', 'P3']
const setDefaultForm = ref({
  name: '',
  category: null,
  priority: null,
  isGlobal: false,
  priorityOrder: 0,
})

function onSetDefault() {
  setDefaultForm.value = {
    name: '',
    category: null,
    priority: null,
    isGlobal: false,
    priorityOrder: 0,
  }
  setDefaultDialogVisible.value = true
}

async function onConfirmSetDefault() {
  const snapshot = store.getPipelineSnapshot()
  const agentNames = snapshot.nodes.map((n) => n.name)
  if (!agentNames.length) {
    ElMessage.warning('画布为空，请先设计流程')
    return
  }
  setDefaultSubmitting.value = true
  try {
    // 1) 确保 preset 存在：优先复用 agents 相同的预设，否则新建
    const presetsRes = await agentApi.pipeline.getPresets()
    const presets = presetsRes.data || presetsRes || []
    const agentsKey = JSON.stringify(agentNames)
    let preset = presets.find(
      (p) => JSON.stringify(p.agents || []) === agentsKey,
    )
    if (!preset) {
      const baseName = store.pipelineName || '未命名流程'
      try {
        const created = await agentApi.pipeline.createPreset(baseName, '', snapshot.nodes)
        preset = created.data || created
      } catch (e) {
        // 名称冲突（409）：改用带时间戳名称重试
        if (e?.response?.status === 409 || e?.code === 409) {
          const created = await agentApi.pipeline.createPreset(
            `${baseName}-${Date.now()}`, '', snapshot.nodes,
          )
          preset = created.data || created
        } else {
          throw e
        }
      }
    }
    if (!preset || preset.id == null) {
      ElMessage.error('保存 pipeline 预设失败')
      return
    }
    // 2) 创建默认规则（先确保 preset 存在 → POST /agents/default-pipelines）
    const payload = {
      preset_id: preset.id,
      name: setDefaultForm.value.name || store.pipelineName || undefined,
      scene_condition: {
        category: setDefaultForm.value.category || null,
        priority: setDefaultForm.value.priority || null,
      },
      is_global: setDefaultForm.value.isGlobal,
      priority_order: setDefaultForm.value.priorityOrder || 0,
    }
    await agentApi.defaultPipelines.create(payload)
    ElMessage.success('已设为默认规则')
    setDefaultDialogVisible.value = false
  } catch (e) {
    // 全局默认已存在(409) 等由后端返回，axios 拦截器已提示
  } finally {
    setDefaultSubmitting.value = false
  }
}

function onNodeDragStart(option) {
  // 拖拽开始时的处理（可选）
}

// ===== H3: beforeunload 离开提醒 =====

function onBeforeUnload(e) {
  if (store.configDirty) {
    e.preventDefault()
    e.returnValue = ''
  }
}

// ===== H6: 键盘快捷键 =====

function onKeyDown(e) {
  // 如果焦点在输入框中，不处理
  const tag = e.target.tagName
  if (tag === 'INPUT' || tag === 'TEXTAREA' || e.target.isContentEditable) return

  const isMac = navigator.platform.toUpperCase().indexOf('MAC') >= 0
  const modKey = isMac ? e.metaKey : e.ctrlKey

  if (modKey && e.key === 's') {
    e.preventDefault()
    onSaveAs()
  } else if (modKey && e.key === 'z') {
    e.preventDefault()
    ElMessage.info('撤销功能开发中')
  } else if ((e.key === 'Delete' || e.key === 'Backspace') && store.selectedNodeId) {
    store.removeNode(store.selectedNodeId)
    ElMessage.info('节点已删除')
    e.preventDefault()
  }
}

// ===== H2: 加载预设 =====

async function onLoadPreset() {
  try {
    const res = await agentApi.pipeline.getPresets()
    const presets = res.data || res || []
    if (!presets.length) {
      ElMessage.info('暂无可用预设')
      return
    }

    // 使用 ElMessageBox 展示预设列表供选择，选中后高亮并显示对勾
    let selectedPreset = null
    let selectedEl = null
    await ElMessageBox({
      title: '加载预设',
      message: h('div', { class: 'preset-list' },
        presets.map(p => h('div', {
          class: 'preset-item',
          style: {
            padding: '8px 12px',
            cursor: 'pointer',
            borderBottom: '0.5px solid var(--color-border-default)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
          },
          onClick: (e) => {
            selectedPreset = p
            selectedEl = e.currentTarget
            // 视觉反馈：高亮 + 左侧强调色 + 对勾
            document.querySelectorAll('.preset-item').forEach(el => {
              el.style.background = ''
              el.style.borderLeft = ''
              el.style.fontWeight = ''
              const check = el.querySelector('.preset-check')
              if (check) check.style.display = 'none'
            })
            e.currentTarget.style.background = 'var(--color-accent-subtle)'
            e.currentTarget.style.borderLeft = '3px solid var(--color-accent)'
            e.currentTarget.style.fontWeight = '500'
            const check = e.currentTarget.querySelector('.preset-check')
            if (check) check.style.display = 'inline'
          },
        }, [
          h('div', null, [
            h('div', { style: 'font-weight:500' }, p.name || p.preset_name),
            h('div', { style: 'font-size:11px;color:var(--color-fg-light)' }, p.description || ''),
          ]),
          h('div', { class: 'preset-check', style: 'display:none;color:var(--color-accent);font-weight:bold;font-size:16px;padding-left:8px;' }, '✓'),
        ]))
      ),
      showCancelButton: true,
      confirmButtonText: '加载',
      beforeClose: (action, instance, done) => {
        if (action === 'confirm') {
          if (!selectedPreset) {
            ElMessage.warning('请先选择一个预设，再点击加载')
            return
          }
          store.loadPreset(selectedPreset)
          ElMessage.success('预设已加载')
        }
        done()
      },
    })
  } catch (e) {
    if (e !== 'cancel' && !e?.toString?.().includes('cancel')) {
      ElMessage.error('加载预设失败: ' + (e.message || e))
    }
  }
}

async function onSaveAs() {
  try {
    const { value: name } = await ElMessageBox.prompt('输入预设名称', '另存为', {
      inputValue: store.pipelineName || '',
      validate: (v) => (v && v.trim() ? true : '名称不能为空'),
    })
    const { value: description } = await ElMessageBox.prompt('输入描述（可选）', '预设描述', {
      inputValue: '',
    })
    const snapshot = store.getPipelineSnapshot()
    const res = await agentApi.pipeline.createPreset(name, description, snapshot.nodes)
    if (res.code === 0 || res.status === 201) {
      ElMessage.success('预设已保存')
      store.configDirty = false
    }
  } catch (e) {
    if (e?.response?.status === 409 || e?.code === 409) {
      ElMessage.warning('名称已存在，请修改')
      // 递归重试
      onSaveAs()
    } else if (e !== 'cancel' && !e?.toString?.().includes('cancel')) {
      ElMessage.error('保存失败: ' + (e.message || e))
    }
  }
}

async function onPublish() {
  try {
    await ElMessageBox.confirm('发布后该工作流将可用于生产环境，确认发布？', '发布确认')
    const snapshot = store.getPipelineSnapshot()
    const { value: name } = await ElMessageBox.prompt('输入预设名称', '发布', {
      inputValue: store.pipelineName || '',
      validate: (v) => (v && v.trim() ? true : '名称不能为空'),
    })
    const { value: description } = await ElMessageBox.prompt('输入描述（可选）', '预设描述', {
      inputValue: '',
    })
    const res = await agentApi.pipeline.createPreset(name, description, snapshot.nodes)
    if (res.code === 0 || res.status === 201) {
      // Plan B：由于后端无 status 字段，发布 = 另存为（前端 UX 区分）
      ElMessage.success('预设已发布')
      store.configDirty = false
    }
  } catch (e) {
    if (e === 'cancel' || e?.toString?.().includes('cancel')) return
    if (e?.response?.status === 409 || e?.code === 409) {
      ElMessage.warning('名称已存在，请修改')
      onPublish()
    } else {
      ElMessage.error('发布失败: ' + (e.message || e))
    }
  }
}

onMounted(() => {
  window.addEventListener('beforeunload', onBeforeUnload)
  window.addEventListener('keydown', onKeyDown)
})

onUnmounted(() => {
  window.removeEventListener('beforeunload', onBeforeUnload)
  window.removeEventListener('keydown', onKeyDown)
})
</script>

<style scoped>
.pipeline-redesign {
  height: 100%;
  display: flex;
  flex-direction: column;
  background: var(--color-canvas-subtle);
  position: relative;
  overflow: hidden;
}

/* ===== 顶部导航 ===== */
.topbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  height: 48px;
  padding: 0 24px;
  background: var(--color-canvas-default);
  border-bottom: 0.5px solid var(--color-border-default);
  flex-shrink: 0;
}
.topbar-left {
  display: flex;
  align-items: center;
  gap: 20px;
}
.topbar-left .logo {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 14px;
  font-weight: 500;
}
.breadcrumb {
  font-size: 12px;
  color: var(--color-fg-subtle);
  display: flex;
  align-items: center;
  gap: 6px;
}
.breadcrumb span {
  color: var(--color-fg-muted);
}
.breadcrumb strong {
  color: var(--color-fg-default);
  font-weight: 500;
}

.topbar-right {
  display: flex;
  align-items: center;
  gap: 8px;
}

/* L5: 未保存标记醒目 */
.unsaved-badge {
  font-size: 11px;
  font-weight: 500;
  color: var(--color-warning-fg);
  background: var(--color-warning-subtle);
  padding: 2px 8px;
  border-radius: 4px;
}

.btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  height: 28px;
  padding: 0 10px;
  font-size: 11px;
  font-weight: 500;
  border-radius: var(--r-btn);
  border: 0.5px solid var(--color-border-default);
  background: var(--color-canvas-default);
  color: var(--color-fg-muted);
  cursor: pointer;
  white-space: nowrap;
}
.btn:hover {
  background: var(--color-canvas-subtle);
}
.btn-debug-on {
  background: var(--color-accent-fg);
  color: #fff;
  border-color: var(--color-accent-fg);
}
.btn-debug-on:hover {
  background: var(--color-accent-fg);
  opacity: 0.9;
}
.btn-primary {
  background: var(--color-accent-fg);
  color: #fff;
  border-color: var(--color-accent-fg);
}
.btn-primary:hover {
  opacity: 0.9;
}

/* ===== 三栏布局 ===== */
.layout {
  display: grid;
  grid-template-columns: 232px 1fr 306px;
  flex: 1;
  min-height: 0;
}

/* ===== 设为默认流程弹窗 ===== */
.preset-name {
  font-weight: 500;
  color: var(--color-fg-default);
}
.form-hint {
  display: inline-block;
  margin-left: 10px;
  font-size: 11px;
  color: var(--color-fg-muted);
}
</style>
