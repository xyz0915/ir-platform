<template>
  <div class="panel">
    <div class="panel-header">结构化时间线</div>
    <div class="summary">{{ timeline.timeline_summary || timeline.attack_chain || '暂无时间线摘要' }}</div>

    <!-- 攻击进度条 -->
    <div v-if="stageProgress.used > 0" class="attack-progress">
      <span class="attack-progress-label">攻击进度: {{ stageProgress.used }}/{{ stageProgress.total }} 阶段</span>
      <el-progress
        :percentage="stageProgress.pct"
        :stroke-width="6"
        :show-text="false"
        status="warning"
        class="attack-progress-bar"
      />
    </div>

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
          :color="getStageColor(event.phase)"
        >
          <div class="event-title">
            <span class="stage-dot" :style="{ background: getStageColor(event.phase) }"></span>
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
            <el-tag
              size="small"
              :style="{ background: getStageColor(event.phase), color: '#fff', border: 'none' }"
              class="phase-tag"
            >
              {{ event.phase || '待确认' }}
            </el-tag>
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

const STAGE_COLORS = {
  '待确认': '#d3d1c7',
  '初始访问': '#534ab7',
  '执行': '#d85a30',
  '持久化': '#1d9e75',
  '权限提升': '#d85a30',
  '防御规避': '#e24b4a',
  '凭据访问': '#ef9f27',
  '发现': '#378add',
  '横向移动': '#185fa5',
  '收集': '#378add',
  '命令与控制': '#854f0b',
  '数据渗出': '#a32d2d',
  '影响': '#e24b4a',
}

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
 * 根据阶段获取颜色
 */
function getStageColor(phase) {
  return STAGE_COLORS[phase] || STAGE_COLORS['待确认']
}

/**
 * 攻击进度计算
 */
const stageProgress = computed(() => {
  const allPhases = Object.keys(STAGE_COLORS).filter((p) => p !== '待确认')
  const usedPhases = new Set()
  for (const evt of events.value) {
    if (evt.phase) usedPhases.add(evt.phase)
  }
  const used = usedPhases.size
  const total = allPhases.length
  return {
    used,
    total,
    pct: total > 0 ? Math.min(100, Math.round((used / total) * 100)) : 0,
  }
})

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
.stage-dot { width: 10px; height: 10px; border-radius: 50%; flex-shrink: 0; display: inline-block; }
.event-type-icon { font-size: 14px; flex-shrink: 0; }
.jump-btn { padding: 0; margin-left: 4px; }
.event-meta { margin-top: 4px; font-size: 12px; color: #909399; display: flex; align-items: center; gap: 6px; }
.phase-tag { font-size: 10px !important; height: 20px !important; line-height: 20px !important; padding: 0 6px !important; border-radius: 3px; }
.severity-tag { font-size: 10px; }
.attack-progress { display: flex; align-items: center; gap: 10px; margin-bottom: 12px; padding: 8px 12px; background: #f9fafb; border-radius: 6px; border: 1px solid #ebeef5; }
.attack-progress-label { font-size: 12px; color: #606266; white-space: nowrap; flex-shrink: 0; }
.attack-progress-bar { flex: 1; }
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
