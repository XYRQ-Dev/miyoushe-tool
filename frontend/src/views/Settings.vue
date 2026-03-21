<template>
  <div class="app-page settings-page">
    <el-card class="settings-card panel-card" shadow="never">
      <template #header>
        <div class="section-head">
          <div>
            <div class="section-title">个人设置</div>
            <div class="section-desc">更新通知邮箱和通知策略，控制个人级消息接收方式。</div>
          </div>
          <el-icon class="section-icon"><User /></el-icon>
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

    <el-card class="settings-card panel-card" shadow="never">
      <template #header>
        <div class="section-head">
          <div>
            <div class="section-title">签到调度</div>
            <div class="section-desc">控制自动签到是否启用、何时执行，以及调度任务是否在后端正常注册。</div>
          </div>
          <el-icon class="section-icon"><Clock /></el-icon>
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
        <el-form-item v-if="taskForm.is_enabled && taskForm.scheduler_error">
          <el-alert
            type="error"
            :closable="false"
            :title="`调度任务注册失败：${taskForm.scheduler_error}`"
          />
        </el-form-item>
        <el-form-item v-else-if="taskForm.is_enabled && !taskForm.job_registered">
          <el-alert
            type="warning"
            :closable="false"
            title="自动签到已启用，但当前后端没有注册成功的调度任务。请重新保存配置，若仍失败请检查后端日志。"
          />
        </el-form-item>
        <el-form-item v-else-if="taskForm.is_enabled">
          <div class="schedule-status">
            <div>调度任务已注册：{{ taskForm.job_id || '-' }}</div>
            <div>下次执行时间：{{ formatScheduleTime(taskForm.next_run_time) }}</div>
            <div class="form-hint">
              到达 Cron 时间后，系统可能会在 1 分钟内随机执行，以分散请求，因此实际签到日志可能略晚出现。
            </div>
          </div>
        </el-form-item>
      </el-form>
    </el-card>

    <el-card class="settings-card panel-card" shadow="never">
      <template #header>
        <div class="section-head">
          <div>
            <div class="section-title">外观设置</div>
            <div class="section-desc">选择你习惯的界面模式，设置会立即生效。</div>
          </div>
          <el-icon class="section-icon"><Sunny /></el-icon>
        </div>
      </template>

      <el-form label-width="120px">
        <el-form-item label="深色模式">
          <el-switch
            :model-value="userStore.darkMode"
            @change="userStore.setDarkMode"
            active-text="开启"
            inactive-text="关闭"
          />
        </el-form-item>
      </el-form>
    </el-card>

    <el-card v-if="userStore.isAdmin" class="settings-card panel-card" shadow="never">
      <template #header>
        <div class="section-head">
          <div>
            <div class="section-title">系统邮件配置</div>
            <div class="section-desc">管理员可配置系统发信用的 SMTP 信息。</div>
          </div>
          <el-icon class="section-icon"><Message /></el-icon>
        </div>
      </template>

      <el-alert
        type="info"
        :closable="false"
        class="admin-alert"
        title="这里的邮箱用于系统发信；用户个人设置里的通知邮箱决定邮件发给谁。"
      />

      <el-form label-width="140px" :model="emailSettingsForm">
        <el-form-item label="启用系统邮件">
          <el-switch v-model="emailSettingsForm.smtp_enabled" />
        </el-form-item>
        <el-form-item label="SMTP 主机">
          <el-input v-model="emailSettingsForm.smtp_host" placeholder="smtp.example.com" />
        </el-form-item>
        <el-form-item label="端口">
          <el-input-number v-model="emailSettingsForm.smtp_port" :min="1" :max="65535" />
        </el-form-item>
        <el-form-item label="用户名">
          <el-input v-model="emailSettingsForm.smtp_user" placeholder="mailer@example.com" />
        </el-form-item>
        <el-form-item label="密码">
          <el-input
            v-model="emailSettingsForm.smtp_password"
            type="password"
            show-password
            placeholder="留空表示不修改现有密码"
          />
          <span v-if="emailSettingsForm.smtp_password_configured" class="form-hint">
            当前已保存密码，留空即可保持不变
          </span>
        </el-form-item>
        <el-form-item label="发件人名称">
          <el-input v-model="emailSettingsForm.smtp_sender_name" placeholder="米游社签到助手" />
        </el-form-item>
        <el-form-item label="发件人邮箱">
          <el-input v-model="emailSettingsForm.smtp_sender_email" placeholder="mailer@example.com" />
        </el-form-item>
        <el-form-item label="SSL/TLS">
          <el-switch v-model="emailSettingsForm.smtp_use_ssl" />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" :loading="savingEmailSettings" @click="saveEmailSettings">
            保存邮件配置
          </el-button>
        </el-form-item>
      </el-form>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, onMounted } from 'vue'
import { User, Clock, Sunny, Message } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { useUserStore } from '../stores/user'
import { authApi, taskApi, adminApi } from '../api'

const userStore = useUserStore()
const saving = ref(false)
const savingTask = ref(false)
const savingEmailSettings = ref(false)

const userForm = reactive({
  email: '',
  email_notify: true,
  notify_on: 'always',
})

const taskForm = reactive({
  cron_expr: '0 6 * * *',
  is_enabled: true,
  job_registered: false,
  job_id: '',
  next_run_time: '',
  scheduler_error: '',
})

const emailSettingsForm = reactive({
  smtp_enabled: false,
  smtp_host: '',
  smtp_port: 465,
  smtp_user: '',
  smtp_password: '',
  smtp_use_ssl: true,
  smtp_sender_name: '',
  smtp_sender_email: '',
  smtp_password_configured: false,
})

async function loadSettings() {
  await userStore.ensureUserInfoLoaded()

  // 加载用户信息
  if (userStore.userInfo) {
    userForm.email = userStore.userInfo.email || ''
    userForm.email_notify = userStore.userInfo.email_notify
    userForm.notify_on = userStore.userInfo.notify_on
  }

  // 加载签到配置
  try {
    const { data } = await taskApi.getConfig()
    syncTaskForm(data)
  } catch (e) {
    // 忽略
  }

  // 管理员加载用户列表
  if (userStore.isAdmin) {
    try {
      const { data: emailSettings } = await adminApi.getEmailSettings()
      Object.assign(emailSettingsForm, emailSettings, { smtp_password: '' })
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
    const { data } = await taskApi.updateConfig({
      cron_expr: taskForm.cron_expr,
      is_enabled: taskForm.is_enabled,
    })
    syncTaskForm(data)
    ElMessage.success('调度配置已保存')
  } finally {
    savingTask.value = false
  }
}

function syncTaskForm(data: {
  cron_expr: string
  is_enabled: boolean
  job_registered?: boolean
  job_id?: string | null
  next_run_time?: string | null
  scheduler_error?: string | null
}) {
  taskForm.cron_expr = data.cron_expr
  taskForm.is_enabled = data.is_enabled
  taskForm.job_registered = Boolean(data.job_registered)
  taskForm.job_id = data.job_id || ''
  taskForm.next_run_time = data.next_run_time || ''
  taskForm.scheduler_error = data.scheduler_error || ''
}

function formatScheduleTime(value?: string) {
  if (!value) return '-'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString('zh-CN')
}

async function saveEmailSettings() {
  savingEmailSettings.value = true
  try {
    const payload = {
      smtp_enabled: emailSettingsForm.smtp_enabled,
      smtp_host: emailSettingsForm.smtp_host,
      smtp_port: emailSettingsForm.smtp_port,
      smtp_user: emailSettingsForm.smtp_user,
      smtp_password: emailSettingsForm.smtp_password || undefined,
      smtp_use_ssl: emailSettingsForm.smtp_use_ssl,
      smtp_sender_name: emailSettingsForm.smtp_sender_name,
      smtp_sender_email: emailSettingsForm.smtp_sender_email,
    }
    const { data } = await adminApi.updateEmailSettings(payload)
    Object.assign(emailSettingsForm, data, { smtp_password: '' })
    ElMessage.success('系统邮件配置已保存')
  } finally {
    savingEmailSettings.value = false
  }
}

onMounted(loadSettings)
</script>

<style scoped>
.settings-page {
  width: min(980px, 100%);
}

.settings-card {
  overflow: hidden;
}

.section-icon {
  font-size: 18px;
  color: var(--brand-secondary);
  flex: 0 0 auto;
}

.form-hint {
  display: inline-block;
  margin-left: 12px;
  font-size: 12px;
  color: var(--text-secondary);
  line-height: 1.7;
}

.schedule-status {
  display: flex;
  flex-direction: column;
  gap: 6px;
  line-height: 1.6;
}

.admin-alert {
  margin-bottom: 16px;
}

@media (max-width: 768px) {
  .settings-page {
    width: 100%;
  }

  .settings-card :deep(.el-form) {
    --el-form-label-width: 100px;
  }

  .settings-card :deep(.el-space) {
    flex-wrap: wrap;
  }
}
</style>
