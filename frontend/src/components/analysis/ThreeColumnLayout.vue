<template>
  <div class="three-column-layout">
    <!-- 左栏 -->
    <div class="tcl-left" :class="{ 'tcl-overlay-visible': showLeftOverlay }">
      <div class="tcl-left-header">
        <span class="tcl-left-title">攻击链时间线</span>
        <button class="tcl-toggle-btn tcl-toggle-left" @click="closeLeft" v-if="showLeftOverlay">
          <svg width="12" height="12" viewBox="0 0 12 12" fill="none"><path d="M7 2L3 6L7 10" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg>
        </button>
      </div>
      <div class="tcl-left-content">
        <slot name="left" />
      </div>
    </div>

    <!-- 左栏遮罩（窄屏） -->
    <div class="tcl-overlay" v-if="showLeftOverlay" @click="closeLeft"></div>

    <!-- 中栏 -->
    <div class="tcl-center">
      <!-- 窄屏工具栏 -->
      <div class="tcl-mobile-bar" v-if="isNarrow">
        <button class="tcl-mobile-btn" @click="openLeft">
          <svg width="14" height="14" viewBox="0 0 14 14" fill="none"><rect x="2" y="3" width="10" height="1.5" rx="0.75" fill="currentColor"/><rect x="2" y="6.25" width="10" height="1.5" rx="0.75" fill="currentColor"/><rect x="2" y="9.5" width="10" height="1.5" rx="0.75" fill="currentColor"/></svg>
          时间线
        </button>
        <button class="tcl-mobile-btn" @click="openRight">
          AI 研判
          <svg width="14" height="14" viewBox="0 0 14 14" fill="none"><rect x="2" y="3" width="10" height="1.5" rx="0.75" fill="currentColor"/><rect x="2" y="6.25" width="10" height="1.5" rx="0.75" fill="currentColor"/><rect x="2" y="9.5" width="10" height="1.5" rx="0.75" fill="currentColor"/></svg>
        </button>
      </div>
      <div class="tcl-center-content">
        <slot name="center" />
      </div>
    </div>

    <!-- 右栏遮罩（窄屏） -->
    <div class="tcl-overlay" v-if="showRightOverlay" @click="closeRight"></div>

    <!-- 右栏 -->
    <div class="tcl-right" :class="{ 'tcl-overlay-visible': showRightOverlay }">
      <div class="tcl-right-header">
        <button class="tcl-toggle-btn tcl-toggle-right" @click="closeRight" v-if="showRightOverlay">
          <svg width="12" height="12" viewBox="0 0 12 12" fill="none"><path d="M5 2L9 6L5 10" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg>
        </button>
        <span class="tcl-right-title">AI 研判</span>
      </div>
      <div class="tcl-right-content">
        <slot name="right" />
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted } from 'vue'

const props = defineProps({
  responsiveBreakpoint: { type: Number, default: 1200 },
})

const showLeftOverlay = ref(false)
const showRightOverlay = ref(false)
const isNarrow = ref(false)

function checkWidth() {
  isNarrow.value = window.innerWidth < props.responsiveBreakpoint
  if (!isNarrow.value) {
    showLeftOverlay.value = false
    showRightOverlay.value = false
  }
}

function openLeft() { showLeftOverlay.value = true }
function closeLeft() { showLeftOverlay.value = false }
function openRight() { showRightOverlay.value = true }
function closeRight() { showRightOverlay.value = false }

onMounted(() => {
  checkWidth()
  window.addEventListener('resize', checkWidth)
})

onUnmounted(() => {
  window.removeEventListener('resize', checkWidth)
})
</script>

<style scoped>
.three-column-layout {
  flex: 1;
  display: flex;
  overflow: hidden;
  position: relative;
  background: var(--color-canvas-subtle);
  gap: 1px;
}

/* 左栏 */
.tcl-left {
  width: 280px;
  min-width: 280px;
  display: flex;
  flex-direction: column;
  background: var(--color-canvas-default);
  border-right: 0.5px solid var(--color-border-tertiary);
}
.tcl-left-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 12px;
  border-bottom: 0.5px solid var(--color-border-default);
  flex-shrink: 0;
}
.tcl-left-title {
  font-size: 12px;
  font-weight: 500;
  color: var(--color-fg-subtle);
}
.tcl-left-content {
  flex: 1;
  overflow-y: auto;
  overflow-x: hidden;
}

/* 中栏 */
.tcl-center {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-width: 0;
  background: var(--color-canvas-subtle);
}
.tcl-center-content {
  flex: 1;
  overflow-y: auto;
  overflow-x: hidden;
  padding: 12px;
}

/* 右栏 */
.tcl-right {
  width: 320px;
  min-width: 320px;
  display: flex;
  flex-direction: column;
  background: var(--color-canvas-default);
  border-left: 0.5px solid var(--color-border-tertiary);
}
.tcl-right-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 12px;
  border-bottom: 0.5px solid var(--color-border-default);
  flex-shrink: 0;
}
.tcl-right-title {
  font-size: 12px;
  font-weight: 500;
  color: var(--color-fg-subtle);
}
.tcl-right-content {
  flex: 1;
  overflow-y: auto;
  overflow-x: hidden;
}

/* 折叠按钮 */
.tcl-toggle-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 22px;
  height: 22px;
  padding: 0;
  border: 0.5px solid var(--color-border-default);
  border-radius: 4px;
  background: var(--color-canvas-default);
  color: var(--color-fg-subtle);
  cursor: pointer;
}
.tcl-toggle-btn:hover {
  background: var(--color-canvas-inset);
  color: var(--color-fg-default);
}

/* 窄屏工具栏 */
.tcl-mobile-bar {
  display: none;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  background: var(--color-canvas-default);
  border-bottom: 0.5px solid var(--color-border-default);
  flex-shrink: 0;
}
.tcl-mobile-btn {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 4px 10px;
  font-size: 11px;
  border: 0.5px solid var(--color-border-default);
  border-radius: 4px;
  background: var(--color-canvas-default);
  color: var(--color-accent-fg);
  cursor: pointer;
}
.tcl-mobile-btn:hover {
  background: var(--color-accent-subtle);
}

/* 遮罩 */
.tcl-overlay {
  display: none;
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.3);
  z-index: 99;
}

/* 响应式降级 */
@media (max-width: 1200px) {
  .tcl-left {
    position: fixed;
    top: 0;
    left: -280px;
    width: 280px;
    height: 100vh;
    z-index: 100;
    transition: left 0.2s ease;
    border-right: 0.5px solid var(--color-border-default);
  }
  .tcl-left.tcl-overlay-visible {
    left: 0;
  }

  .tcl-right {
    position: fixed;
    top: 0;
    right: -320px;
    width: 320px;
    height: 100vh;
    z-index: 100;
    transition: right 0.2s ease;
    border-left: 0.5px solid var(--color-border-default);
  }
  .tcl-right.tcl-overlay-visible {
    right: 0;
  }

  .tcl-overlay {
    display: block;
  }

  .tcl-mobile-bar {
    display: flex;
  }
}
</style>
