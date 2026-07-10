<template>
  <div class="login-container">
    <el-card class="login-card">
      <div class="login-header">
        <el-icon size="40" color="var(--color-accent-fg)"><Shield /></el-icon>
        <h2>个人应急响应平台</h2>
        <p class="subtitle">IR Platform</p>
      </div>
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
      <div class="login-tip">
        <el-text type="info" size="small">默认账号: admin / admin123</el-text>
      </div>
    </el-card>
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
.login-container {
  height: 100%;
  display: flex;
  justify-content: center;
  align-items: center;
  background: var(--color-canvas-subtle);
}

.login-card {
  width: 400px;
  max-width: 90vw;
  padding: 28px;
  background: var(--color-canvas-default);
  border: 1px solid var(--color-border-default);
  border-radius: 12px;
  box-shadow: 0 8px 24px rgba(140, 149, 159, 0.2);
}

.login-header {
  text-align: center;
  margin-bottom: 30px;
}

.login-header h2 {
  margin: 10px 0 5px;
  color: var(--color-fg-default);
}

.login-header .subtitle {
  color: var(--color-fg-muted);
  font-size: 14px;
}

.login-btn {
  width: 100%;
}

.login-tip {
  text-align: center;
  margin-top: 10px;
}
</style>
