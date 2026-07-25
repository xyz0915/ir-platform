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
  </div>
</template>

<script setup>
import { h } from 'vue'
import { onMounted, onUnmounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { usePipelineEditorStore } from '@/stores/pipelineEditor'
import agentApi from '@/api/agent'
import NodeLibrary from '@/components/agents/pipeline/NodeLibrary.vue'
import CanvasArea from '@/components/agents/pipeline/CanvasArea.vue'
import ConfigPanel from '@/components/agents/pipeline/ConfigPanel.vue'
import DebugPanel from '@/components/agents/pipeline/DebugPanel.vue'

const store = usePipelineEditorStore()

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

    // 使用 ElMessageBox 展示预设列表供选择
    let selectedPreset = null
    await ElMessageBox({
      title: '加载预设',
      message: h('div', { class: 'preset-list' },
        presets.map(p => h('div', {
          class: 'preset-item',
          style: {
            padding: '8px 12px',
            cursor: 'pointer',
            borderBottom: '0.5px solid var(--color-border-default)',
          },
          onClick: (e) => {
            selectedPreset = p
            // 视觉反馈
            document.querySelectorAll('.preset-item').forEach(el => {
              el.style.background = ''
            })
            e.currentTarget.style.background = 'var(--color-accent-subtle)'
          },
        }, [
          h('div', { style: 'font-weight:500' }, p.name || p.preset_name),
          h('div', { style: 'font-size:11px;color:var(--color-fg-light)' }, p.description || ''),
        ]))
      ),
      showCancelButton: true,
      confirmButtonText: '加载',
      beforeClose: (action, instance, done) => {
        if (action === 'confirm' && selectedPreset) {
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
</style>
