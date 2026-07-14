<template>
  <div class="smart-search-bar">
    <!-- 搜索框 -->
    <el-input
      v-model="localFilters.keyword"
      placeholder="搜索事件 ID / 类型 / 主机..."
      clearable
      size="small"
      class="filter-search"
      @input="onFilterChange"
    />

    <!-- 时间范围 -->
    <el-date-picker
      v-model="localFilters.timeRange"
      type="datetimerange"
      range-separator="至"
      start-placeholder="开始时间"
      end-placeholder="结束时间"
      size="small"
      class="filter-date"
      format="YYYY-MM-DD HH:mm"
      value-format="YYYY-MM-DDTHH:mm:ssZ"
      @change="onFilterChange"
    />

    <!-- 事件类型 -->
    <el-select
      v-model="localFilters.eventTypes"
      multiple
      placeholder="事件类型"
      size="small"
      class="filter-select"
      collapse-tags
      collapse-tags-tooltip
      @change="onFilterChange"
    >
      <el-option
        v-for="item in eventTypeOptions"
        :key="item.value"
        :label="item.label"
        :value="item.value"
      />
    </el-select>

    <!-- 严重等级 -->
    <el-select
      v-model="localFilters.severities"
      multiple
      placeholder="严重等级"
      size="small"
      class="filter-select"
      collapse-tags
      collapse-tags-tooltip
      @change="onFilterChange"
    >
      <el-option label="严重 (critical)" value="critical" />
      <el-option label="高危 (high)" value="high" />
      <el-option label="中危 (medium)" value="medium" />
      <el-option label="低危 (low)" value="low" />
      <el-option label="信息 (info)" value="info" />
    </el-select>

    <!-- 处置状态 -->
    <el-select
      v-model="localFilters.statuses"
      multiple
      placeholder="处置状态"
      size="small"
      class="filter-select"
      collapse-tags
      collapse-tags-tooltip
      @change="onFilterChange"
    >
      <el-option label="待处理 (pending)" value="pending" />
      <el-option label="分诊中 (triaging)" value="triaging" />
      <el-option label="调查中 (investigating)" value="investigating" />
      <el-option label="已解决 (resolved)" value="resolved" />
      <el-option label="已误报 (rejected)" value="rejected" />
    </el-select>

    <!-- 快速筛选标签 -->
    <el-tag
      v-for="tag in quickTags"
      :key="tag.key"
      :type="activeQuickTag === tag.key ? 'primary' : 'info'"
      size="small"
      class="quick-tag"
      @click="applyQuickTag(tag)"
    >
      {{ tag.label }}
    </el-tag>

    <!-- 重置按钮 -->
    <el-button size="small" @click="onReset">重置</el-button>
  </div>
</template>

<script setup>
import { reactive, ref, watch } from 'vue'

const props = defineProps({
  filters: { type: Object, required: true },
})

const emit = defineEmits(['update:filters', 'reset'])

const eventTypeOptions = [
  { label: '进程启动', value: 'process_start' },
  { label: '进程退出', value: 'process_terminate' },
  { label: '出站连接', value: 'network_outbound' },
  { label: '端口监听', value: 'network_listen' },
  { label: '注册表写入', value: 'registry_modify' },
  { label: '注册表删除', value: 'registry_delete' },
  { label: '文件创建', value: 'file_create' },
  { label: '文件修改', value: 'file_modify' },
  { label: '持久化注册', value: 'persistence_register' },
  { label: 'WMI订阅', value: 'wmi_subscribe' },
  { label: '行为告警', value: 'behavior_alert' },
  { label: 'IOC命中', value: 'ioc_match' },
  { label: '用户登录', value: 'user_login' },
  { label: '用户登出', value: 'user_logout' },
  { label: 'DNS查询', value: 'dns_query' },
  { label: '模块加载', value: 'module_load' },
  { label: '计划任务', value: 'scheduled_task' },
  { label: '服务操作', value: 'service_operation' },
  { label: '管道连接', value: 'pipe_connect' },
  { label: '驱动加载', value: 'driver_load' },
]

const quickTags = [
  { key: 'high-unhandled', label: '高危未处理', filters: { severities: ['critical', 'high'], statuses: ['pending'] } },
  { key: 'today-new', label: '今日新增', filters: { quickTag: 'today' } },
  { key: 'ioc-hit', label: 'IOC命中', filters: { eventTypes: ['ioc_match'] } },
  { key: 'my-events', label: '我的事件', filters: { quickTag: 'mine' } },
]

const activeQuickTag = ref('')
const localFilters = reactive({
  keyword: '',
  timeRange: [null, null],
  eventTypes: [],
  severities: [],
  statuses: [],
  attackStages: [],
  quickTag: '',
})

// 从 props 同步到 local（仅初始化）
watch(() => props.filters, (val) => {
  Object.assign(localFilters, val)
}, { immediate: true, deep: true })

let changeTimer = null

function onFilterChange() {
  clearTimeout(changeTimer)
  activeQuickTag.value = ''
  changeTimer = setTimeout(() => {
    emit('update:filters', { ...localFilters })
  }, 500)
}

function applyQuickTag(tag) {
  activeQuickTag.value = tag.key
  if (tag.filters) {
    Object.assign(localFilters, {
      keyword: '',
      timeRange: [null, null],
      eventTypes: [],
      severities: [],
      statuses: [],
      attackStages: [],
      quickTag: tag.key,
    })
    if (tag.filters.severities) localFilters.severities = [...tag.filters.severities]
    if (tag.filters.statuses) localFilters.statuses = [...tag.filters.statuses]
    if (tag.filters.eventTypes) localFilters.eventTypes = [...tag.filters.eventTypes]
    if (tag.filters.quickTag) localFilters.quickTag = tag.filters.quickTag
  }
  emit('update:filters', { ...localFilters })
}

function onReset() {
  Object.assign(localFilters, {
    keyword: '',
    timeRange: [null, null],
    eventTypes: [],
    severities: [],
    statuses: [],
    attackStages: [],
    quickTag: '',
  })
  activeQuickTag.value = ''
  emit('reset')
}
</script>

<style scoped>
.smart-search-bar {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  flex-wrap: wrap;
}

.filter-search {
  width: 200px;
}

.filter-date {
  width: 260px;
}

.filter-select {
  width: 160px;
}

.quick-tag {
  cursor: pointer;
  margin: 0 2px;
}
</style>
