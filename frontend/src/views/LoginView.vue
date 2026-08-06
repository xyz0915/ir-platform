<template>
  <div class="login-page">
    <main class="login-main">
      <!-- ── 左品牌区 ── -->
      <section class="login-brand" aria-label="品牌介绍">
        <BrandArt class="brand-art" />
        <h1 class="brand-title">
          <span>应急平台</span><span class="gap" aria-hidden="true"></span><span>安全护航</span>
        </h1>
        <p class="brand-sub">
          <span>实时监测</span><span>智能分析</span><span>快速处置</span><span>闭环溯源</span>
        </p>
      </section>

      <!-- ── 右登录卡 ── -->
      <section class="login-panel" aria-label="登录表单">
        <div class="login-card">
          <div class="card-head">
            <span class="card-logo" aria-hidden="true">
              <svg viewBox="0 0 24 16" fill="none">
                <g fill="#ffffff">
                  <circle cx="8" cy="10" r="5"/>
                  <circle cx="16" cy="10" r="4.2"/>
                  <circle cx="12" cy="6.5" r="4.6"/>
                  <rect x="4" y="9.5" width="16" height="4.5" rx="2.2"/>
                </g>
              </svg>
            </span>
            <h2>应急运营门户</h2>
          </div>
          <p class="card-sub">统一身份认证 · 应急响应入口</p>

          <el-form
            ref="formRef"
            :model="form"
            :rules="rules"
            label-width="0"
            hide-required-asterisk
            @submit.prevent="handleLogin"
          >
            <div class="field">
              <label class="field-label" for="login-username">用户名</label>
              <el-form-item prop="username">
                <el-input
                  id="login-username"
                  v-model="form.username"
                  placeholder="请输入用户名"
                  autocomplete="username"
                  @keyup.enter="handleLogin"
                />
              </el-form-item>
            </div>
            <div class="field">
              <label class="field-label" for="login-password">密码</label>
              <el-form-item prop="password">
                <el-input
                  id="login-password"
                  v-model="form.password"
                  type="password"
                  placeholder="请输入密码"
                  autocomplete="current-password"
                  show-password
                  @keyup.enter="handleLogin"
                />
              </el-form-item>
            </div>

            <label class="agree" for="login-agree">
              <input id="login-agree" v-model="agreed" type="checkbox" />
              <span class="agree-text">
                我已阅读并同意
                <a href="#" @click.prevent>用户协议</a>
                和
                <a href="#" @click.prevent>隐私政策声明</a>
              </span>
            </label>

            <el-button
              type="primary"
              class="login-submit"
              :loading="loading"
              :disabled="!agreed"
              @click="handleLogin"
            >
              登录
            </el-button>
          </el-form>

          <p class="card-foot">登录遇到问题？请联系平台管理员</p>
        </div>
      </section>
    </main>
  </div>
</template>

<script setup>
import { ref, reactive } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { useAuthStore } from '@/stores/auth'
import BrandArt from '@/components/login/BrandArt.vue'

const router = useRouter()
const authStore = useAuthStore()

const formRef = ref(null)
const loading = ref(false)
const agreed = ref(true) // 默认勾选（与 preview 一致）；纯前端门槛，不传后端

const form = reactive({
  username: '', // R8：默认置空，不预填账号（preview placeholder 一致）
  password: ''
})

const rules = {
  username: [{ required: true, message: '请输入用户名', trigger: 'blur' }],
  password: [{ required: true, message: '请输入密码', trigger: 'blur' }]
}

async function handleLogin() {
  // 协议门槛：Enter 提交可绕过按钮 disabled，此处必须再次校验（设计 §4 双重保障）
  if (!agreed.value) {
    ElMessage.warning('请先阅读并同意用户协议和隐私政策声明')
    return
  }
  if (!formRef.value) return
  await formRef.value.validate(async (valid) => {
    if (!valid) return
    loading.value = true
    try {
      await authStore.login(form.username, form.password)
      ElMessage.success('登录成功')
      router.push('/')
    } catch (error) {
      // 错误已在拦截器中处理（401 detail toast / 其他通用提示）
    } finally {
      loading.value = false
    }
  })
}
</script>

<style scoped>
/* ===== 页面容器 =====
 * 登录页固定品牌色，不随主题切换（设计 §8.1：品牌前台必须与已审批设计一致，
 * 项目 theme.css 暗色模式下变量会变，故此处显式写死色值，防止后人误改回变量） */
.login-page {
  min-height: 100vh;
  background: #f0f2f5;
  display: flex;
  align-items: center;
  justify-content: center;
}

.login-main {
  width: 100%;
  max-width: 1240px;
  padding: 48px 40px;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 5%;
}

/* ===== 左品牌区 ===== */
.login-brand {
  flex: 0 1 55%;
  position: relative;
  display: flex;
  flex-direction: column;
  align-items: center;
  text-align: center;
}

.login-brand::before {
  content: "";
  position: absolute;
  inset: -6% -14%;
  z-index: 0;
  background: radial-gradient(
    560px 420px at 50% 38%,
    rgba(63, 168, 75, 0.12),
    rgba(63, 168, 75, 0) 68%
  );
  pointer-events: none;
}

.login-brand > * {
  position: relative;
  z-index: 1;
}

.brand-art {
  width: min(460px, 100%);
  margin-bottom: 6px;
}

.brand-title {
  font-size: 44px;
  font-weight: 700;
  line-height: 1.35;
  color: #111827;
  letter-spacing: 0.04em;
  white-space: nowrap;
}

.brand-title .gap {
  display: inline-block;
  width: 3em;
}

.brand-sub {
  margin-top: 14px;
  font-size: 15px;
  color: #6b7280;
  letter-spacing: 0.18em;
  padding-left: 0.18em;
  white-space: nowrap;
}

.brand-sub span {
  margin: 0 1.1em;
}

.brand-sub span:first-child {
  margin-left: 0;
}

.brand-sub span:last-child {
  margin-right: 0;
}

/* ===== 右登录卡 ===== */
.login-panel {
  flex: 0 1 30%;
  display: flex;
  justify-content: center;
}

.login-card {
  width: 100%;
  max-width: 400px;
  background: #ffffff;
  border: 1px solid #e9ecef;
  border-radius: 16px;
  box-shadow:
    0 18px 50px rgba(17, 24, 39, 0.10),
    0 2px 6px rgba(17, 24, 39, 0.04);
  padding: 40px 38px 32px;
}

.card-head {
  display: flex;
  align-items: center;
  gap: 11px;
}

.card-logo {
  width: 36px;
  height: 36px;
  border-radius: 10px;
  flex: none;
  background: linear-gradient(135deg, #57c266, #2f8f3d);
  display: flex;
  align-items: center;
  justify-content: center;
  box-shadow: 0 4px 10px rgba(63, 168, 75, 0.28);
}

.card-logo svg {
  width: 22px;
  height: 22px;
}

.card-head h2 {
  font-size: 21px;
  font-weight: 600;
  letter-spacing: 0.02em;
  color: #111827;
}

.card-sub {
  margin-top: 6px;
  font-size: 13px;
  color: #8a919c;
}

/* ===== 表单字段 ===== */
.field {
  margin-top: 24px;
}

.field-label {
  display: block;
  font-size: 13px;
  font-weight: 500;
  color: #374151;
  margin-bottom: 8px;
}

/* Element Plus 输入框覆盖（模拟 preview 视觉） */
.login-card .el-input__wrapper {
  box-shadow: 0 0 0 1px #d7dbe1 inset;
  border-radius: 10px;
  height: 46px;
  padding: 0 14px;
  background: #ffffff;
  transition: border-color 0.15s, box-shadow 0.15s, background 0.15s;
}

.login-card .el-input__wrapper:hover {
  box-shadow: 0 0 0 1px #c3c9d2 inset;
}

.login-card .el-input__wrapper.is-focus,
.login-card .el-input__wrapper:focus-within {
  box-shadow:
    0 0 0 1px #3fa84b inset,
    0 0 0 3px rgba(63, 168, 75, 0.14) inset;
  background: #fcfefc;
}

.login-card .el-input__inner {
  height: 46px;
  font-size: 14px;
  color: #111827;
}

.login-card .el-input__inner::placeholder {
  color: #a3aab4;
}

/* 字段间距由 .field 控制，去掉 el-form-item 默认下边距 */
.field .el-form-item {
  margin-bottom: 0;
}

/* ===== 协议行 ===== */
.agree {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  margin-top: 18px;
  cursor: pointer;
  user-select: none;
}

.agree input {
  width: 16px;
  height: 16px;
  margin-top: 2px;
  flex: none;
  accent-color: #3fa84b;
  cursor: pointer;
}

.agree-text {
  font-size: 12.5px;
  color: #6b7280;
  line-height: 1.7;
}

.agree-text a {
  color: #2f8f3d;
  text-decoration: none;
  font-weight: 500;
  cursor: pointer;
}

.agree-text a:hover {
  text-decoration: underline;
}

/* ===== 登录按钮（Element Plus 覆盖） ===== */
.login-submit.el-button {
  width: 100%;
  height: 48px;
  margin-top: 26px;
  border: none;
  border-radius: 10px;
  cursor: pointer;
  color: #ffffff;
  font-size: 16px;
  font-weight: 600;
  letter-spacing: 6px;
  text-indent: 6px;
  --el-button-bg-color: #3fa84b;
  --el-button-border-color: #3fa84b;
  --el-button-hover-bg-color: #389b44;
  --el-button-hover-border-color: #389b44;
  --el-button-active-bg-color: #338f3e;
  --el-button-active-border-color: #338f3e;
  background-color: #3fa84b;
  background-image: linear-gradient(180deg, #43b051, #37a048);
  box-shadow: 0 8px 18px rgba(63, 168, 75, 0.30);
  transition: background-color 0.15s, box-shadow 0.15s, transform 0.1s;
}

.login-submit.el-button:hover:not(.is-disabled),
.login-submit.el-button:focus-visible:not(.is-disabled) {
  color: #ffffff;
  background-color: #389b44;
  background-image: linear-gradient(180deg, #3aa548, #2f8f3d);
  box-shadow: 0 10px 22px rgba(63, 168, 75, 0.34);
}

.login-submit.el-button:active:not(.is-disabled) {
  transform: translateY(1px);
  box-shadow: 0 4px 10px rgba(63, 168, 75, 0.26);
}

/* 协议未勾选时按钮禁用态：降透明度（设计 §8.2 配合协议门槛） */
.login-submit.el-button.is-disabled,
.login-submit.el-button:disabled {
  opacity: 0.55;
  cursor: not-allowed;
  background-image: linear-gradient(180deg, #43b051, #37a048);
  box-shadow: none;
}

/* ===== 卡片脚注 ===== */
.card-foot {
  margin-top: 22px;
  text-align: center;
  font-size: 12px;
  color: #9aa1ab;
}

/* ===== 响应式（设计 §8.3） ===== */
@media (max-width: 1024px) {
  .login-main {
    flex-direction: column;
    gap: 40px;
    padding: 40px 24px;
  }
  .login-brand {
    flex: none;
    width: 100%;
  }
  .brand-art {
    width: min(340px, 80%);
  }
  .brand-title {
    font-size: 34px;
  }
  .brand-sub {
    white-space: normal;
  }
  .login-panel {
    flex: none;
    width: 100%;
  }
  .login-card {
    max-width: 420px;
  }
}

@media (max-width: 560px) {
  .brand-title {
    font-size: 26px;
    white-space: normal;
  }
  .brand-title .gap {
    width: 1.5em;
  }
  .brand-sub {
    font-size: 13px;
    letter-spacing: 0.1em;
    padding-left: 0.1em;
  }
  .login-card {
    padding: 32px 24px 26px;
  }
}
</style>
