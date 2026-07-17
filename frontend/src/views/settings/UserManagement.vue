<template>
  <div class="user-management">
    <div class="page-header">
      <h2>用户与权限</h2>
      <el-button type="primary" @click="openCreateDialog">新增用户</el-button>
    </div>

    <!-- 搜索栏 -->
    <div class="search-bar">
      <el-input
        v-model="searchQuery"
        placeholder="搜索用户名..."
        clearable
        style="width: 260px"
        @input="handleSearch"
      >
        <template #prefix>
          <el-icon><Search /></el-icon>
        </template>
      </el-input>
    </div>

    <!-- 用户列表 -->
    <el-table :data="userList" border stripe style="width: 100%" v-loading="loading">
      <el-table-column label="用户名" min-width="140">
        <template #default="{ row }">
          <div class="user-cell">
            <span class="user-avatar">{{ row.username.charAt(0).toUpperCase() }}</span>
            <span>{{ row.username }}</span>
          </div>
        </template>
      </el-table-column>
      <el-table-column prop="display_name" label="显示名称" min-width="120" />
      <el-table-column label="角色" width="120">
        <template #default="{ row }">
          <el-tag :type="roleTagType(row.role)" size="small">
            {{ roleLabel(row.role) }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="状态" width="100">
        <template #default="{ row }">
          <el-switch
            :model-value="row.is_active === 1"
            :loading="togglingId === row.id"
            @click="toggleActive(row)"
          />
        </template>
      </el-table-column>
      <el-table-column label="最后登录" width="170">
        <template #default="{ row }">
          {{ row.last_login ? formatTime(row.last_login) : '从未登录' }}
        </template>
      </el-table-column>
      <el-table-column label="操作" width="280" fixed="right">
        <template #default="{ row }">
          <el-button text type="primary" size="small" @click="openEditDialog(row)">编辑</el-button>
          <el-button text type="warning" size="small" @click="openResetPasswordDialog(row)">重置密码</el-button>
          <el-button
            text
            :type="row.is_active ? 'warning' : 'success'"
            size="small"
            @click="toggleActive(row)"
          >
            {{ row.is_active ? '禁用' : '启用' }}
          </el-button>
          <el-popconfirm title="确定删除此用户？" @confirm="handleDelete(row)">
            <template #reference>
              <el-button text type="danger" size="small">删除</el-button>
            </template>
          </el-popconfirm>
        </template>
      </el-table-column>
    </el-table>

    <!-- 分页 -->
    <div class="pagination-wrap">
      <el-pagination
        v-model:current-page="currentPage"
        v-model:page-size="pageSize"
        :total="total"
        :page-sizes="[10, 20, 50]"
        layout="total, sizes, prev, pager, next"
        @size-change="fetchUsers"
        @current-change="fetchUsers"
      />
    </div>

    <!-- 新增/编辑对话框 -->
    <el-dialog
      :title="isEditing ? '编辑用户' : '新增用户'"
      v-model="dialogVisible"
      width="450px"
      :close-on-click-modal="false"
    >
      <el-form ref="formRef" :model="formData" :rules="formRules" label-width="100px">
        <el-form-item label="用户名" prop="username">
          <el-input v-model="formData.username" :disabled="isEditing" />
        </el-form-item>
        <el-form-item label="密码" prop="password" v-if="!isEditing">
          <el-input v-model="formData.password" type="password" show-password />
        </el-form-item>
        <el-form-item label="角色" prop="role">
          <el-select v-model="formData.role" style="width: 100%">
            <el-option label="管理员" value="admin" />
            <el-option label="分析师" value="analyst" />
            <el-option label="只读用户" value="readonly" />
          </el-select>
        </el-form-item>
        <el-form-item label="显示名称" prop="display_name">
          <el-input v-model="formData.display_name" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="submitting" @click="handleSubmit">确定</el-button>
      </template>
    </el-dialog>

    <!-- 重置密码对话框 -->
    <el-dialog title="重置密码" v-model="pwdDialogVisible" width="400px">
      <el-form ref="pwdFormRef" :model="pwdForm" :rules="pwdRules" label-width="100px">
        <el-form-item label="新密码" prop="new_password">
          <el-input v-model="pwdForm.new_password" type="password" show-password />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="pwdDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="submitting" @click="handleResetPassword">确定</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { Search } from '@element-plus/icons-vue'
import { getUsers, createUser, updateUser, deleteUser, resetPassword, toggleUserActive } from '@/api/users'

const loading = ref(false)
const submitting = ref(false)
const userList = ref([])
const total = ref(0)
const currentPage = ref(1)
const pageSize = ref(20)
const searchQuery = ref('')
const togglingId = ref(null)
let searchTimer = null

// 对话框状态
const dialogVisible = ref(false)
const isEditing = ref(false)
const editingId = ref(null)
const formRef = ref(null)
const formData = ref({
  username: '',
  password: '',
  role: 'analyst',
  display_name: '',
})
const formRules = {
  username: [{ required: true, message: '请输入用户名', trigger: 'blur' }],
  password: [{ required: true, message: '请输入密码', trigger: 'blur' }],
  role: [{ required: true, message: '请选择角色', trigger: 'change' }],
}

// 重置密码对话框
const pwdDialogVisible = ref(false)
const pwdFormRef = ref(null)
const pwdForm = ref({ new_password: '' })
const resetUserId = ref(null)
const pwdRules = {
  new_password: [{ required: true, message: '请输入新密码', trigger: 'blur' }],
}

function roleTagType(role) {
  if (role === 'admin') return 'danger'
  if (role === 'analyst') return 'success'
  return 'info'
}

function roleLabel(role) {
  const map = { admin: '管理员', analyst: '分析师', readonly: '只读' }
  return map[role] || role
}

function formatTime(val) {
  if (!val) return ''
  const d = new Date(val)
  const pad = (n) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

async function fetchUsers() {
  loading.value = true
  try {
    const params = { page: currentPage.value, page_size: pageSize.value }
    if (searchQuery.value) {
      params.username = searchQuery.value
    }
    const res = await getUsers(params)
    userList.value = res.data.items || []
    total.value = res.data.total || 0
  } catch (e) {
    console.error('获取用户列表失败', e)
  } finally {
    loading.value = false
  }
}

function handleSearch() {
  clearTimeout(searchTimer)
  searchTimer = setTimeout(() => {
    currentPage.value = 1
    fetchUsers()
  }, 300)
}

function openCreateDialog() {
  isEditing.value = false
  editingId.value = null
  formData.value = { username: '', password: '', role: 'analyst', display_name: '' }
  dialogVisible.value = true
}

function openEditDialog(row) {
  isEditing.value = true
  editingId.value = row.id
  formData.value = {
    username: row.username,
    password: '',
    role: row.role,
    display_name: row.display_name || '',
  }
  dialogVisible.value = true
}

async function handleSubmit() {
  const valid = await formRef.value.validate().catch(() => false)
  if (!valid) return
  submitting.value = true
  try {
    if (isEditing.value) {
      await updateUser(editingId.value, {
        display_name: formData.value.display_name,
        role: formData.value.role,
      })
      ElMessage.success('用户信息已更新')
    } else {
      await createUser({
        username: formData.value.username,
        password: formData.value.password,
        role: formData.value.role,
        display_name: formData.value.display_name,
      })
      ElMessage.success('用户已创建')
    }
    dialogVisible.value = false
    fetchUsers()
  } catch (e) {
    console.error('提交失败', e)
  } finally {
    submitting.value = false
  }
}

async function handleDelete(row) {
  try {
    await deleteUser(row.id)
    ElMessage.success('用户已删除')
    fetchUsers()
  } catch (e) {
    console.error('删除失败', e)
  }
}

function openResetPasswordDialog(row) {
  resetUserId.value = row.id
  pwdForm.value = { new_password: '' }
  pwdDialogVisible.value = true
}

async function handleResetPassword() {
  const valid = await pwdFormRef.value.validate().catch(() => false)
  if (!valid) return
  submitting.value = true
  try {
    await resetPassword(resetUserId.value, { new_password: pwdForm.value.new_password })
    ElMessage.success('密码已重置')
    pwdDialogVisible.value = false
  } catch (e) {
    console.error('重置密码失败', e)
  } finally {
    submitting.value = false
  }
}

async function toggleActive(row) {
  togglingId.value = row.id
  try {
    const res = await toggleUserActive(row.id)
    row.is_active = res.data.is_active
    ElMessage.success(row.is_active ? '用户已启用' : '用户已禁用')
  } catch (e) {
    console.error('切换状态失败', e)
  } finally {
    togglingId.value = null
  }
}

onMounted(() => {
  fetchUsers()
})
</script>

<style scoped>
.user-management {
  max-width: 1200px;
}

.page-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
}

.page-header h2 {
  margin: 0;
  font-size: 20px;
  font-weight: 600;
}

.search-bar {
  margin-bottom: 16px;
}

.user-cell {
  display: flex;
  align-items: center;
  gap: 8px;
}

.user-avatar {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  border-radius: 50%;
  background: var(--color-accent-subtle, #ecfdf5);
  color: var(--color-accent-fg, #059669);
  font-size: 13px;
  font-weight: 700;
  flex-shrink: 0;
}

.pagination-wrap {
  display: flex;
  justify-content: flex-end;
  margin-top: 16px;
}
</style>
