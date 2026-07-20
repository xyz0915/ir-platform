<template>
  <div class="rule-card-overlay" @click.self="$emit('close')">
    <div class="rule-card">
      <div class="rc-header">
        <div class="rc-title-row">
          <span class="severity-badge" :class="'badge-' + (rule.severity || 'info')">{{ rule.severity }}</span>
          <strong class="rc-name">{{ rule.name }}</strong>
          <span class="rc-version">v{{ rule.version || 1 }}</span>
        </div>
        <button class="rc-close" @click="$emit('close')">×</button>
      </div>

      <div class="rc-body">
        <!-- 基本信息 -->
        <div class="rc-section">
          <div class="rc-section-title">基本信息</div>
          <div class="rc-grid">
            <div><span class="rc-label">类别</span><span>{{ rule.category || '—' }}</span></div>
            <div><span class="rc-label">类型</span><span>{{ rule.rule_type || '—' }}</span></div>
            <div><span class="rc-label">来源</span><span>{{ rule.source || 'default' }}</span></div>
            <div><span class="rc-label">ATT&CK</span><span>{{ rule.mitre_attack || '—' }}</span></div>
            <div><span class="rc-label">状态</span><span>{{ rule.enabled ? '已启用' : '已禁用' }}</span></div>
            <div><span class="rc-label">标签</span><span>{{ rule.label || '—' }}</span></div>
          </div>
        </div>

        <!-- 条件原文 -->
        <div class="rc-section">
          <div class="rc-section-title">条件原文</div>
          <pre class="rc-code">{{ formatCond(rule.condition) }}</pre>
        </div>

        <!-- 命中统计 -->
        <div class="rc-section" v-if="rule.hit_count !== undefined">
          <div class="rc-section-title">命中统计</div>
          <div class="rc-stats">
            <div class="rc-stat"><span class="rc-stat-num">{{ rule.hit_count || 0 }}</span><span class="rc-stat-lbl">总命中</span></div>
            <div class="rc-stat"><span class="rc-stat-num">{{ rule.false_positive_rate || 0 }}%</span><span class="rc-stat-lbl">误报率</span></div>
          </div>
        </div>

        <!-- 描述 -->
        <div class="rc-section" v-if="rule.description">
          <div class="rc-section-title">描述</div>
          <p class="rc-desc">{{ rule.description }}</p>
        </div>

        <!-- 操作按钮 -->
        <div class="rc-actions">
          <button class="btn btn-sm btn-primary" @click="$emit('edit', rule)">编辑</button>
          <button class="btn btn-sm" :class="rule.enabled ? 'btn-warning' : 'btn-success'"
                  @click="$emit('toggle', rule)">{{ rule.enabled ? '禁用' : '启用' }}</button>
          <button class="btn btn-sm btn-danger" @click="$emit('delete', rule)">删除</button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
defineProps({ rule: { type: Object, default: () => ({}) } })
defineEmits(['close', 'edit', 'toggle', 'delete'])

function formatCond(cond) {
  if (!cond) return '{}'
  return typeof cond === 'string' ? cond : JSON.stringify(cond, null, 2)
}
</script>

<style scoped>
.rule-card-overlay {
  position: fixed; inset: 0; z-index: 1000;
  background: rgba(0,0,0,0.3);
  display: flex; justify-content: flex-end;
}
.rule-card {
  width: 520px; height: 100vh; overflow-y: auto;
  background: var(--color-canvas-default, #fff);
  border-left: 1px solid var(--color-border-default);
  padding: 16px;
}
.rc-header { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 16px; }
.rc-title-row { display: flex; align-items: center; gap: 8px; }
.rc-name { font-size: 15px; }
.rc-version { font-size: 11px; color: var(--color-fg-subtle); background: var(--color-canvas-subtle); padding: 1px 6px; border-radius: 3px; }
.rc-close { background: none; border: none; font-size: 20px; cursor: pointer; color: var(--color-fg-subtle); }
.rc-section { margin-bottom: 16px; }
.rc-section-title { font-size: 12px; font-weight: 600; color: var(--color-fg-subtle); margin-bottom: 8px; border-bottom: 0.5px solid var(--color-border-default); padding-bottom: 4px; }
.rc-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 6px 16px; font-size: 12px; }
.rc-label { display: inline-block; width: 60px; color: var(--color-fg-subtle); }
.rc-code { background: var(--color-canvas-subtle); padding: 8px; border-radius: 4px; font-size: 11px; overflow-x: auto; white-space: pre-wrap; }
.rc-stats { display: flex; gap: 24px; }
.rc-stat { text-align: center; }
.rc-stat-num { display: block; font-size: 20px; font-weight: 700; }
.rc-stat-lbl { font-size: 11px; color: var(--color-fg-subtle); }
.rc-desc { font-size: 12px; line-height: 1.6; color: var(--color-fg-default); }
.rc-actions { display: flex; gap: 8px; margin-top: 16px; padding-top: 12px; border-top: 0.5px solid var(--color-border-default); }
</style>
