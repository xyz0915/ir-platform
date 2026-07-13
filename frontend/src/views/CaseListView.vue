<template>
  <div class="page-container">
    <div class="card-box">
      <div class="flex-between mb-20">
        <h2 class="page-title">
          <span class="title-emoji">📁</span>
          <span>案件管理</span>
          <el-tag class="title-tag" type="warning" effect="plain" size="small">🚨 应急核心</el-tag>
        </h2>
        <el-button type="primary" @click="showCreateDialog">
          <el-icon><Plus /></el-icon> 新建案件
        </el-button>
      </div>
      <div class="mb-20">
        <el-input
          v-model="searchQuery"
          placeholder="搜索案件名称或编号"
          style="width: 300px"
          clearable
          @keyup.enter="loadCases"
          @clear="loadCases"
        >
          <template #append>
            <el-button @click="loadCases">
              <el-icon><Search /></el-icon>
            </el-button>
          </template>
        </el-input>
      </div>
      <el-table :data="cases" border stripe v-loading="loading">
        <el-table-column prop="name" label="案件名称" min-width="150" />
        <el-table-column prop="case_number" label="案件编号" width="150" />
        <el-table-column prop="description" label="描述" min-width="200" show-overflow-tooltip />
        <el-table-column prop="status" label="状态" width="100">
          <template #default="{ row }">
            <el-tag :type="row.status === 'open' ? 'success' : 'info'" size="small">
              {{ row.status === 'open' ? '进行中' : '已关闭' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="created_at" label="创建时间" width="180" />
        <el-table-column label="操作" width="180" fixed="right">
          <template #default="{ row }">
            <el-button size="small" @click="goToDetail(row.id)">查看</el-button>
            <el-button size="small" type="danger" @click="handleDelete(row.id)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
      <div class="mt-20 flex-center">
        <el-pagination
          v-model:current-page="currentPage"
          v-model:page-size="pageSize"
          :total="total"
          :page-sizes="[10, 20, 50]"
          layout="total, sizes, prev, pager, next"
          @size-change="loadCases"
          @current-change="loadCases"
        />
      </div>
    </div>

    <!-- 新建案件对话框 -->
    <el-dialog v-model="createDialogVisible" title="新建案件" width="500px">
      <el-form :model="createForm" label-width="80px">
        <el-form-item label="案件名称" required>
          <el-input v-model="createForm.name" placeholder="请输入案件名称" />
        </el-form-item>
        <el-form-item label="案件编号">
          <el-input v-model="createForm.case_number" placeholder="可选，自动分配" />
        </el-form-item>
        <el-form-item label="描述">
          <el-input
            v-model="createForm.description"
            type="textarea"
            :rows="3"
            placeholder="案件描述"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="createDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="creating" @click="handleCreate">创建</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import casesApi from '@/api/cases'

const router = useRouter()

const cases = ref([])
const loading = ref(false)
const searchQuery = ref('')
const currentPage = ref(1)
const pageSize = ref(20)
const total = ref(0)

const createDialogVisible = ref(false)
const creating = ref(false)
const createForm = reactive({
  name: '',
  case_number: '',
  description: ''
})

onMounted(() => {
  loadCases()
})

async function loadCases() {
  loading.value = true
  try {
    const res = await casesApi.list(currentPage.value, pageSize.value, searchQuery.value)
    cases.value = res.data.items
    total.value = res.data.total
  } catch (error) {
    // handled by interceptor
  } finally {
    loading.value = false
  }
}

function showCreateDialog() {
  createForm.name = ''
  createForm.case_number = ''
  createForm.description = ''
  createDialogVisible.value = true
}

async function handleCreate() {
  if (!createForm.name) {
    ElMessage.warning('请输入案件名称')
    return
  }
  creating.value = true
  try {
    await casesApi.create({
      name: createForm.name,
      case_number: createForm.case_number || null,
      description: createForm.description || null
    })
    ElMessage.success('案件创建成功')
    createDialogVisible.value = false
    loadCases()
  } catch (error) {
    // handled
  } finally {
    creating.value = false
  }
}

function goToDetail(id) {
  router.push(`/cases/${id}`)
}

async function handleDelete(id) {
  try {
    await ElMessageBox.confirm('确定要删除此案件吗？删除后不可恢复。', '确认删除', {
      type: 'warning'
    })
    await casesApi.delete(id)
    ElMessage.success('删除成功')
    loadCases()
  } catch (error) {
    // cancelled or error
  }
}
</script>
