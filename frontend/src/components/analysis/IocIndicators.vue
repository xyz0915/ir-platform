<template>
  <div class="ioc-indicators">
    <div class="ioc-title">威胁指标 (IOC)</div>

    <!-- 有数据时渲染真实 IOC -->
    <template v-if="totalCount > 0">
      <!-- IP 地址 -->
      <div class="ioc-group" v-if="iocs.ips?.length">
        <span class="ioc-group-label">IP 地址 ({{ iocs.ips.length }})</span>
        <div v-for="ip in iocs.ips" :key="ip" class="ioc-item">
          <span class="ioc-label">IP 地址</span>
          <span class="ioc-val">{{ ip }}</span>
          <button class="ioc-action-btn" @click="copyText(ip)" title="复制">📋</button>
        </div>
      </div>

      <!-- SHA256 -->
      <div class="ioc-group" v-if="iocs.sha256?.length">
        <span class="ioc-group-label">文件哈希 ({{ iocs.sha256.length }})</span>
        <div v-for="h in iocs.sha256" :key="h" class="ioc-item">
          <span class="ioc-label">文件哈希</span>
          <span class="ioc-val ioc-val-hash">{{ h.substring(0, 16) }}...</span>
          <button class="ioc-action-btn" @click="copyText(h)" title="复制">📋</button>
          <button class="ioc-action-btn ioc-vt-btn" @click="openVT(h)" title="VirusTotal">VT</button>
        </div>
      </div>

      <!-- 域名 -->
      <div class="ioc-group" v-if="iocs.domains?.length">
        <span class="ioc-group-label">域名 ({{ iocs.domains.length }})</span>
        <div v-for="d in iocs.domains" :key="d" class="ioc-item">
          <span class="ioc-label">域名</span>
          <span class="ioc-val">{{ d }}</span>
          <button class="ioc-action-btn" @click="copyText(d)" title="复制">📋</button>
        </div>
      </div>

      <!-- MD5 -->
      <div class="ioc-group" v-if="iocs.md5?.length">
        <span class="ioc-group-label">MD5 ({{ iocs.md5.length }})</span>
        <div v-for="m in iocs.md5" :key="m" class="ioc-item">
          <span class="ioc-label">MD5</span>
          <span class="ioc-val ioc-val-hash">{{ m.substring(0, 16) }}...</span>
          <button class="ioc-action-btn" @click="copyText(m)" title="复制">📋</button>
        </div>
      </div>

      <!-- 文件路径 -->
      <div class="ioc-group" v-if="iocs.file_paths?.length">
        <span class="ioc-group-label">文件路径 ({{ iocs.file_paths.length }})</span>
        <div v-for="fp in iocs.file_paths.slice(0, 5)" :key="fp" class="ioc-item">
          <span class="ioc-label">文件路径</span>
          <span class="ioc-val ioc-val-path">{{ fp }}</span>
          <button class="ioc-action-btn" @click="copyText(fp)" title="复制">📋</button>
        </div>
        <span v-if="iocs.file_paths.length > 5" class="ioc-more">+{{ iocs.file_paths.length - 5 }} 更多</span>
      </div>

      <!-- 注册表 -->
      <div class="ioc-group" v-if="iocs.registry?.length">
        <span class="ioc-group-label">注册表 ({{ iocs.registry.length }})</span>
        <div v-for="r in iocs.registry.slice(0, 5)" :key="r" class="ioc-item">
          <span class="ioc-label">注册表</span>
          <span class="ioc-val ioc-val-path">{{ r }}</span>
          <button class="ioc-action-btn" @click="copyText(r)" title="复制">📋</button>
        </div>
      </div>

      <!-- 进程名 -->
      <div class="ioc-group" v-if="iocs.process_names?.length">
        <span class="ioc-group-label">进程名 ({{ iocs.process_names.length }})</span>
        <div v-for="pn in iocs.process_names.slice(0, 5)" :key="pn" class="ioc-item">
          <span class="ioc-label">进程名</span>
          <span class="ioc-val">{{ pn }}</span>
          <button class="ioc-action-btn" @click="copyText(pn)" title="复制">📋</button>
        </div>
      </div>
    </template>

    <!-- 空状态 -->
    <template v-else>
      <div class="ioc-empty-hint">暂无威胁指标</div>
    </template>
  </div>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  iocs: { type: Object, default: () => ({}) },
})

const totalCount = computed(() => {
  const i = props.iocs
  if (!i) return 0
  return (i.ips?.length || 0) + (i.domains?.length || 0) + (i.md5?.length || 0)
       + (i.sha1?.length || 0) + (i.sha256?.length || 0) + (i.file_paths?.length || 0)
       + (i.registry?.length || 0) + (i.process_names?.length || 0)
})

function copyText(text) {
  navigator.clipboard.writeText(text).then(() => {}).catch(() => {})
}

function openVT(hash) {
  window.open(`https://www.virustotal.com/gui/file/${hash}`, '_blank')
}
</script>

<style scoped>
.ioc-indicators {
  background: var(--color-canvas-default);
  border: 0.5px solid #e5e5e7;
  border-radius: 8px;
  padding: 14px;
  margin-bottom: 12px;
}
.ioc-title {
  font-size: 12px;
  font-weight: 500;
  color: #1d1d1f;
  margin-bottom: 10px;
}
.ioc-group {
  margin-bottom: 8px;
}
.ioc-group-label {
  display: block;
  font-size: 11px;
  color: #b4b2a9;
  margin-bottom: 4px;
  font-weight: 500;
}
.ioc-item {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 8px;
  border: 0.5px solid #e5e5e7;
  border-radius: 6px;
  margin-bottom: 4px;
  font-size: 11px;
}
.ioc-label {
  color: #b4b2a9;
  font-size: 10px;
  white-space: nowrap;
  min-width: 48px;
}
.ioc-val {
  flex: 1;
  color: #1d1d1f;
  font-family: "SF Mono", "JetBrains Mono", "Cascadia Code", monospace;
  font-size: 11px;
  word-break: break-all;
}
.ioc-val-hash {
  font-size: 10px;
}
.ioc-val-path {
  font-size: 10px;
}
.ioc-action-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 2px 6px;
  font-size: 10px;
  border: 0.5px solid #e5e5e7;
  border-radius: 4px;
  background: #f8f8fa;
  color: #888780;
  cursor: pointer;
  white-space: nowrap;
  line-height: 1.4;
}
.ioc-action-btn:hover {
  background: #E6F1FB;
  color: #185FA5;
}
.ioc-vt-btn {
  background: #FCEBEB;
  color: #A32D2D;
  border-color: rgba(163,45,45,0.2);
  font-weight: 500;
}
.ioc-vt-btn:hover {
  background: #A32D2D;
  color: #fff;
}
.ioc-more {
  font-size: 11px;
  color: #888780;
}
.ioc-empty-hint {
  font-size: 12px;
  color: #b4b2a9;
  text-align: center;
  padding: 20px 0;
}
</style>
