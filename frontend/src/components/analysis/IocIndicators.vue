<template>
  <div class="ioc-indicators" v-if="totalCount > 0">
    <div class="ioc-title">威胁指标 ({{ totalCount }})</div>

    <!-- IP 地址 -->
    <div class="ioc-group" v-if="iocs.ips?.length">
      <span class="ioc-group-label">🌐 IP 地址 ({{ iocs.ips.length }})</span>
      <span v-for="ip in iocs.ips" :key="ip" class="ioc-chip ioc-ip" :title="ip" @click="copyText(ip)">{{ ip }}</span>
    </div>

    <!-- SHA256 -->
    <div class="ioc-group" v-if="iocs.sha256?.length">
      <span class="ioc-group-label">🔑 SHA256 ({{ iocs.sha256.length }})</span>
      <span v-for="h in iocs.sha256" :key="h" class="ioc-chip ioc-hash" :title="h" @click="copyText(h)">
        {{ h.substring(0, 16) }}...
        <a class="ioc-vt-link" @click.stop="openVT(h)">VT</a>
      </span>
    </div>

    <!-- 域名 -->
    <div class="ioc-group" v-if="iocs.domains?.length">
      <span class="ioc-group-label">🌐 域名 ({{ iocs.domains.length }})</span>
      <span v-for="d in iocs.domains" :key="d" class="ioc-chip ioc-domain" :title="d" @click="copyText(d)">{{ d }}</span>
    </div>

    <!-- MD5 -->
    <div class="ioc-group" v-if="iocs.md5?.length">
      <span class="ioc-group-label">🔏 MD5 ({{ iocs.md5.length }})</span>
      <span v-for="m in iocs.md5" :key="m" class="ioc-chip ioc-hash" :title="m" @click="copyText(m)">{{ m.substring(0, 16) }}...</span>
    </div>

    <!-- 文件路径 -->
    <div class="ioc-group" v-if="iocs.file_paths?.length">
      <span class="ioc-group-label">📁 文件路径 ({{ iocs.file_paths.length }})</span>
      <div v-for="fp in iocs.file_paths.slice(0, 5)" :key="fp" class="ioc-fp">{{ fp }}</div>
      <span v-if="iocs.file_paths.length > 5" class="ioc-more">+{{ iocs.file_paths.length - 5 }} 更多</span>
    </div>
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
  border: 0.5px solid var(--color-border-default);
  border-radius: 10px;
  padding: 14px;
  margin-bottom: 10px;
}
.ioc-title {
  font-size: 12px;
  font-weight: 500;
  color: var(--color-fg-subtle);
  margin-bottom: 10px;
}
.ioc-group {
  margin: 8px 0;
}
.ioc-group-label {
  display: block;
  font-size: 11px;
  color: var(--color-fg-subtle);
  margin-bottom: 4px;
}
.ioc-chip {
  display: inline-block;
  padding: 2px 8px;
  margin: 2px 4px 2px 0;
  border-radius: 4px;
  font-size: 11px;
  cursor: pointer;
  font-family: monospace;
  transition: all 0.1s;
}
.ioc-chip:hover { transform: scale(1.05); }
.ioc-ip { background: #dbeafe; color: #1e40af; }
.ioc-hash { background: #fce7f3; color: #9d174d; }
.ioc-domain { background: #d1fae5; color: #065f46; }
.ioc-fp {
  font-size: 11px;
  font-family: monospace;
  padding: 2px 4px;
  color: var(--color-fg-subtle);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 280px;
}
.ioc-vt-link {
  margin-left: 4px;
  color: #2563eb;
  text-decoration: underline;
  cursor: pointer;
  font-family: sans-serif;
}
.ioc-more {
  font-size: 11px;
  color: var(--color-fg-light);
}
</style>
