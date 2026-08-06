<template>
  <svg class="hero-art" viewBox="0 0 480 360" role="img" aria-label="应急平台品牌标识：绿色等距云与六边形芯片">
    <defs>
      <linearGradient id="gBaseTop" x1="0" y1="0" x2="1" y2="1">
        <stop offset="0" stop-color="#e3efe4"/>
        <stop offset="1" stop-color="#c9e2cb"/>
      </linearGradient>
      <linearGradient id="gBaseRight" x1="0" y1="0" x2="0" y2="1">
        <stop offset="0" stop-color="#bcd9bf"/>
        <stop offset="1" stop-color="#a7cbaa"/>
      </linearGradient>
      <linearGradient id="gBaseLeft" x1="0" y1="0" x2="0" y2="1">
        <stop offset="0" stop-color="#a3c9a7"/>
        <stop offset="1" stop-color="#8db892"/>
      </linearGradient>
      <linearGradient id="gCloud" x1="0" y1="0" x2="0" y2="1">
        <stop offset="0" stop-color="#6fd67c"/>
        <stop offset="1" stop-color="#3fa84b"/>
      </linearGradient>
      <linearGradient id="gCloudDark" x1="0" y1="0" x2="0" y2="1">
        <stop offset="0" stop-color="#2f8f3d"/>
        <stop offset="1" stop-color="#277a34"/>
      </linearGradient>
      <linearGradient id="gChip" x1="0" y1="0" x2="0" y2="1">
        <stop offset="0" stop-color="#5cc96a"/>
        <stop offset="1" stop-color="#2e8f3c"/>
      </linearGradient>
      <radialGradient id="gGround" cx="0.5" cy="0.5" r="0.5">
        <stop offset="0" stop-color="rgba(17,24,39,0.10)"/>
        <stop offset="1" stop-color="rgba(17,24,39,0)"/>
      </radialGradient>
      <filter id="fBlur" x="-50%" y="-50%" width="200%" height="200%">
        <feGaussianBlur stdDeviation="3"/>
      </filter>
    </defs>

    <!-- 地面投影 -->
    <ellipse cx="240" cy="328" rx="150" ry="20" fill="url(#gGround)"/>

    <!-- 哑光六边形基座（等距视角） -->
    <g>
      <polygon points="240,305 335,278 335,304 240,331" fill="url(#gBaseRight)"/>
      <polygon points="240,305 145,278 145,304 240,331" fill="url(#gBaseLeft)"/>
      <polygon points="240,195 335,222 335,278 240,305 145,278 145,222"
               fill="url(#gBaseTop)"
               stroke="#ffffff" stroke-opacity="0.35" stroke-width="1"/>
    </g>

    <!-- 3D 绿色云（从基座升起） -->
    <g class="cloud">
      <!-- 深色底面制造厚度 -->
      <g transform="translate(8,12)" fill="url(#gCloudDark)" opacity="0.9">
        <ellipse cx="240" cy="196" rx="150" ry="40"/>
        <circle cx="165" cy="178" r="46"/>
        <circle cx="240" cy="162" r="60"/>
        <circle cx="305" cy="182" r="42"/>
        <circle cx="200" cy="146" r="40"/>
        <circle cx="262" cy="148" r="36"/>
      </g>
      <!-- 主体 -->
      <g fill="url(#gCloud)">
        <ellipse cx="240" cy="188" rx="150" ry="40"/>
        <circle cx="165" cy="170" r="46"/>
        <circle cx="240" cy="154" r="60"/>
        <circle cx="305" cy="174" r="42"/>
        <circle cx="200" cy="138" r="40"/>
        <circle cx="262" cy="140" r="36"/>
      </g>
      <!-- 顶部高光 -->
      <ellipse cx="206" cy="132" rx="58" ry="18" fill="#ffffff" opacity="0.20" filter="url(#fBlur)"/>
      <ellipse cx="200" cy="130" rx="26" ry="9" fill="#ffffff" opacity="0.35"/>
    </g>

    <!-- 六边形芯片（漂浮在云上方） -->
    <g class="chip c1">
      <polygon points="150,119 164.7,110.5 164.7,93.5 150,85 135.3,93.5 135.3,110.5"
               transform="translate(0,5)" fill="#2e8f3c" opacity="0.9"/>
      <polygon points="150,119 164.7,110.5 164.7,93.5 150,85 135.3,93.5 135.3,110.5"
               fill="url(#gChip)"/>
      <polygon points="150,109 156,105.5 156,98.5 150,95 144,98.5 144,105.5"
               fill="none" stroke="#ffffff" stroke-opacity="0.4" stroke-width="1"/>
    </g>
    <g class="chip c2">
      <polygon points="336,101 347.3,94.5 347.3,81.5 336,75 324.7,81.5 324.7,94.5"
               transform="translate(0,4)" fill="#2e8f3c" opacity="0.9"/>
      <polygon points="336,101 347.3,94.5 347.3,81.5 336,75 324.7,81.5 324.7,94.5"
               fill="url(#gChip)"/>
      <polygon points="336,93.5 340.8,90.75 340.8,85.25 336,82.5 331.2,85.25 331.2,90.75"
               fill="none" stroke="#ffffff" stroke-opacity="0.4" stroke-width="1"/>
    </g>
    <g class="chip c3">
      <polygon points="248,89 257.5,83.5 257.5,72.5 248,67 238.5,72.5 238.5,83.5"
               transform="translate(0,4)" fill="#2e8f3c" opacity="0.9"/>
      <polygon points="248,89 257.5,83.5 257.5,72.5 248,67 238.5,72.5 238.5,83.5"
               fill="url(#gChip)"/>
      <polygon points="248,82.5 251.9,80.25 251.9,75.75 248,73.5 244.1,75.75 244.1,80.25"
               fill="none" stroke="#ffffff" stroke-opacity="0.4" stroke-width="1"/>
    </g>
    <g class="chip c4">
      <polygon points="186,75 193.8,70.5 193.8,61.5 186,57 178.2,61.5 178.2,70.5"
               transform="translate(0,3)" fill="#2e8f3c" opacity="0.85"/>
      <polygon points="186,75 193.8,70.5 193.8,61.5 186,57 178.2,61.5 178.2,70.5"
               fill="url(#gChip)" opacity="0.9"/>
    </g>
    <g class="chip c5">
      <polygon points="308,64 314.9,60 314.9,52 308,48 301.1,52 301.1,60"
               transform="translate(0,3)" fill="#2e8f3c" opacity="0.8"/>
      <polygon points="308,64 314.9,60 314.9,52 308,48 301.1,52 301.1,60"
               fill="url(#gChip)" opacity="0.85"/>
    </g>

    <!-- 装饰光点 -->
    <circle class="spark"    cx="118" cy="122" r="3"  fill="#3fa84b"/>
    <circle class="spark s2" cx="376" cy="108" r="2.5" fill="#3fa84b"/>
    <circle class="spark s3" cx="208" cy="40"  r="2.5" fill="#57c266"/>
    <circle class="spark s4" cx="330" cy="42"  r="2"  fill="#3fa84b"/>
  </svg>
</template>

<script setup>
// 纯展示组件，无逻辑：应急平台 3D 云品牌标识（SVG 原样取自 login_preview_emergency.html）
</script>

<style scoped>
/* 品牌图自适应容器宽度；由父级 .brand-art 控制实际尺寸 */
.hero-art {
  width: 100%;
  height: auto;
  display: block;
}

/* ── 动画（与 preview L205-232 一致）── */
.cloud { animation: cloudBob 6s ease-in-out infinite; }
.chip  { animation: chipFloat 4.5s ease-in-out infinite; }
.chip.c2 { animation-delay: 0.6s; }
.chip.c3 { animation-delay: 1.2s; }
.chip.c4 { animation-delay: 1.8s; }
.chip.c5 { animation-delay: 2.4s; }
.spark { animation: sparkPulse 3s ease-in-out infinite; }
.spark.s2 { animation-delay: 0.8s; }
.spark.s3 { animation-delay: 1.6s; }
.spark.s4 { animation-delay: 2.2s; }

@keyframes cloudBob {
  0%, 100% { transform: translateY(0); }
  50%      { transform: translateY(-6px); }
}
@keyframes chipFloat {
  0%, 100% { transform: translateY(0); }
  50%      { transform: translateY(-9px); }
}
@keyframes sparkPulse {
  0%, 100% { opacity: 0.15; }
  50%      { opacity: 0.60; }
}

/* ── 减弱动态效果降级 ── */
@media (prefers-reduced-motion: reduce) {
  .cloud, .chip, .spark { animation: none; }
}
</style>
