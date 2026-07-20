<template>
  <div class="rule-condition-editor">
    <div class="rce-type">
      <label class="rce-label">规则类型</label>
      <el-select v-model="localType" size="small" @change="onTypeChange">
        <el-option v-for="t in ruleTypes" :key="t.value" :label="t.label" :value="t.value" />
      </el-select>
    </div>

    <!-- regex：字段 + 正则 -->
    <template v-if="localType === 'regex'">
      <div class="rce-field">
        <label class="rce-label">匹配字段</label>
        <el-input v-model="localCond.field" size="small" placeholder="evidence.process_name" />
      </div>
      <div class="rce-field">
        <label class="rce-label">正则模式</label>
        <el-input v-model="localCond.pattern" size="small" placeholder=".*malware.*" />
      </div>
    </template>

    <!-- list：字段 + 值列表 -->
    <template v-else-if="localType === 'list'">
      <div class="rce-field">
        <label class="rce-label">匹配字段</label>
        <el-input v-model="localCond.field" size="small" placeholder="severity" />
      </div>
      <div class="rce-field">
        <label class="rce-label">匹配值</label>
        <el-select v-model="localCond.values" multiple size="small" placeholder="选择值">
          <el-option v-for="v in ['critical','high','medium','low','info']" :key="v" :label="v" :value="v" />
        </el-select>
      </div>
    </template>

    <!-- threshold：字段 + 比较符 + 阈值 -->
    <template v-else-if="localType === 'threshold'">
      <div class="rce-field">
        <label class="rce-label">计数字段</label>
        <el-input v-model="localCond.field" size="small" placeholder="count" />
      </div>
      <div class="rce-row">
        <el-select v-model="localCond.operator" size="small" style="width:100px">
          <el-option label=">=" value=">=" />
          <el-option label=">" value=">" />
          <el-option label="=" value="=" />
          <el-option label="<" value="<" />
          <el-option label="<=" value="<=" />
        </el-select>
        <el-input-number v-model="localCond.value" :min="0" size="small" style="width:120px" />
      </div>
    </template>

    <!-- behavior + composite + exists + attack_chain：JSON 编辑 -->
    <template v-else>
      <div class="rce-field">
        <label class="rce-label">条件 (JSON)</label>
        <el-input
          v-model="localCondRaw"
          type="textarea"
          :rows="6"
          size="small"
          placeholder='{"field": "process_name", "pattern": ".*"}'
        />
      </div>
    </template>

    <div class="rce-error" v-if="errorMsg">{{ errorMsg }}</div>
  </div>
</template>

<script setup>
import { ref, watch, computed } from 'vue'

const props = defineProps({
  modelValue: { type: Object, default: () => ({}) },
  ruleType: { type: String, default: 'regex' },
})

const emit = defineEmits(['update:modelValue', 'update:ruleType'])

const ruleTypes = [
  { value: 'regex', label: '正则匹配' },
  { value: 'list', label: '列表匹配' },
  { value: 'threshold', label: '阈值匹配' },
  { value: 'behavior', label: '行为检测' },
  { value: 'composite', label: '复合条件' },
  { value: 'exists', label: '字段存在' },
  { value: 'attack_chain', label: '攻击链' },
]

const localType = ref(props.ruleType)
const localCond = ref({ ...props.modelValue })
const localCondRaw = ref(JSON.stringify(props.modelValue, null, 2))
const errorMsg = ref('')

watch(() => props.modelValue, (v) => {
  localCond.value = { ...v }
  localCondRaw.value = JSON.stringify(v, null, 2)
})

watch(localCond, (v) => {
  localCondRaw.value = JSON.stringify(v, null, 2)
  emit('update:modelValue', v)
}, { deep: true })

function onTypeChange() {
  localCond.value = {}
  localCondRaw.value = '{}'
  emit('update:ruleType', localType.value)
  emit('update:modelValue', localCond.value)
}
</script>

<style scoped>
.rule-condition-editor { padding: 8px 0; }
.rce-label { display: block; font-size: 12px; color: var(--color-fg-subtle); margin: 8px 0 4px; }
.rce-field { margin-bottom: 8px; }
.rce-row { display: flex; gap: 8px; align-items: center; margin-bottom: 8px; }
.rce-error { color: #dc2626; font-size: 11px; margin-top: 4px; }
</style>
