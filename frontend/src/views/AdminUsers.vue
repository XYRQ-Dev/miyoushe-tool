<template>
  <div v-if="userStore.isAdmin" class="admin-users-page">
    <el-card class="users-card" shadow="never">
      <template #header>
        <div class="card-header">
          <div>
            <h3>用户信息列表</h3>
            <p>查看所有用户的基础资料与通知配置，并管理账号启用状态。</p>
          </div>
          <el-button :icon="Refresh" @click="loadUsers" :loading="loading" round>刷新</el-button>
        </div>
      </template>

      <!--
        管理员用户列表包含多个短标签列。如果继续使用默认 fixed table-layout，再叠加较紧的固定宽度，
        浏览器会在中等窗口下把单元格压缩得过窄，最终把“管理员 / 正常 / 已开启”这类短文本拆成逐字换行。
        这里显式改为 auto 布局，并给相关列保留最小宽度，避免后续再因为新增列或容器宽度变化把标签挤坏。
      -->
      <el-table :data="users" stripe table-layout="auto">
        <el-table-column label="用户名" prop="username" min-width="140" />
        <el-table-column label="邮箱" min-width="220">
          <template #default="{ row }">
            {{ row.email || '-' }}
          </template>
        </el-table-column>
        <el-table-column label="邮件通知" min-width="120" align="center">
          <template #default="{ row }">
            <el-tag :type="row.email_notify ? 'success' : 'info'" size="small" class="compact-tag">
              {{ row.email_notify ? '已开启' : '已关闭' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="通知策略" min-width="140" align="center">
          <template #default="{ row }">
            <span class="compact-text">
              {{ row.notify_on === 'failure_only' ? '仅失败时通知' : '每次都通知' }}
            </span>
          </template>
        </el-table-column>
        <el-table-column label="角色" min-width="110" align="center">
          <template #default="{ row }">
            <el-tag :type="row.role === 'admin' ? 'danger' : 'info'" size="small" class="compact-tag">
              {{ row.role === 'admin' ? '管理员' : '用户' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="状态" min-width="110" align="center">
          <template #default="{ row }">
            <el-tag :type="row.is_active ? 'success' : 'danger'" size="small" class="compact-tag">
              {{ row.is_active ? '正常' : '已禁用' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="注册时间" width="180">
          <template #default="{ row }">
            {{ new Date(row.created_at).toLocaleString('zh-CN') }}
          </template>
        </el-table-column>
        <el-table-column label="操作" width="120" align="center">
          <template #default="{ row }">
            <el-button
              v-if="row.id !== userStore.userInfo?.id"
              size="small"
              :type="row.is_active ? 'danger' : 'success'"
              @click="toggleUser(row)"
            >
              {{ row.is_active ? '禁用' : '启用' }}
            </el-button>
            <span v-else class="self-tip">当前账号</span>
          </template>
        </el-table-column>
      </el-table>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { Refresh } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { adminApi } from '../api'
import { useUserStore } from '../stores/user'

const userStore = useUserStore()
const users = ref<any[]>([])
const loading = ref(false)

async function loadUsers() {
  if (!userStore.isAdmin) {
    users.value = []
    return
  }

  loading.value = true
  try {
    const { data } = await adminApi.listUsers()
    users.value = data
  } finally {
    loading.value = false
  }
}

async function toggleUser(user: any) {
  try {
    await adminApi.toggleUser(user.id)
    ElMessage.success(`用户已${user.is_active ? '禁用' : '启用'}`)
    await loadUsers()
  } catch (e) {
    // 错误已在拦截器中处理
  }
}

onMounted(loadUsers)
</script>

<style scoped>
.admin-users-page {
  max-width: 1280px;
  margin: 0 auto;
}

.users-card {
  border-radius: 16px;
  border: 1px solid var(--border-color);
}

.card-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
}

.card-header h3 {
  margin: 0;
  font-size: 18px;
  color: var(--text-primary);
}

.card-header p {
  margin: 6px 0 0;
  font-size: 13px;
  color: var(--text-secondary);
}

.self-tip {
  font-size: 12px;
  color: var(--text-secondary);
}

.compact-text {
  display: inline-block;
  white-space: nowrap;
  word-break: keep-all;
}

.compact-tag {
  white-space: nowrap;
}

.compact-tag :deep(.el-tag__content) {
  white-space: nowrap;
  word-break: keep-all;
}

@media (max-width: 768px) {
  .card-header {
    flex-direction: column;
    align-items: stretch;
  }
}
</style>
