<template>
  <svg class="hero-art" viewBox="0 0 400 400" role="img" aria-label="应急平台品牌标识：绿色雷达监测环与脉冲信号">
    <defs>
      <!-- 无渐变、无滤镜：仅描边与少量填充 -->
    </defs>

    <!-- 外圈参考环（极淡） -->
    <circle cx="200" cy="200" r="168" fill="none"
            stroke="#3fa84b" stroke-opacity="0.10" stroke-width="1.5"/>

    <!-- 雷达同心圆（3 圈：绿/灰/绿，透明度由外向内递增） -->
    <circle cx="200" cy="200" r="150" fill="none"
            stroke="#3fa84b" stroke-opacity="0.22" stroke-width="1.5"/>
    <circle cx="200" cy="200" r="104" fill="none"
            stroke="#6b7280" stroke-opacity="0.32" stroke-width="1.5"/>
    <circle cx="200" cy="200" r="60"  fill="none"
            stroke="#3fa84b" stroke-opacity="0.45" stroke-width="1.75"/>

    <!-- 十字方向射线（监测扫描轴线） -->
    <g stroke="#3fa84b" stroke-opacity="0.30" stroke-width="1.5" stroke-linecap="round">
      <line x1="200" y1="50"  x2="200" y2="350"/>
      <line x1="50"  y1="200" x2="350" y2="200"/>
    </g>

    <!-- 对角刻度（45° 方位标记，跨外圈内外侧） -->
    <g stroke="#6b7280" stroke-opacity="0.35" stroke-width="1.5" stroke-linecap="round">
      <line x1="303.2" y1="303.2" x2="308.9" y2="308.9"/>
      <line x1="96.8"  y1="303.2" x2="91.1"  y2="308.9"/>
      <line x1="96.8"  y1="96.8"  x2="91.1"  y2="91.1"/>
      <line x1="303.2" y1="96.8"  x2="308.9" y2="91.1"/>
    </g>

    <!-- 监测节点（信号点：绿为主、灰为辅，静态） -->
    <circle cx="335.9" cy="263.4" r="3.5" fill="#3fa84b"/>
    <circle cx="109.9" cy="148.0" r="3"   fill="#6b7280"/>
    <circle cx="120.3" cy="266.9" r="3"   fill="#3fa84b" opacity="0.85"/>
    <circle cx="230.0" cy="148.0" r="2.5" fill="#6b7280"/>

    <!-- 脉冲环（2 圈，从中心扩散至外圈后消失） -->
    <circle class="pulse" cx="200" cy="200" r="30" fill="none"
            stroke="#3fa84b" stroke-width="2"/>
    <circle class="pulse p2" cx="200" cy="200" r="30" fill="none"
            stroke="#3fa84b" stroke-width="2"/>

    <!-- 雷达扫描：前导射线 + 拖尾虚线弧（整体绕中心旋转） -->
    <g class="sweep">
      <line x1="200" y1="200" x2="200" y2="56"
            stroke="#3fa84b" stroke-width="2" stroke-linecap="round" stroke-opacity="0.85"/>
      <path d="M 117.4 82.0 A 144 144 0 0 1 200 56"
            fill="none" stroke="#3fa84b" stroke-width="2" stroke-linecap="round"
            stroke-opacity="0.50" stroke-dasharray="5 7"/>
    </g>

    <!-- 中心节点（实心圆 + 细环） -->
    <circle cx="200" cy="200" r="15"  fill="none"
            stroke="#3fa84b" stroke-opacity="0.55" stroke-width="1.5"/>
    <circle cx="200" cy="200" r="7.5" fill="#3fa84b"/>
  </svg>
</template>

<script setup>
// 纯展示组件，无逻辑：应急平台雷达监测环品牌标识（SVG 原样取自 brandart_preview_v2.html，方案 A+B 综合）
</script>

<style scoped>
/* 品牌图自适应容器宽度；由父级 .brand-art 控制实际尺寸 */
.hero-art {
  width: 100%;
  height: auto;
  display: block;
}

/* ── 动画（与 preview L205-237 一致）──
   仅 2 个极简动效：雷达扫描弧旋转 + 脉冲环扩散
   均为纯 CSS transform/opacity，无渐变、无发光滤镜 */
/* 雷达扫描线 + 拖尾弧：绕中心 8s 匀速旋转一圈 */
.sweep {
  transform-box: view-box;
  transform-origin: 50% 50%;
  animation: sweepRotate 8s linear infinite;
}
@keyframes sweepRotate {
  from { transform: rotate(0deg); }
  to   { transform: rotate(360deg); }
}

/* 脉冲环：从中心向外扩散消失（2.6s 一轮，两环错峰 1.3s） */
.pulse {
  transform-box: fill-box;
  transform-origin: center;
  opacity: 0;
  animation: pulseRing 2.6s cubic-bezier(0.22, 0.61, 0.36, 1) infinite;
}
.pulse.p2 { animation-delay: 1.3s; }
@keyframes pulseRing {
  0%   { transform: scale(0.55); opacity: 0.45; }
  70%  { opacity: 0.10; }
  100% { transform: scale(4.9);  opacity: 0; }
}

/* ── 减弱动态效果降级 ── */
@media (prefers-reduced-motion: reduce) {
  .sweep { animation: none; }
  .pulse { animation: none; display: none; }
}
</style>
