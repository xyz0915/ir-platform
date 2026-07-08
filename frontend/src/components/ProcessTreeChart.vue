<template>
  <div class="process-tree-chart">
    <v-chart
      :option="chartOption"
      autoresize
      style="height: 500px; width: 100%"
      @click="handleClick"
    />
  </div>
</template>

<script setup>
import { computed } from 'vue'
import VChart from 'vue-echarts'
import { use } from 'echarts/core'
import { TreeChart } from 'echarts/charts'
import { TooltipComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'

use([TreeChart, TooltipComponent, CanvasRenderer])

const props = defineProps({
  treeData: { type: Object, default: () => ({}) },
  abnormalPids: { type: Array, default: () => [] }
})

const emit = defineEmits(['node-click'])

const abnormalPidsSet = computed(() => new Set(props.abnormalPids))

/** 将后端 tree JSON 转为 ECharts data 格式（递归转换） */
function convertToEChartsData(node) {
  if (!node) return null
  const isAbnormal = node.is_abnormal || abnormalPidsSet.value.has(node.pid)

  const echartsNode = {
    name: node.name || 'unknown',
    value: node.pid,
    itemStyle: {
      color: isAbnormal ? '#F56C6C' : '#909399'
    },
    symbolSize: isAbnormal ? 20 : 12,
    label: {
      show: true,
      fontSize: isAbnormal ? 13 : 11,
      color: isAbnormal ? '#F56C6C' : '#606266',
      fontWeight: isAbnormal ? 'bold' : 'normal'
    },
    // 存储原始数据供点击事件使用
    _rawData: {
      pid: node.pid,
      process_name: node.process_name,
      process_path: node.process_path,
      command_line: node.command_line,
      is_abnormal: node.is_abnormal,
      risk_score: node.risk_score,
      matched_rules: node.matched_rules,
      attack_path: node.attack_path
    }
  }

  if (node.children && node.children.length > 0) {
    echartsNode.children = node.children.map(child => convertToEChartsData(child))
  }

  return echartsNode
}

const chartOption = computed(() => {
  const data = convertToEChartsData(props.treeData)
  return {
    tooltip: {
      trigger: 'item',
      formatter(params) {
        const raw = params.data._rawData || {}
        let html = `<strong>${raw.process_name || params.name}</strong><br/>`
        html += `PID: ${raw.pid || 'N/A'}<br/>`
        if (raw.process_path) html += `路径: ${raw.process_path}<br/>`
        if (raw.command_line) html += `命令行: ${raw.command_line.substring(0, 80)}<br/>`
        if (raw.is_abnormal) {
          html += `<span style="color:#F56C6C">异常进程</span><br/>`
          html += `风险评分: ${raw.risk_score || 0}<br/>`
          if (raw.attack_path) html += `攻击路径: ${raw.attack_path}<br/>`
        }
        return html
      }
    },
    series: [
      {
        type: 'tree',
        data: data ? [data] : [],
        orient: 'LR',
        layout: 'orthogonal',
        symbol: 'circle',
        symbolSize: 14,
        initialTreeDepth: -1,
        roam: true,
        label: {
          position: 'left',
          verticalAlign: 'middle',
          align: 'right'
        },
        leaves: {
          label: {
            position: 'right',
            verticalAlign: 'middle',
            align: 'left'
          }
        },
        emphasis: {
          focus: 'descendant'
        },
        expandAndCollapse: true,
        animationDuration: 550,
        animationDurationUpdate: 750
      }
    ]
  }
})

function handleClick(params) {
  const rawData = params.data?._rawData
  if (rawData) {
    emit('node-click', rawData)
  }
}
</script>

<style scoped>
.process-tree-chart {
  width: 100%;
  min-height: 500px;
}
</style>
