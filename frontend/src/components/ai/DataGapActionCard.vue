<template>
  <div class="data-gap-card">
    <div class="dg-title">数据缺口即动作 (data_gaps)</div>
    <el-empty v-if="!dataGaps.length" description="无数据缺口" :image-size="48" />

    <div v-for="(gap, gi) in dataGaps" :key="gi" class="dg-gap">
      <div class="dg-gap-head">
        <el-tag :type="sevType(gap.severity)" size="small" effect="plain">{{ gap.severity }}</el-tag>
        <el-tag size="small" :type="gapType(gap.category)" effect="plain" class="dg-type-tag">{{ gap.category }}</el-tag>
        <span class="dg-gap-title">{{ gap.title }}</span>
      </div>
      <div class="dg-gap-desc">{{ gap.description }}</div>
      <div class="dg-gap-foot">
        <el-popconfirm
          title="确认下发补采任务？"
          confirm-button-text="确定"
          cancel-button-text="取消"
          @confirm="dispatchGap(gap)"
        >
          <template #reference>
            <el-button size="small" type="primary" :loading="dispatching === 'gap-' + gi">
              一键补采
            </el-button>
          </template>
        </el-popconfirm>
        <span class="dg-gap-hint">自动采集缺失数据，完成后可刷新查看</span>
      </div>

      <div v-for="(act, ai) in (gap.recommended_actions || [])" :key="ai" class="dg-action">
        <div class="dg-act-row">
          <el-tag size="mini" effect="plain">{{ act.priority }}</el-tag>
          <span class="dg-act-type">{{ act.action_type }}</span>
          <span class="dg-act-target">{{ act.target }}</span>
        </div>
        <div v-if="act.command_or_api" class="dg-cmd">{{ act.command_or_api }}</div>
        <div class="dg-act-foot">
          <el-button size="small" text type="primary" @click="copyCmd(act.command_or_api)">复制命令</el-button>
          <el-button
            v-if="act.auto_runnable"
            size="small"
            type="warning"
            :loading="dispatching === actKey(gi, ai)"
            @click="dispatch(gap, act)"
          >派发只读采集</el-button>
          <el-tag v-else size="mini" type="info">需人工执行</el-tag>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { ElMessage } from 'element-plus'
import { dispatchReadonly } from '../../api/dispatch'

const props = defineProps({
  dataGaps: { type: Array, default: () => [] },
  hostId: { type: Number, required: true },
})

const emit = defineEmits(['dispatched'])

const dispatching = ref('')

function actKey(gi, ai) {
  return `${gi}-${ai}`
}

function sevType(s) {
  const m = { high: 'danger', critical: 'danger', medium: 'warning', low: 'success' }
  return m[s] || 'info'
}

function gapType(cat) {
  const m = { network_analysis: 'warning', ioc: 'danger', process: 'primary', registry: 'success' }
  return m[cat] || 'info'
}

/**
 * 一键补采：派发该缺口下所有 auto_runnable 的动作
 */
async function dispatchGap(gap) {
  const gi = props.dataGaps.indexOf(gap)
  dispatching.value = 'gap-' + gi
  let dispatchedCount = 0
  try {
    for (const act of (gap.recommended_actions || [])) {
      if (!act.auto_runnable) continue
      await dispatchReadonly(props.hostId, {
        action_type: act.action_type,
        target: act.target,
        command_or_api: act.command_or_api,
        auto_runnable: true,
      })
      dispatchedCount++
    }
    ElMessage.success(`补采任务已下发 (${dispatchedCount}项)，请稍后刷新查看`)
    emit('dispatched', { taskId: null, gap, count: dispatchedCount })
  } catch (e) {
    ElMessage.error(e?.response?.data?.message || e?.message || '补采派发失败')
  } finally {
    dispatching.value = ''
  }
}

async function copyCmd(cmd) {
  if (!cmd) return
  try {
    await navigator.clipboard.writeText(cmd)
    ElMessage.success('命令已复制')
  } catch {
    ElMessage.warning('复制失败，请手动选择')
  }
}

async function dispatch(gap, act) {
  const key = actKey(props.dataGaps.indexOf(gap), (gap.recommended_actions || []).indexOf(act))
  dispatching.value = key
  try {
    const resp = await dispatchReadonly(props.hostId, {
      action_type: act.action_type,
      target: act.target,
      command_or_api: act.command_or_api,
      auto_runnable: true,
    })
    const data = resp.data?.data || {}
    ElMessage.success(`已派发只读采集，task_id=${data.task_id}`)
    emit('dispatched', { taskId: data.task_id, action: act })
  } catch (e) {
    ElMessage.error(e?.response?.data?.message || e?.message || '派发失败')
  } finally {
    dispatching.value = ''
  }
}
</script>

<style scoped>
.data-gap-card { border: 1px solid var(--el-border-color); border-radius: 8px; padding: 12px 14px; }
.dg-title { font-weight: 600; font-size: 15px; margin-bottom: 8px; }
.dg-gap { border-top: 1px dashed var(--el-border-color); padding: 8px 0; }
.dg-gap-head { display: flex; align-items: center; gap: 8px; }
.dg-gap-title { font-weight: 600; }
.dg-gap-cat { margin-left: auto; color: #999; font-size: 12px; }
.dg-gap-desc { color: #666; font-size: 13px; margin: 4px 0 6px; }
.dg-gap-foot { display: flex; align-items: center; gap: 8px; margin: 6px 0 8px; }
.dg-gap-hint { font-size: 11px; color: #999; }
.dg-type-tag { font-size: 10px !important; }
.dg-action { background: #fafafa; border-radius: 6px; padding: 8px; margin-bottom: 6px; }
.dg-act-row { display: flex; align-items: center; gap: 6px; }
.dg-act-type { font-weight: 600; font-size: 13px; }
.dg-act-target { color: #888; font-size: 12px; }
.dg-cmd { font-family: monospace; font-size: 12px; background: #fff; border: 1px solid var(--el-border-color); border-radius: 4px; padding: 4px 6px; margin: 6px 0; word-break: break-all; }
.dg-act-foot { display: flex; align-items: center; gap: 8px; }
</style>
