<template>
  <div class="panel">
    <div class="panel-header">结构化时间线</div>
    <div class="summary">{{ timeline.timeline_summary || timeline.attack_chain || '暂无时间线摘要' }}</div>
    <el-timeline v-if="events.length" class="timeline-list">
      <el-timeline-item
        v-for="(event, index) in events"
        :key="index"
        :timestamp="event.timestamp || '-'"
        placement="top"
      >
        <div class="event-title">{{ event.event }}</div>
        <div class="event-meta">阶段：{{ event.phase || '待确认' }}</div>
        <div v-if="event.significance" class="event-meta">说明：{{ event.significance }}</div>
      </el-timeline-item>
    </el-timeline>
  </div>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  timeline: { type: Object, default: () => ({}) },
})

const events = computed(() => props.timeline?.key_events || [])
</script>

<style scoped>
.panel { padding: 14px; border: 1px solid #ebeef5; border-radius: 8px; background: #fff; }
.panel-header { font-size: 14px; font-weight: 600; margin-bottom: 10px; }
.summary { font-size: 13px; color: #606266; line-height: 1.7; margin-bottom: 10px; }
.timeline-list { padding-left: 4px; }
.event-title { font-size: 13px; font-weight: 600; color: #303133; }
.event-meta { margin-top: 4px; font-size: 12px; color: #909399; }
</style>
