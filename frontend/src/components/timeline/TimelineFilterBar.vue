<template>
  <el-form inline class="timeline-filter-bar">
    <el-form-item label="时间范围">
      <el-date-picker
        v-model="dateRange"
        type="datetimerange"
        range-separator="至"
        start-placeholder="开始时间"
        end-placeholder="结束时间"
        format="YYYY-MM-DD HH:mm:ss"
        value-format="YYYY-MM-DDTHH:mm:ss"
        :clearable="true"
        @change="emitFilter"
      />
    </el-form-item>

    <el-form-item label="事件类型">
      <el-select
        v-model="selectedEventTypes"
        multiple
        clearable
        placeholder="全部类型"
        collapse-tags
        collapse-tags-tooltip
        style="width: 200px"
        @change="emitFilter"
      >
        <el-option
          v-for="de in eventTypeOptions"
          :key="de.value"
          :label="de.label"
          :value="de.value"
        />
      </el-select>
    </el-form-item>

    <el-form-item label="严重度">
      <el-select
        v-model="selectedSeverities"
        multiple
        clearable
        placeholder="全部严重度"
        collapse-tags
        collapse-tags-tooltip
        style="width: 180px"
        @change="emitFilter"
      >
        <el-option
          v-for="sev in severityOptions"
          :key="sev.value"
          :label="sev.label"
          :value="sev.value"
        />
      </el-select>
    </el-form-item>

    <el-form-item>
      <el-button @click="emitFilter">筛选</el-button>
      <el-button @click="resetFilter">重置</el-button>
    </el-form-item>
  </el-form>
</template>

<script setup>
import { ref } from 'vue'
import { SEVERITY, EVENT_TYPE } from '@/constants/design-tokens.js'

const props = defineProps({
  hostId: { type: [Number, String], required: true },
})

const emit = defineEmits(['filter-change'])

const dateRange = ref(null)
const selectedEventTypes = ref([])
const selectedSeverities = ref([])

const eventTypeOptions = Object.entries(EVENT_TYPE.LABEL).map(([value, label]) => ({
  value, label,
}))

const severityOptions = Object.entries(SEVERITY.LABEL)
  .filter(([key]) => key !== 'critical')
  .map(([value, label]) => ({ value, label }))

function emitFilter() {
  const range = dateRange.value
  emit('filter-change', {
    start: range ? range[0] : null,
    end: range ? range[1] : null,
    eventTypes: selectedEventTypes.value,
    severities: selectedSeverities.value,
  })
}

function resetFilter() {
  dateRange.value = null
  selectedEventTypes.value = []
  selectedSeverities.value = []
  emitFilter()
}
</script>

<style scoped>
.timeline-filter-bar {
  margin-bottom: 6px;
  padding: 0;
  background: transparent;
  border: none;
  border-radius: 0;
}
</style>
