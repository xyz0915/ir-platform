<template>
  <div class="attack-chain-container">
    <el-collapse v-model="activeCollapse" class="dag-collapse">
      <el-collapse-item title="攻击链 DAG" name="dag">
        <div v-if="hasChain" ref="chartRef" class="dag-chart"></div>
        <div v-else class="dag-empty">暂无攻击链数据</div>
      </el-collapse-item>
    </el-collapse>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted, watch, nextTick } from 'vue'
import * as echarts from 'echarts'
import { EVENT_TYPE } from '@/constants/design-tokens.js'

const props = defineProps({
  attackChain: { type: String, default: '' },
})

const chartRef = ref(null)
let chart = null
const activeCollapse = ref(['dag'])

const hasChain = computed(() => {
  return props.attackChain && props.attackChain.trim().length > 0
})

onMounted(() => {
  if (hasChain.value) {
    nextTick(() => initChart())
  }
})

onUnmounted(() => {
  if (chart) chart.dispose()
})

watch(() => props.attackChain, (val) => {
  if (val && val.trim()) {
    nextTick(() => initChart())
  }
})

function parseChainText(text) {
  // 尝试从文本中提取节点和边
  // 期望格式: "A -> B -> C" 或 "步骤1(process): 描述 -> 步骤2(network): 描述"
  if (!text) return { nodes: [], edges: [] }

  const nodes = []
  const edges = []
  const seen = new Set()

  // 按 -> 分割
  const segments = text.split('->').map(s => s.trim()).filter(Boolean)
  if (segments.length < 2) {
    // 尝试按行分割
    const lines = text.split('\n').filter(l => l.trim())
    if (lines.length > 0) {
      nodes.push({
        name: '事件序列',
        symbolSize: 28,
        itemStyle: { color: EVENT_TYPE.COLOR.process },
      })
      lines.forEach((line, i) => {
        const nodeName = line.substring(0, 30)
        if (!seen.has(nodeName)) {
          seen.add(nodeName)
          nodes.push({
            name: nodeName,
            symbolSize: 14,
            itemStyle: { color: Object.values(EVENT_TYPE.COLOR)[i % 7] },
          })
          if (nodes.length > 1) {
            edges.push({ source: nodes[nodes.length - 2].name, target: nodeName })
          }
        }
      })
      return { nodes, edges }
    }
    return { nodes, edges }
  }

  segments.forEach((seg, i) => {
    // 提取: "event_type: description"
    const match = seg.match(/^(\w+):\s*(.+)/)
    let nodeName = seg.substring(0, 30)
    let nodeColor = EVENT_TYPE.COLOR.other
    if (match) {
      const etype = match[1].toLowerCase()
      nodeName = match[2].substring(0, 25)
      nodeColor = EVENT_TYPE.COLOR[etype] || EVENT_TYPE.COLOR.other
    }
    if (!seen.has(nodeName)) {
      seen.add(nodeName)
      nodes.push({
        name: nodeName,
        symbolSize: 20,
        itemStyle: { color: nodeColor },
      })
    }
  })

  // 构建边
  for (let i = 1; i < nodes.length; i++) {
    edges.push({
      source: nodes[i - 1].name,
      target: nodes[i].name,
    })
  }

  return { nodes, edges }
}

function initChart() {
  if (!chartRef.value) return
  if (!chart) {
    chart = echarts.init(chartRef.value)
  }

  const { nodes, edges } = parseChainText(props.attackChain)

  if (nodes.length === 0) {
    chart.setOption({
      title: { text: '暂无攻击链数据', left: 'center', top: 'center', textStyle: { color: '#999', fontSize: 14 } },
    }, true)
    return
  }

  const option = {
    tooltip: {
      trigger: 'item',
      formatter: function (params) {
        if (params.dataType === 'edge') {
          return `${params.data.source} → ${params.data.target}`
        }
        return params.name
      },
    },
    series: [{
      type: 'graph',
      layout: 'force',
      roam: true,
      draggable: true,
      force: {
        repulsion: 200,
        edgeLength: 150,
      },
      data: nodes,
      edges: edges.map(e => ({
        source: e.source,
        target: e.target,
        lineStyle: { color: '#909399', curveness: 0.1 },
      })),
      label: {
        show: true,
        fontSize: 10,
        formatter: (p) => p.name,
      },
      lineStyle: {
        color: 'source',
        curveness: 0.1,
      },
      emphasis: {
        focus: 'adjacency',
        lineStyle: { width: 3 },
      },
    }],
  }

  chart.setOption(option, true)
}
</script>

<style scoped>
.attack-chain-container {
  margin-top: 16px;
}
.dag-collapse {
  border: 1px solid #ebeef5;
  border-radius: 8px;
}
.dag-chart {
  width: 100%;
  height: 400px;
}
.dag-empty {
  text-align: center;
  color: #c0c4cc;
  padding: 40px 0;
  font-size: 13px;
}
</style>
