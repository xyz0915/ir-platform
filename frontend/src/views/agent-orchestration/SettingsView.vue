<template>
  <div class="settings-view">
    <!-- 顶部 -->
    <div class="sv-toolbar">
      <div class="sv-title">
        <h2>编排设置</h2>
        <span class="sv-sub">多模型 profile / 无状态部署 / 协议状态（Mock 适配层，F10/F14）</span>
      </div>
      <el-button @click="store.refreshAll" :loading="store.loading">刷新</el-button>
    </div>

    <div class="sv-body">
      <!-- 左：多模型 profile -->
      <div class="sv-main">
        <h3 class="sv-section">多模型 Profile ({{ store.enabledProfiles }}/{{ store.modelProfiles.length }} 启用)</h3>
        <div class="sv-mp-list">
          <div v-for="p in store.modelProfiles" :key="p.profile_id" class="sv-mp-card">
            <div class="sv-mp-head">
              <span class="sv-mp-name">{{ p.name }}</span>
              <el-tag :type="p.enabled ? 'success' : 'info'" size="small" effect="light">
                {{ p.enabled ? '启用' : '停用' }}
              </el-tag>
            </div>
            <div class="sv-mp-meta">
              <div><span class="mi-label">厂商</span><span class="mi-value">{{ p.provider }}</span></div>
              <div><span class="mi-label">模型</span><span class="mi-value gv-mono">{{ p.model }}</span></div>
            </div>
            <div class="sv-mp-id gv-mono">{{ p.profile_id }}</div>
          </div>
        </div>
      </div>

      <!-- 右：部署配置 -->
      <div class="sv-side" v-if="store.deploymentConfig">
        <h3 class="sv-section">部署配置</h3>
        <el-card class="sv-config-card" shadow="never">
          <div class="sv-config-row">
            <span class="sc-label">无状态部署 (F14)</span>
            <el-tag :type="store.deploymentConfig.stateless_enabled ? 'success' : 'danger'" size="small" effect="light">
              {{ store.deploymentConfig.stateless_enabled ? '已开启' : '已关闭' }}
            </el-tag>
          </div>
          <div class="sv-config-row">
            <span class="sc-label">Redis 连接</span>
            <el-tag :type="store.deploymentConfig.redis_connected ? 'success' : 'danger'" size="small" effect="light">
              {{ store.deploymentConfig.redis_connected ? '已连接' : '未连接' }}
            </el-tag>
          </div>
          <div class="sv-config-row">
            <span class="sc-label">SSE 协议</span>
            <span class="sc-value gv-mono">{{ store.deploymentConfig.sse_protocol }}</span>
          </div>
          <div class="sv-config-row">
            <span class="sc-label">HITL 协议</span>
            <span class="sc-value gv-mono">{{ store.deploymentConfig.hitl_protocol }}</span>
          </div>
        </el-card>

        <h3 class="sv-section sv-mt">说明</h3>
        <el-card class="sv-hint-card" shadow="never">
          <ul class="sv-hint-list">
            <li>无状态部署：编排运行态托管于 Redis，前端零本地状态（M0 目标）。</li>
            <li>SSE 统一采用 Orchestrator 的 <code>step_*</code> 协议，M3 运行态复用同一通道。</li>
            <li>HITL 采用 <code>hitl_approval + resume</code> 协议：处置动作待管理员批准后续跑。</li>
          </ul>
        </el-card>
      </div>
    </div>
  </div>
</template>

<script setup>
import { onMounted } from 'vue'
import { useAgentSettingsStore } from '@/stores/agentSettings'

const store = useAgentSettingsStore()

onMounted(store.refreshAll)
</script>

<style scoped>
.settings-view { padding: 16px; }
.sv-toolbar { display: flex; align-items: center; justify-content: space-between; margin-bottom: 12px; }
.sv-title h2 { margin: 0; font-size: 18px; font-weight: 600; }
.sv-sub { display: block; font-size: 12px; color: var(--color-fg-subtle); margin-top: 2px; }

.sv-body { display: flex; gap: 16px; align-items: flex-start; }
.sv-main { flex: 1; min-width: 0; }
.sv-side { width: 380px; flex-shrink: 0; }

.sv-section { font-size: 14px; font-weight: 500; margin: 0 0 10px; }
.sv-mt { margin-top: 22px; }

.sv-mp-list { display: flex; flex-direction: column; gap: 10px; }
.sv-mp-card {
  background: var(--color-canvas-default); border: 0.5px solid var(--color-border-default);
  border-radius: 10px; padding: 12px 14px; display: flex; flex-direction: column; gap: 8px;
}
.sv-mp-head { display: flex; align-items: center; justify-content: space-between; }
.sv-mp-name { font-size: 14px; font-weight: 600; }
.sv-mp-meta { display: flex; gap: 18px; }
.sv-mp-meta > div { display: flex; flex-direction: column; gap: 2px; }
.mi-label { font-size: 11px; color: var(--color-fg-subtle); }
.mi-value { font-size: 12px; color: var(--color-fg-default); }
.sv-mp-id { font-size: 11px; color: var(--color-fg-subtle); }

.sv-config-card, .sv-hint-card { border-radius: 10px; border: 1px solid var(--color-border-default); }
.sv-config-row { display: flex; align-items: center; justify-content: space-between; padding: 8px 0; border-bottom: 0.5px solid var(--color-border-default); }
.sv-config-row:last-child { border-bottom: none; }
.sc-label { font-size: 13px; color: var(--color-fg-muted); }
.sc-value { font-size: 12px; color: var(--color-fg-default); }

.sv-hint-list { margin: 0; padding-left: 18px; font-size: 12px; color: var(--color-fg-muted); line-height: 1.8; }
.sv-hint-list code { background: var(--color-canvas-inset); padding: 1px 5px; border-radius: 4px; font-family: ui-monospace, monospace; }
.gv-mono { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }

@media (max-width: 1100px) {
  .sv-body { flex-direction: column; }
  .sv-side { width: 100%; }
}
</style>
