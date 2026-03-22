<template>
  <div v-if="userStore.isAdmin" class="app-page admin-users-page">
    <el-card class="users-card" shadow="never">
      <template #header>
        <div class="card-header">
          <div>
            <h3>用户信息列表</h3>
            <p>查看用户资料、通知设置和账号启用状态。</p>
          </div>
          <div class="header-actions">
            <el-button type="primary" @click="openBroadcastDialog">
              群发通知
            </el-button>
            <el-button :icon="Refresh" @click="loadUsers" :loading="loading" round>刷新</el-button>
          </div>
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

    <el-dialog
      v-model="broadcastDialogVisible"
      title="群发通知"
      width="640px"
      destroy-on-close
    >
      <el-alert
        type="info"
        :closable="false"
        class="broadcast-alert"
        title="邮件将发送给所有已绑定邮箱且账号启用的用户，忽略个人邮件通知开关。"
      />
      <el-form label-width="88px" :model="broadcastForm">
        <el-form-item label="邮件主题">
          <el-input
            v-model="broadcastForm.subject"
            maxlength="120"
            show-word-limit
            placeholder="例如：系统维护通知"
          />
        </el-form-item>
        <el-form-item label="邮件正文">
          <el-input
            v-model="broadcastForm.body"
            type="textarea"
            :rows="8"
            maxlength="5000"
            show-word-limit
            placeholder="输入要发送给所有用户的通知内容"
          />
        </el-form-item>
      </el-form>
      <div class="recipient-hint">
        预计发送 {{ eligibleRecipientCount }} 人
      </div>
      <el-alert
        v-if="broadcastResult"
        :type="broadcastResult.failed_count > 0 ? 'warning' : 'success'"
        :closable="false"
        class="broadcast-result"
        :title="`发送完成：成功 ${broadcastResult.sent_count} 人，失败 ${broadcastResult.failed_count} 人`"
      />
      <div v-if="broadcastResult?.failures.length" class="failure-panel">
        <div class="failure-title">失败列表</div>
        <div
          v-for="failure in broadcastResult.failures"
          :key="`${failure.user_id}-${failure.email}`"
          class="failure-item"
        >
          {{ failure.username }}（{{ failure.email }}）：{{ failure.error }}
        </div>
      </div>
      <template #footer>
        <div class="dialog-actions">
          <el-button @click="closeBroadcastDialog">取消</el-button>
          <el-button
            type="primary"
            :loading="broadcastSending"
            :disabled="eligibleRecipientCount === 0"
            @click="submitBroadcast"
          >
            发送通知
          </el-button>
        </div>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { Refresh } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { adminApi } from '../api'
import { useUserStore } from '../stores/user'

type AdminUserRow = {
  id: number
  username: string
  email?: string | null
  email_notify: boolean
  notify_on: string
  role: string
  is_active: boolean
  created_at: string
}

type BroadcastFailure = {
  user_id: number
  username: string
  email: string
  error: string
}

type BroadcastResult = {
  recipient_count: number
  sent_count: number
  failed_count: number
  failures: BroadcastFailure[]
  operation_log_id: number
}

const userStore = useUserStore()
const users = ref<AdminUserRow[]>([])
const loading = ref(false)
const broadcastDialogVisible = ref(false)
const broadcastSending = ref(false)
const broadcastResult = ref<BroadcastResult | null>(null)
const broadcastForm = reactive({
  subject: '',
  body: '',
})

const eligibleRecipientCount = computed(() => {
  // 这里统计的是“管理员公告”收件范围，不是签到通知偏好。
  // 若误把 email_notify / notify_on 也混进来，管理员会看到人数和实际发送对象对不上，排障会非常混乱。
  return users.value.filter((user) => user.is_active && (user.email || '').trim()).length
})

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

async function toggleUser(user: AdminUserRow) {
  try {
    await adminApi.toggleUser(user.id)
    ElMessage.success(`用户已${user.is_active ? '禁用' : '启用'}`)
    await loadUsers()
  } catch (e) {
    // 错误已在拦截器中处理
  }
}

function resetBroadcastState() {
  broadcastForm.subject = ''
  broadcastForm.body = ''
  broadcastResult.value = null
  broadcastSending.value = false
}

function openBroadcastDialog() {
  resetBroadcastState()
  broadcastDialogVisible.value = true
}

function closeBroadcastDialog() {
  broadcastDialogVisible.value = false
  resetBroadcastState()
}

async function submitBroadcast() {
  if (!broadcastForm.subject.trim()) {
    ElMessage.warning('请填写邮件主题')
    return
  }
  if (!broadcastForm.body.trim()) {
    ElMessage.warning('请填写邮件正文')
    return
  }

  broadcastSending.value = true
  try {
    const { data } = await adminApi.broadcastEmail({
      subject: broadcastForm.subject,
      body: broadcastForm.body,
    })
    broadcastResult.value = data
    ElMessage.success(`群发完成，成功 ${data.sent_count} 人`)
  } finally {
    broadcastSending.value = false
  }
}

onMounted(loadUsers)
</script>

<style scoped>
.admin-users-page {
  width: 100%;
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

.header-actions {
  display: flex;
  gap: 12px;
  flex-wrap: wrap;
  justify-content: flex-end;
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

.broadcast-alert,
.broadcast-result {
  margin-bottom: 16px;
}

.recipient-hint {
  margin-top: -4px;
  margin-bottom: 16px;
  font-size: 13px;
  color: var(--text-secondary);
}

.failure-panel {
  border: 1px solid var(--border-color);
  border-radius: 12px;
  padding: 14px 16px;
  background: var(--surface-raised, rgba(255, 255, 255, 0.72));
}

.failure-title {
  margin-bottom: 10px;
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary);
}

.failure-item {
  font-size: 13px;
  line-height: 1.7;
  color: var(--text-secondary);
  word-break: break-word;
}

.dialog-actions {
  display: flex;
  justify-content: flex-end;
}

@media (max-width: 768px) {
  .card-header {
    flex-direction: column;
    align-items: stretch;
  }

  .header-actions {
    justify-content: stretch;
  }
}
</style>
