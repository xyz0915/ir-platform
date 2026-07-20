<template>
  <div class="rule-table-wrap">
    <div class="rt-toolbar">
      <div class="rt-filters">
        <el-select v-model="filterCategory" size="small" placeholder="全部分类" clearable @change="$emit('filter', { category: filterCategory })">
          <el-option v-for="c in categories" :key="c" :label="c" :value="c" />
        </el-select>
        <el-input v-model="searchQ" size="small" placeholder="搜索规则名称..." clearable style="width:200px" @input="$emit('search', searchQ)" />
      </div>
      <div class="rt-actions">
        <button class="btn btn-xs" @click="selectAll">全选</button>
        <button class="btn btn-xs" @click="clearSelection">清除</button>
        <button class="btn btn-xs btn-primary" :disabled="!selectedIds.length" @click="$emit('batch-enable', selectedIds, true)">批量启用</button>
        <button class="btn btn-xs btn-warning" :disabled="!selectedIds.length" @click="$emit('batch-enable', selectedIds, false)">批量禁用</button>
      </div>
    </div>

    <el-table :data="rules" style="width:100%" size="small" stripe
      @row-click="onRowClick" @selection-change="onSelection">
      <el-table-column type="selection" width="36" />
      <el-table-column label="名称" min-width="180">
        <template #default="{ row }">
          <span class="rt-name" :title="row.description || row.name">{{ row.name }}</span>
        </template>
      </el-table-column>
      <el-table-column label="类别" width="100" prop="category" />
      <el-table-column label="类型" width="90" prop="rule_type" />
      <el-table-column label="严重度" width="80">
        <template #default="{ row }">
          <span class="severity-badge" :class="'badge-' + (row.severity || 'info')">{{ row.severity }}</span>
        </template>
      </el-table-column>
      <el-table-column label="ATT&CK" width="100" prop="mitre_attack" />
      <el-table-column label="来源" width="70" prop="source" />
      <el-table-column label="启用" width="60">
        <template #default="{ row }">
          <span :class="row.enabled ? 'status-on' : 'status-off'">{{ row.enabled ? '是' : '否' }}</span>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="180" fixed="right">
        <template #default="{ row }">
          <button class="btn btn-link btn-xs" @click.stop="$emit('view', row)">详情</button>
          <button class="btn btn-link btn-xs" @click.stop="$emit('edit', row)">编辑</button>
          <button class="btn btn-link btn-xs" :class="row.enabled ? 'text-warning' : 'text-success'"
                  @click.stop="$emit('toggle', row)">{{ row.enabled ? '禁用' : '启用' }}</button>
          <button class="btn btn-link btn-xs text-danger" @click.stop="$emit('delete', row)">删除</button>
        </template>
      </el-table-column>
    </el-table>
  </div>
</template>

<script setup>
import { ref } from 'vue'

defineProps({ rules: { type: Array, default: () => [] }, categories: { type: Array, default: () => [] } })
const emit = defineEmits(['view', 'edit', 'toggle', 'delete', 'batch-enable', 'filter', 'search', 'select-all', 'clear-selection'])

const searchQ = ref('')
const filterCategory = ref('')
const selectedIds = ref([])

function onSelection(selection) { selectedIds.value = selection.map(s => s.id) }
function onRowClick(row) { emit('view', row) }
function selectAll() { emit('select-all') }
function clearSelection() { selectedIds.value = []; emit('clear-selection') }
</script>

<style scoped>
.rule-table-wrap { margin-top: 8px; }
.rt-toolbar { display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; gap: 8px; flex-wrap: wrap; }
.rt-filters { display: flex; gap: 8px; align-items: center; }
.rt-actions { display: flex; gap: 4px; align-items: center; }
.rt-name { font-weight: 500; }
.status-on { color: #16a34a; font-weight: 500; }
.status-off { color: #a3a3a3; }
</style>
