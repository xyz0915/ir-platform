<template>
  <div class="whitelist-view">
    <div class="card-box">
      <div class="flex-between mb-16">
        <h2 class="page-title">白名单配置</h2>
        <el-button type="primary" size="small" @click="showAddDialog = true">添加白名单</el-button>
      </div>

      <!-- 类别筛选 -->
      <el-radio-group v-model="categoryFilter" size="small" class="mb-12" @change="loadWhitelist">
        <el-radio-button label="">全部</el-radio-button>
        <el-radio-button label="path">路径</el-radio-button>
        <el-radio-button label="process_name">进程名</el-radio-button>
        <el-radio-button label="signature">签名</el-radio-button>
      </el-radio-group>

      <!-- 白名单表格 -->
      <el-table :data="whitelistData" border stripe size="small" v-loading="loading">
        <el-table-column prop="id" label="ID" width="60" />
        <el-table-column prop="category" label="类别" width="120">
          <template #default="{ row }">
            <el-tag size="small" :type="categoryTagType(row.category)">
              {{ categoryLabel(row.category) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="pattern" label="匹配值" min-width="250" show-overflow-tooltip />
        <el-table-column prop="source" label="来源" width="120">
          <template #default="{ row }">
            <el-tag v-if="row.source === 'default'" type="info" size="small">内置默认</el-tag>
            <el-tag v-else type="success" size="small">用户添加</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="description" label="描述" min-width="180" show-overflow-tooltip />
        <el-table-column prop="enabled" label="启用" width="80">
          <template #default="{ row }">
            <el-switch
              v-model="row.enabled"
              :active-value="1"
              :inactive-value="0"
              @change="handleToggle(row)"
              size="small"
            />
          </template>
        </el-table-column>
        <el-table-column label="操作" width="80">
          <template #default="{ row }">
            <el-popconfirm
              title="确认删除该白名单项？"
              @confirm="handleDelete(row)"
            >
              <template #reference>
                <el-button type="danger" link size="small">删除</el-button>
              </template>
            </el-popconfirm>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <!-- 添加白名单对话框 -->
    <el-dialog
      v-model="showAddDialog"
      title="添加白名单"
      width="500px"
      destroy-on-close
    >
      <el-form :model="addForm" label-width="80px" size="small">
        <el-form-item label="类别">
          <el-select v-model="addForm.category" placeholder="选择类别">
            <el-option label="路径" value="path" />
            <el-option label="进程名" value="process_name" />
            <el-option label="签名" value="signature" />
          </el-select>
        </el-form-item>
        <el-form-item label="匹配值">
          <el-input v-model="addForm.pattern" placeholder="输入白名单匹配值" />
        </el-form-item>
        <el-form-item label="描述">
          <el-input v-model="addForm.description" placeholder="输入描述（可选）" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showAddDialog = false">取消</el-button>
        <el-button type="primary" @click="handleAdd">确定</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import whitelistApi from '@/api/whitelist'

const whitelistData = ref([])
const loading = ref(false)
const categoryFilter = ref('')
const showAddDialog = ref(false)
const addForm = ref({
  category: 'path',
  pattern: '',
  description: ''
})

onMounted(() => {
  loadWhitelist()
})

async function loadWhitelist() {
  loading.value = true
  try {
    const params = {}
    if (categoryFilter.value) {
      params.category = categoryFilter.value
    }
    const res = await whitelistApi.getWhitelist(params)
    whitelistData.value = res.data || []
  } catch (error) {
    // handled
  } finally {
    loading.value = false
  }
}

async function handleAdd() {
  if (!addForm.value.category || !addForm.value.pattern) {
    ElMessage.warning('请填写类别和匹配值')
    return
  }
  try {
    await whitelistApi.createWhitelist({
      category: addForm.value.category,
      pattern: addForm.value.pattern,
      description: addForm.value.description
    })
    ElMessage.success('添加成功')
    showAddDialog.value = false
    addForm.value = { category: 'path', pattern: '', description: '' }
    loadWhitelist()
  } catch (error) {
    // handled
  }
}

async function handleDelete(row) {
  try {
    await whitelistApi.deleteWhitelist(row.id)
    ElMessage.success('删除成功')
    loadWhitelist()
  } catch (error) {
    // handled
  }
}

async function handleToggle(row) {
  try {
    await whitelistApi.updateWhitelist(row.id, { enabled: row.enabled === 1 })
  } catch (error) {
    // revert on error
    row.enabled = row.enabled === 1 ? 0 : 1
  }
}

function categoryLabel(category) {
  const map = { path: '路径', process_name: '进程名', signature: '签名' }
  return map[category] || category
}

function categoryTagType(category) {
  const map = { path: 'primary', process_name: 'success', signature: 'warning' }
  return map[category] || 'info'
}
</script>

<style scoped>
.whitelist-view {
  padding: 0;
}
.card-box {
  background: #fff;
  border-radius: 4px;
  padding: 20px;
}
.flex-between {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.mb-12 {
  margin-bottom: 12px;
}
.mb-16 {
  margin-bottom: 16px;
}
.page-title {
  font-size: 18px;
  font-weight: bold;
  color: #303133;
  margin: 0;
}
</style>
