<template>
  <div class="settings-page">
    <!-- 个人设置 -->
    <el-card class="settings-card" shadow="never">
      <template #header>
        <div class="card-title">
          <el-icon><User /></el-icon>
          <span>个人设置</span>
        </div>
      </template>

      <el-form label-width="120px" :model="userForm">
        <el-form-item label="用户名">
          <el-input :value="userStore.userInfo?.username" disabled />
        </el-form-item>
        <el-form-item label="角色">
          <el-tag :type="userStore.isAdmin ? 'danger' : 'info'" size="small">
            {{ userStore.isAdmin ? '管理员' : '普通用户' }}
          </el-tag>
        </el-form-item>
        <el-form-item label="通知邮箱">
          <el-input v-model="userForm.email" placeholder="接收签到通知的邮箱" />
        </el-form-item>
        <el-form-item label="邮件通知">
          <el-switch v-model="userForm.email_notify" />
        </el-form-item>
        <el-form-item label="通知策略">
          <el-radio-group v-model="userForm.notify_on">
            <el-radio value="always">每次都通知</el-radio>
            <el-radio value="failure_only">仅失败时通知</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item>
          <el-button type="primary" @click="saveUserSettings" :loading="saving">
            保存设置
          </el-button>
        </el-form-item>
      </el-form>
    </el-card>

    <!-- 签到调度设置 -->
    <el-card class="settings-card" shadow="never">
      <template #header>
        <div class="card-title">
          <el-icon><Clock /></el-icon>
          <span>签到调度</span>
        </div>
      </template>

      <el-form label-width="120px" :model="taskForm">
        <el-form-item label="启用自动签到">
          <el-switch v-model="taskForm.is_enabled" />
        </el-form-item>
        <el-form-item label="Cron 表达式">
          <el-input
            v-model="taskForm.cron_expr"
            placeholder="0 6 * * *"
            style="width: 200px"
          />
          <span class="form-hint">格式：分 时 日 月 周（例如 0 6 * * * 表示每天 6:00）</span>
        </el-form-item>
        <el-form-item label="常用模板">
          <el-space>
            <el-button size="small" @click="taskForm.cron_expr = '0 6 * * *'">每天 6:00</el-button>
            <el-button size="small" @click="taskForm.cron_expr = '0 8 * * *'">每天 8:00</el-button>
            <el-button size="small" @click="taskForm.cron_expr = '30 7 * * *'">每天 7:30</el-button>
            <el-button size="small" @click="taskForm.cron_expr = '0 12 * * *'">每天 12:00</el-button>
          </el-space>
        </el-form-item>
        <el-form-item>
          <el-button type="primary" @click="saveTaskConfig" :loading="savingTask">
            保存调度配置
          </el-button>
        </el-form-item>
      </el-form>
    </el-card>

    <!-- 外观设置 -->
    <el-card class="settings-card" shadow="never">
      <template #header>
        <div class="card-title">
          <el-icon><Sunny /></el-icon>
          <span>外观设置</span>
        </div>
      </template>

      <el-form label-width="120px">
        <el-form-item label="深色模式">
          <el-switch
            v-model="userStore.darkMode"
            @change="userStore.toggleDarkMode()"
            active-text="开启"
            inactive-text="关闭"
          />
        </el-form-item>
      </el-form>
    </el-card>

    <!-- 管理员区域 -->
    <el-card v-if="userStore.isAdmin" class="settings-card" shadow="never">
      <template #header>
        <div class="card-title">
          <el-icon><Setting /></el-icon>
          <span>用户管理（管理员）</span>
        </div>
      </template>

      <el-table :data="users" stripe>
        <el-table-column label="用户名" prop="username" />
        <el-table-column label="角色" width="100">
          <template #default="{ row }">
            <el-tag :type="row.role === 'admin' ? 'danger' : 'info'" size="small">
              {{ row.role === 'admin' ? '管理员' : '用户' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="100">
          <template #default="{ row }">
            <el-tag :type="row.is_active ? 'success' : 'danger'" size="small">
              {{ row.is_active ? '正常' : '已禁用' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="注册时间" width="180">
          <template #default="{ row }">
            {{ new Date(row.created_at).toLocaleString('zh-CN') }}
          </template>
        </el-table-column>
        <el-table-column label="操作" width="120">
          <template #default="{ row }">
            <el-button
              v-if="row.id !== userStore.userInfo?.id"
              size="small"
              :type="row.is_active ? 'danger' : 'success'"
              @click="toggleUser(row)"
            >
              {{ row.is_active ? '禁用' : '启用' }}
            </el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, onMounted } from 'vue'
import { User, Clock, Sunny, Setting } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { useUserStore } from '../stores/user'
import { authApi, taskApi, adminApi } from '../api'

const userStore = useUserStore()
const saving = ref(false)
const savingTask = ref(false)
const users = ref<any[]>([])

const userForm = reactive({
  email: '',
  email_notify: true,
  notify_on: 'always',
})

const taskForm = reactive({
  cron_expr: '0 6 * * *',
  is_enabled: true,
})

async function loadSettings() {
  // 加载用户信息
  if (userStore.userInfo) {
    userForm.email = userStore.userInfo.email || ''
    userForm.email_notify = userStore.userInfo.email_notify
    userForm.notify_on = userStore.userInfo.notify_on
  }

  // 加载签到配置
  try {
    const { data } = await taskApi.getConfig()
    taskForm.cron_expr = data.cron_expr
    taskForm.is_enabled = data.is_enabled
  } catch (e) {
    // 忽略
  }

  // 管理员加载用户列表
  if (userStore.isAdmin) {
    try {
      const { data } = await adminApi.listUsers()
      users.value = data
    } catch (e) {
      // 忽略
    }
  }
}

async function saveUserSettings() {
  saving.value = true
  try {
    await authApi.updateMe(userForm)
    await userStore.fetchUserInfo()
    ElMessage.success('设置已保存')
  } finally {
    saving.value = false
  }
}

async function saveTaskConfig() {
  savingTask.value = true
  try {
    await taskApi.updateConfig(taskForm)
    ElMessage.success('调度配置已保存')
  } finally {
    savingTask.value = false
  }
}

async function toggleUser(user: any) {
  try {
    await adminApi.toggleUser(user.id)
    ElMessage.success(`用户已${user.is_active ? '禁用' : '启用'}`)
    const { data } = await adminApi.listUsers()
    users.value = data
  } catch (e) {
    // 错误已在拦截器中处理
  }
}

onMounted(loadSettings)
</script>

<style scoped>
.settings-page {
  max-width: 800px;
  margin: 0 auto;
}

.settings-card {
  margin-bottom: 20px;
  border-radius: 16px;
  border: 1px solid var(--border-color);
}

.card-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-weight: 600;
}

.form-hint {
  margin-left: 12px;
  font-size: 12px;
  color: var(--text-secondary);
}
</style>
