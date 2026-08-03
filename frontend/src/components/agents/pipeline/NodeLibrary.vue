<template>
  <div class="sidebar">
    <div class="sidebar-header">
      <h3>节点库</h3>
      <div class="search-field">
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="color:var(--color-fg-light)">
          <circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/>
        </svg>
        <input
          v-model="searchQuery"
          placeholder="搜索节点名称"
          @input="onSearch"
        />
      </div>
    </div>
    <div class="node-catalog">
      <div v-for="group in filteredGroups" :key="group.name" class="node-group">
        <div class="node-group-title">{{ group.name }}</div>
        <div
          v-for="option in group.items"
          :key="option.type"
          class="node-option"
          draggable="true"
          @dragstart="onDragStart($event, option)"
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" v-html="option.icon"></svg>
          <span>{{ option.label }}</span>
          <span class="count">{{ option.count }}</span>
        </div>
      </div>
      <div v-if="filteredGroups.length === 0" class="empty-search">
        未找到匹配节点
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'
import { NodeType, NodeTypeMeta } from '@/constants/pipelineTypes'

const emit = defineEmits(['nodeDragStart'])

const searchQuery = ref('')

// 节点库分组定义
const nodeGroups = [
  {
    name: '流程控制',
    items: [
      { type: NodeType.TRIGGER, label: '触发器', icon: NodeTypeMeta[NodeType.TRIGGER].icon, count: 3 },
      { type: NodeType.CONDITION, label: '条件分支', icon: NodeTypeMeta[NodeType.CONDITION].icon, count: 2 },
      { type: NodeType.PARALLEL, label: '并行分支', icon: NodeTypeMeta[NodeType.PARALLEL].icon, count: 1 },
    ],
  },
  {
    name: '调查分析',
    items: [
      { type: NodeType.LLM, label: '大模型调用', icon: NodeTypeMeta[NodeType.LLM].icon, count: 8 },
      { type: NodeType.DATA_PROCESS, label: '数据处理', icon: NodeTypeMeta[NodeType.DATA_PROCESS].icon, count: 5 },
      { type: NodeType.INTEL_QUERY, label: '外部情报查询', icon: NodeTypeMeta[NodeType.INTEL_QUERY].icon, count: 4 },
      // ── 增量：7 个后端分析节点（type 一律引用 NodeType 枚举，避免字符串字面量）──
      { type: NodeType.FILE_ANALYSIS, label: '文件分析', icon: NodeTypeMeta[NodeType.FILE_ANALYSIS].icon, count: 1 },
      { type: NodeType.PROCESS_ANALYSIS, label: '进程分析', icon: NodeTypeMeta[NodeType.PROCESS_ANALYSIS].icon, count: 1 },
      { type: NodeType.NETWORK_ANALYSIS, label: '网络分析', icon: NodeTypeMeta[NodeType.NETWORK_ANALYSIS].icon, count: 1 },
      { type: NodeType.REGISTRY_ANALYSIS, label: '注册表分析', icon: NodeTypeMeta[NodeType.REGISTRY_ANALYSIS].icon, count: 1 },
      { type: NodeType.TIMELINE, label: '时间线重建', icon: NodeTypeMeta[NodeType.TIMELINE].icon, count: 1 },
      { type: NodeType.ROOT_CAUSE, label: '根因定位', icon: NodeTypeMeta[NodeType.ROOT_CAUSE].icon, count: 1 },
      { type: NodeType.THREAT_INTEL, label: '威胁情报', icon: NodeTypeMeta[NodeType.THREAT_INTEL].icon, count: 1 },
    ],
  },
  {
    name: '安全控制',
    items: [
      { type: NodeType.GUARD, label: '护栏', icon: NodeTypeMeta[NodeType.GUARD].icon, count: 6 },
      { type: NodeType.HITL, label: '人工审核', icon: NodeTypeMeta[NodeType.HITL].icon, count: 2 },
      { type: NodeType.ACTION, label: '处置执行', icon: NodeTypeMeta[NodeType.ACTION].icon, count: 7 },
    ],
  },
  {
    name: '数据源',
    items: [
      { type: NodeType.OUTPUT, label: '知识库', icon: NodeTypeMeta[NodeType.OUTPUT].icon, count: 3 },
      { type: NodeType.MCP_TOOL, label: 'MCP 工具', icon: NodeTypeMeta[NodeType.MCP_TOOL].icon, count: 12 },
      { type: NodeType.INTEL_SOURCE, label: '情报源接入', icon: NodeTypeMeta[NodeType.INTEL_SOURCE].icon, count: 5 },
    ],
  },
]

// 搜索过滤
const filteredGroups = computed(() => {
  const query = searchQuery.value.trim().toLowerCase()
  if (!query) return nodeGroups
  return nodeGroups
    .map(group => ({
      ...group,
      items: group.items.filter(item => item.label.toLowerCase().includes(query)),
    }))
    .filter(group => group.items.length > 0)
})

function onSearch() {
  // 搜索已通过 computed 实时响应
}

function onDragStart(event, option) {
  event.dataTransfer.effectAllowed = 'copy'
  event.dataTransfer.setData('application/node-type', option.type)
  event.dataTransfer.setData('text/plain', option.type)
  emit('nodeDragStart', option)
}
</script>

<style scoped>
.sidebar {
  background: var(--color-canvas-default);
  border-right: 0.5px solid var(--color-border-default);
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.sidebar-header {
  padding: 16px 16px 0;
}
.sidebar-header h3 {
  font-size: 11px;
  font-weight: 500;
  color: var(--color-fg-subtle);
  letter-spacing: 0.4px;
  margin-bottom: 10px;
}
.search-field {
  display: flex;
  align-items: center;
  gap: 8px;
  height: 32px;
  padding: 0 10px;
  border: 0.5px solid var(--color-border-default);
  border-radius: var(--r-btn);
  background: var(--color-canvas-subtle);
}
.search-field:focus-within {
  background: var(--color-canvas-default);
  border-color: var(--color-accent-fg);
}
.search-field input {
  border: none;
  background: transparent;
  outline: none;
  font-size: 12px;
  color: var(--color-fg-default);
  flex: 1;
  font-family: inherit;
}
.search-field input::placeholder {
  color: var(--color-fg-light);
}

.node-catalog {
  flex: 1;
  overflow-y: auto;
  padding: 10px 0 16px;
}

.node-group {
  margin-bottom: 4px;
}
.node-group-title {
  display: flex;
  align-items: center;
  padding: 8px 16px;
  font-size: 10px;
  font-weight: 500;
  color: var(--color-fg-light);
  letter-spacing: 0.4px;
  text-transform: uppercase;
}
.node-group-title::after {
  content: '';
  flex: 1;
  height: 0;
  margin-left: 10px;
  border-bottom: 0.5px solid var(--color-border-default);
}

.node-option {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 7px 16px;
  font-size: 13px;
  cursor: pointer;
  color: var(--color-fg-muted);
  border-left: 2px solid transparent;
}
.node-option:hover {
  background: var(--color-canvas-subtle);
  color: var(--color-fg-default);
}
.node-option svg {
  color: var(--color-fg-light);
  flex-shrink: 0;
}
.node-option .count {
  margin-left: auto;
  font-size: 11px;
  color: var(--color-fg-light);
  background: var(--color-canvas-subtle);
  padding: 1px 6px;
  border-radius: 3px;
}

.empty-search {
  padding: 32px 16px;
  text-align: center;
  font-size: 12px;
  color: var(--color-fg-light);
}
</style>
