<template>
  <div class="profile-selector">
    <!-- 下拉选择框 -->
    <div class="selector-row">
      <span class="selector-label">当前配置：</span>
      <el-select
        :model-value="modelValue"
        @update:model-value="onSelect"
        placeholder="选择 AI 配置"
        class="profile-select"
        :disabled="profiles.length === 0"
      >
        <el-option
          v-for="p in profiles"
          :key="p.id"
          :label="optionLabel(p)"
          :value="p.id"
        />
      </el-select>
      <el-tag
        v-if="modelValue === activeProfileId"
        type="success"
        size="small"
        class="ml-10"
      >
        活跃
      </el-tag>
    </div>

    <!-- 操作按钮行 -->
    <div class="action-row">
      <el-button type="primary" size="small" @click="$emit('add')">新增</el-button>
      <el-button
        size="small"
        @click="onEdit"
        :disabled="!selectedId"
      >编辑</el-button>
      <el-button
        size="small"
        @click="onActivate"
        :disabled="!selectedId || selectedId === activeProfileId"
      >设为活跃</el-button>
      <el-popconfirm
        title="确认删除该配置？此操作不可撤销"
        @confirm="onDelete"
        :disabled="profiles.length <= 1"
      >
        <template #reference>
          <el-button
            type="danger"
            size="small"
            :disabled="!selectedId || profiles.length <= 1"
          >删除</el-button>
        </template>
      </el-popconfirm>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'

// ============================================================
// Props
// ============================================================
const props = defineProps({
  /** Profile 列表 */
  profiles: {
    type: Array,
    default: () => [],
  },
  /** 当前选中的 profile_id */
  modelValue: {
    type: [Number, String, null],
    default: null,
  },
  /** 活跃 Profile ID（用于显示"活跃"标签） */
  activeProfileId: {
    type: [Number, String, null],
    default: null,
  },
})

// ============================================================
// Emits
// ============================================================
const emit = defineEmits([
  'update:modelValue',
  'add',
  'edit',
  'delete',
  'activate',
])

// ============================================================
// Computed
// ============================================================
const selectedId = computed(() => props.modelValue || null)

// ============================================================
// Handlers
// ============================================================
function onSelect(val) {
  emit('update:modelValue', val)
}

function onEdit() {
  if (selectedId.value) {
    emit('edit', selectedId.value)
  }
}

function onActivate() {
  if (selectedId.value) {
    emit('activate', selectedId.value)
  }
}

function onDelete() {
  if (selectedId.value) {
    emit('delete', selectedId.value)
  }
}

function optionLabel(p) {
  let label = p.profile_name || `配置 #${p.id}`
  if (p.provider) {
    label += ` (${p.provider})`
  }
  if (p.is_active === 1 || p.id === props.activeProfileId) {
    label += ' (活跃)'
  }
  return label
}
</script>

<style scoped>
.profile-selector {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.selector-row {
  display: flex;
  align-items: center;
  gap: 10px;
}

.selector-label {
  font-size: 14px;
  color: #606266;
  white-space: nowrap;
}

.profile-select {
  width: 280px;
}

.action-row {
  display: flex;
  gap: 8px;
}

.ml-10 {
  margin-left: 10px;
}
</style>
