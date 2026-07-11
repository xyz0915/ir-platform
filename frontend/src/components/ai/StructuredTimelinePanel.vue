<template>
  <div class="panel">
    <div class="panel-header">结构化时间线</div>
    <div class="summary">{{ timeline.timeline_summary || timeline.attack_chain || '暂无时间线摘要' }}</div>
    <el-timeline v-if="groupedEvents.length" class="timeline-list">
      <template v-for="(group, gIdx) in groupedEvents" :key="'g-' + gIdx">
        <!-- 阶段分隔线 -->
        <el-divider
          v-if="group.phase"
          content-position="left"
          class="phase-divider"
        >
          {{ group.phase }}
        </el-divider>

        <el-timeline-item
          v-for="(event, eIdx) in group.events"
          :key="'e-' + gIdx + '-' + eIdx"
          :timestamp="event.timestamp || '-'"
          placement="top"
          :color="getSeverityColor(event.severity)"
        >
          <div class="event-title">
            <el-icon class="event-type-icon"><component :is="getEventIcon(event.event_type || event.phase)" /></el-icon>
            {{ event.event }}
            <el-button
              v-if="event.source_event_id"
              type="primary"
              link
              size="small"
              class="jump-btn"
              @click="$emit('jump-to-event', event.source_event_id)"
            >
              <el-icon><Link /></el-icon>
            </el-button>
          </div>
          <div class="event-meta">
            阶段：{{ event.phase || '待确认' }}
            <el-tag
              v-if="event.severity"
              :color="getSeverityColor(event.severity)"
              size="small"
              effect="dark"
              class="severity-tag"
            >
              {{ getSeverityLabel(event.severity) }}
            </el-tag>
          </div>
          <div v-if="event.significance" class="event-meta">
            <el-collapse class="significance-collapse">
              <el-collapse-item title="说明">
                <span class="significance-text">{{ event.significance }}</span>
              </el-collapse-item>
            </el-collapse>
          </div>
        </el-timeline-item>
      </template>
    </el-timeline>
    <div v-else class="empty-hint">暂无时间线事件</div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { Link } from '@element-plus/icons-vue'
import { SEVERITY, EVENT_TYPE } from '@/constants/design-tokens.js'

const props = defineProps({
  timeline: { type: Object, default: () => ({}) },
})

defineEmits(['jump-to-event'])

const events = computed(() => props.timeline?.key_events || [])

/**
 * 按 phase 字段分组：连续同 phase 事件归为一组
 */
const groupedEvents = computed(() => {
  const raw = events.value
  if (raw.length === 0) return []

  const groups = []
  let currentGroup = { phase: raw[0].phase || '', events: [] }

  for (const evt of raw) {
    const phase = evt.phase || ''
    if (phase !== currentGroup.phase) {
      if (currentGroup.events.length > 0) {
        groups.push({ ...currentGroup })
      }
      currentGroup = { phase: phase, events: [] }
    }
    currentGroup.events.push(evt)
  }
  if (currentGroup.events.length > 0) {
    groups.push(currentGroup)
  }

  return groups
})

/**
 * 根据 severity 获取颜色
 */
function getSeverityColor(severity) {
  return SEVERITY.COLOR[severity] || SEVERITY.COLOR.info
}

/**
 * 根据 severity 获取标签
 */
function getSeverityLabel(severity) {
  return SEVERITY.LABEL[severity] || severity || '未知'
}

/**
 * 根据事件类型获取图标组件名
 */
function getEventIcon(eventType) {
  const iconName = EVENT_TYPE.ICON[eventType] || EVENT_TYPE.ICON.other
  return iconName
}
</script>

<style scoped>
.panel { padding: 14px; border: 1px solid #ebeef5; border-radius: 8px; background: #fff; }
.panel-header { font-size: 14px; font-weight: 600; margin-bottom: 10px; }
.summary { font-size: 13px; color: #606266; line-height: 1.7; margin-bottom: 10px; }
.timeline-list { padding-left: 4px; }
.event-title { font-size: 13px; font-weight: 600; color: #303133; display: flex; align-items: center; gap: 6px; }
.event-type-icon { font-size: 14px; flex-shrink: 0; }
.jump-btn { padding: 0; margin-left: 4px; }
.event-meta { margin-top: 4px; font-size: 12px; color: #909399; display: flex; align-items: center; gap: 6px; }
.severity-tag { font-size: 10px; }
.phase-divider { margin: 12px 0; }
.phase-divider :deep(.el-divider__text) {
  font-size: 13px;
  font-weight: 600;
  color: #606266;
  background-color: #fff;
}
.significance-collapse { margin-top: 4px; }
.significance-collapse :deep(.el-collapse-item__header) {
  font-size: 12px;
  color: #909399;
  line-height: 24px;
  height: 24px;
}
.significance-text { font-size: 12px; color: #606266; line-height: 1.6; }
.empty-hint { text-align: center; color: #909399; padding: 20px; font-size: 13px; }
</style>
