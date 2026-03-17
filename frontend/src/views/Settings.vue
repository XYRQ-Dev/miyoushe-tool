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
            :model-value="userStore.darkMode"
            @change="userStore.setDarkMode"
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
          <el-icon><Message /></el-icon>
          <span>系统邮件配置（管理员）</span>
        </div>
      </template>

      <el-alert
        type="info"
        :closable="false"
        class="admin-alert"
        title="这里配置的是系统发信 SMTP；用户个人设置里的通知邮箱只决定邮件发给谁。"
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
    await taskApi.updateConfig(taskForm)
    ElMessage.success('调度配置已保存')
  } finally {
    savingTask.value = false
  }
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
  max-width: 880px;
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

.admin-alert {
  margin-bottom: 16px;
}

@media (max-width: 768px) {
  .settings-page {
    max-width: none;
  }

  .settings-card :deep(.el-form) {
    --el-form-label-width: 100px;
  }

  .settings-card :deep(.el-space) {
    flex-wrap: wrap;
  }
}
</style>
