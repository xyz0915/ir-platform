<template>
  <div class="login-container">
    <!-- 顶部横条 -->
    <div class="login-topbar">
      <div class="topbar-left">
        <div class="topbar-logo">
          <svg width="20" height="24" viewBox="0 0 20 24" fill="none">
            <path d="M10 1L2 5V11C2 16.5 5.5 21.5 10 23C14.5 21.5 18 16.5 18 11V5L10 1Z" fill="#639922" />
            <path d="M7 12L9.5 14.5L14 9" stroke="white" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" />
          </svg>
        </div>
        <span class="topbar-title">个人应急响应平台</span>
        <span class="topbar-subtitle">IR Platform</span>
      </div>
      <div class="topbar-right">
        <span class="topbar-status">●</span>
        <span>安全运营中心</span>
      </div>
    </div>

    <!-- 中间主体 -->
    <div class="login-main">
      <!-- 背景装饰色块 -->
      <div class="deco-blob blob-1"></div>
      <div class="deco-blob blob-2"></div>
      <div class="deco-blob blob-3"></div>

      <!-- 左侧品牌区 -->
      <div class="login-brand">
        <div class="brand-title">
          让安全运营<br />更高效更智能
        </div>
        <div class="brand-subtitle">AI驱动的威胁检测与应急响应</div>
        <div class="brand-divider"></div>
        <div class="brand-features">
          <div class="brand-feature">
            <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
              <path d="M7 12.5C7.82843 12.5 8.5 11.8284 8.5 11H5.5C5.5 11.8284 6.17157 12.5 7 12.5Z" fill="white" />
              <path d="M11 9.5V6.5C11 4.4 9.8 2.7 8 2.1V1.5C8 0.947715 7.55228 0.5 7 0.5C6.44772 0.5 6 0.947715 6 1.5V2.1C4.2 2.7 3 4.4 3 6.5V9.5L2 10.5V11H12V10.5L11 9.5Z" fill="white" />
            </svg>
            <span>告警聚合降噪</span>
          </div>
          <div class="brand-feature">
            <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
              <path d="M7 0.5L8.5 5.5L13.5 7L8.5 8.5L7 13.5L5.5 8.5L0.5 7L5.5 5.5L7 0.5Z" fill="white" />
            </svg>
            <span>AI研判溯源</span>
          </div>
          <div class="brand-feature">
            <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
              <rect x="0.5" y="0.5" width="5" height="5" rx="1" fill="white" />
              <rect x="8.5" y="0.5" width="5" height="5" rx="1" fill="white" />
              <rect x="0.5" y="8.5" width="5" height="5" rx="1" fill="white" />
              <rect x="8.5" y="8.5" width="5" height="5" rx="1" fill="white" />
            </svg>
            <span>资产事件全貌</span>
          </div>
        </div>
      </div>

      <!-- 右侧表单区 -->
      <div class="login-form-wrapper">
        <div class="login-form-card">
          <h3 class="form-title">账号登录</h3>
          <p class="form-subtitle">请输入账号信息登录系统</p>
          <el-form
            ref="formRef"
            :model="form"
            :rules="rules"
            label-width="0"
            @submit.prevent="handleLogin"
          >
            <el-form-item prop="username">
              <el-input
                v-model="form.username"
                placeholder="用户名"
                size="large"
                :prefix-icon="User"
              />
            </el-form-item>
            <el-form-item prop="password">
              <el-input
                v-model="form.password"
                type="password"
                placeholder="密码"
                size="large"
                :prefix-icon="Lock"
                show-password
                @keyup.enter="handleLogin"
              />
            </el-form-item>
            <el-form-item>
              <el-button
                type="primary"
                size="large"
                class="login-btn"
                :loading="loading"
                @click="handleLogin"
              >
                登录
              </el-button>
            </el-form-item>
          </el-form>
          <div class="login-extra">
            <a href="javascript:void(0)" class="extra-link">忘记密码</a>
            <span class="extra-sep">|</span>
            <a href="javascript:void(0)" class="extra-link">联系管理员</a>
          </div>
          <div class="login-tip">
            <el-text type="info" size="small">默认账号: admin / admin123</el-text>
          </div>
        </div>
      </div>
    </div>

    <!-- 底部横条 -->
    <div class="login-bottombar">
      <span class="bottombar-copyright">© 2026 IR Platform v1.0</span>
      <div class="compliance-badges">
        <span class="badge">SOC2</span>
        <span class="badge">等保三级</span>
        <span class="badge">ISO27001</span>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, reactive } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { User, Lock } from '@element-plus/icons-vue'
import { useAuthStore } from '@/stores/auth'

const router = useRouter()
const authStore = useAuthStore()

const formRef = ref(null)
const loading = ref(false)

const form = reactive({
  username: 'admin',
  password: ''
})

const rules = {
  username: [{ required: true, message: '请输入用户名', trigger: 'blur' }],
  password: [{ required: true, message: '请输入密码', trigger: 'blur' }]
}

async function handleLogin() {
  if (!formRef.value) return
  await formRef.value.validate(async (valid) => {
    if (!valid) return
    loading.value = true
    try {
      await authStore.login(form.username, form.password)
      ElMessage.success('登录成功')
      router.push('/')
    } catch (error) {
      // 错误已在拦截器中处理
    } finally {
      loading.value = false
    }
  })
}
</script>

<style scoped>
/* ===== 整体容器 ===== */
.login-container {
  min-height: 100vh;
  display: flex;
  flex-direction: column;
  background: var(--color-canvas-subtle);
}

/* ===== 顶部横条 ===== */
.login-topbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 28px;
  background: #fff;
  border-bottom: 0.5px solid var(--color-border-tertiary);
  flex-shrink: 0;
  z-index: 2;
}

.topbar-left {
  display: flex;
  align-items: center;
  gap: 10px;
}

.topbar-logo {
  display: flex;
  align-items: center;
  justify-content: center;
}

.topbar-title {
  font-size: 16px;
  font-weight: 600;
  color: var(--color-fg-default);
}

.topbar-subtitle {
  font-size: 12px;
  color: var(--color-fg-muted);
}

.topbar-right {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 14px;
  color: var(--color-fg-default);
}

.topbar-status {
  color: #639922;
  font-size: 14px;
}

/* ===== 中间主体 ===== */
.login-main {
  flex: 1;
  display: flex;
  position: relative;
  overflow: hidden;
}

/* ===== 背景装饰色块 ===== */
.deco-blob {
  position: absolute;
  z-index: 0;
  pointer-events: none;
}

.blob-1 {
  width: 170px;
  height: 170px;
  border-radius: 50%;
  background: #C0DD97;
  top: -30px;
  right: -30px;
}

.blob-2 {
  width: 200px;
  height: 200px;
  border-radius: 50%;
  background: #EEEDFE;
  bottom: -40px;
  left: -40px;
}

.blob-3 {
  width: 36px;
  height: 36px;
  border-radius: 8px;
  background: #FAEEDA;
  top: 55%;
  left: 60px;
  transform: rotate(15deg);
}

/* ===== 左侧品牌区 ===== */
.login-brand {
  width: 260px;
  flex-shrink: 0;
  background: #639922;
  color: #fff;
  padding: 28px 24px;
  z-index: 1;
  display: flex;
  flex-direction: column;
}

.brand-title {
  font-size: 16px;
  font-weight: 500;
  line-height: 1.5;
  color: #fff;
}

.brand-subtitle {
  font-size: 12px;
  opacity: 0.85;
  margin-top: 4px;
  color: #fff;
}

.brand-divider {
  height: 1px;
  background: rgba(255, 255, 255, 0.2);
  margin: 18px 0;
}

.brand-features {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.brand-feature {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  color: #fff;
}

.brand-feature svg {
  flex-shrink: 0;
  background: rgba(255, 255, 255, 0.22);
  border-radius: 50%;
  padding: 5px;
  width: 24px;
  height: 24px;
  box-sizing: content-box;
}

/* ===== 右侧表单区 ===== */
.login-form-wrapper {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
  z-index: 1;
}

.login-form-card {
  background: #fff;
  border-radius: 12px;
  border: 0.5px solid var(--color-border-default);
  max-width: 340px;
  width: 100%;
  padding: 28px 24px 22px;
  box-shadow: 0 4px 16px rgba(140, 149, 159, 0.12);
}

.form-title {
  margin: 0 0 4px;
  font-size: 18px;
  font-weight: 600;
  color: var(--color-fg-default);
}

.form-subtitle {
  margin: 0 0 22px;
  font-size: 13px;
  color: var(--color-fg-muted);
}

.form-title,
.form-subtitle {
  text-align: center;
}

/* ===== 登录按钮 ===== */
.login-btn {
  width: 100%;
  --el-button-bg-color: #639922;
  --el-button-border-color: #639922;
  --el-button-hover-bg-color: #56801a;
  --el-button-hover-border-color: #56801a;
  --el-button-active-bg-color: #4d7016;
  --el-button-active-border-color: #4d7016;
}

/* ===== 表单底部链接 ===== */
.login-extra {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  margin-top: 4px;
}

.extra-link {
  color: var(--color-accent-fg);
  font-size: 13px;
  text-decoration: none;
  cursor: pointer;
}

.extra-link:hover {
  text-decoration: underline;
}

.extra-sep {
  color: var(--color-border-default);
  font-size: 13px;
}

/* ===== 默认账号提示 ===== */
.login-tip {
  text-align: center;
  margin-top: 14px;
}

/* ===== 底部横条 ===== */
.login-bottombar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 28px;
  background: #fff;
  border-top: 0.5px solid var(--color-border-tertiary);
  flex-shrink: 0;
  z-index: 2;
}

.bottombar-copyright {
  font-size: 12px;
  color: var(--color-fg-muted);
}

.compliance-badges {
  display: flex;
  align-items: center;
  gap: 10px;
}

.badge {
  display: inline-block;
  font-size: 11px;
  color: var(--color-fg-muted);
  border: 0.5px solid var(--color-border-default);
  border-radius: 3px;
  padding: 2px 6px;
  line-height: 1.4;
}
</style>
