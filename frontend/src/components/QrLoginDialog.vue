<template>
  <el-dialog
    :model-value="visible"
    @update:model-value="$emit('update:visible', $event)"
    :title="dialogTitle"
    width="min(460px, 95%)"
    :close-on-click-modal="false"
    @close="handleDialogClose"
    align-center
  >
    <el-tabs v-model="activeTab" class="login-tabs" stretch>
      <el-tab-pane label="扫码登录" name="qr">
        <div class="qr-container">
          <div v-if="status === 'initializing'" class="qr-loading">
            <el-icon class="loading-icon" :size="40"><Loading /></el-icon>
            <p>正在初始化高权限登录...</p>
          </div>

          <div v-else-if="status === 'qr_ready' || status === 'scanned'" class="qr-code">
            <img v-if="qrImage" :src="'data:image/png;base64,' + qrImage" alt="高权限登录二维码" />
            <div v-if="status === 'scanned'" class="scanned-overlay">
              <el-icon :size="40" color="var(--color-success)"><CircleCheck /></el-icon>
              <p>已扫码，请在 App 内确认</p>
            </div>
          </div>

          <div v-else-if="status === 'success'" class="qr-success">
            <el-icon :size="48" color="var(--color-success)"><CircleCheck /></el-icon>
            <p>登录成功</p>
            <p class="sub-text">
              {{ rolesCount > 0 ? `已同步 ${rolesCount} 个游戏角色` : '正在刷新账号列表' }}
            </p>
          </div>

          <div v-else-if="status === 'failed' || status === 'timeout'" class="qr-error">
            <el-icon :size="48" color="var(--color-danger)"><CircleClose /></el-icon>
            <p>{{ errorMessage || '登录失败' }}</p>
            <el-button type="primary" size="small" @click="startQrLogin" round>重新获取</el-button>
          </div>

          <div v-if="status === 'qr_ready'" class="qr-hint">
            <p>使用米游社 App 扫码</p>
            <p class="timeout-hint">有效期 3 分钟</p>
          </div>
        </div>
      </el-tab-pane>

      <el-tab-pane label="短信登录" name="sms">
        <div class="sms-container">
          <el-alert
            type="warning"
            :closable="false"
            show-icon
            title="短信登录仅用于凭据校验"
          >
            校验通过后，请切回扫码页签完成绑定。
          </el-alert>

          <el-form label-position="top" class="sms-form">
            <el-form-item label="手机号">
              <el-input
                v-model="smsForm.mobile"
                maxlength="11"
                placeholder="米游社绑定手机号"
              />
            </el-form-item>

            <el-form-item label="验证码">
              <el-input
                v-model="smsForm.captcha"
                maxlength="8"
                placeholder="短信验证码"
              >
                <template #append>
                  <el-button :loading="smsCaptchaSending" @click="handleSendSmsCaptcha">
                    获取
                  </el-button>
                </template>
              </el-input>
            </el-form-item>

            <div class="sms-actions">
              <el-button
                type="primary"
                :loading="smsVerifying"
                :disabled="!canVerifySms"
                @click="handleVerifySms"
              >
                校验凭据
              </el-button>
              <el-button @click="switchToQrTab">返回扫码</el-button>
            </div>
          </el-form>

          <div v-if="smsVerifyResult" class="sms-result">
            <div class="sms-result-head">
              <el-icon :size="24" color="var(--color-success)"><CircleCheck /></el-icon>
              <div class="sms-result-title">校验成功</div>
            </div>
            <div class="sms-result-grid">
              <div class="result-item">
                <span class="result-label">UID</span>
                <span class="result-value">{{ smsVerifyResult.stuid || '-' }}</span>
              </div>
              <div class="result-item">
                <span class="result-label">MID</span>
                <span class="result-value">{{ smsVerifyResult.mid || '-' }}</span>
              </div>
            </div>
          </div>
        </div>
      </el-tab-pane>
    </el-tabs>
  </el-dialog>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { Loading, CircleCheck, CircleClose } from '@element-plus/icons-vue'
import { accountApi } from '../api'
import { useUserStore } from '../stores/user'

type QrStatus = 'initializing' | 'qr_ready' | 'scanned' | 'success' | 'failed' | 'timeout'
type LoginTab = 'qr' | 'sms'
type SmsVerifyResult = {
  stuid?: string
  mid?: string
  login_ticket?: string
  credential_source?: string
}

const props = defineProps<{
  visible: boolean
  sessionId: string
  accountId?: number | null
}>()

const emit = defineEmits(['update:visible', 'success'])

const userStore = useUserStore()
const activeTab = ref<LoginTab>('qr')
const status = ref<QrStatus>('initializing')
const qrImage = ref('')
const errorMessage = ref('')
const rolesCount = ref(0)
const smsForm = ref({
  mobile: '',
  captcha: '',
  aigis: '',
})
const smsCaptchaSending = ref(false)
const smsVerifying = ref(false)
const smsCaptchaMessage = ref('')
const smsActionType = ref('')
const smsVerifyResult = ref<SmsVerifyResult | null>(null)
const dialogTitle = computed(() => (props.accountId ? '升级高权限登录态' : '添加高权限账号'))
const canVerifySms = computed(() => Boolean(
  smsForm.value.mobile.trim() &&
  smsForm.value.captcha.trim() &&
  smsActionType.value
))

let ws: WebSocket | null = null
let successTimer: number | null = null

function getDisplayErrorMessage(message: string) {
  if (message.includes('未进入扫码登录界面')) {
    return '未切换到高权限登录二维码，请重试'
  }
  if (message.includes('未找到二维码')) {
    return '未找到高权限登录二维码，请重试'
  }
  if (message.includes('未找到扫码登录入口') || message.includes('登录页结构')) {
    return '高权限登录入口结构已变化，需要更新适配'
  }
  return message || '高权限登录失败'
}

function clearSuccessTimer() {
  if (successTimer !== null) {
    window.clearTimeout(successTimer)
    successTimer = null
  }
}

function cleanupQrSocket() {
  clearSuccessTimer()
  if (ws) {
    ws.onmessage = null
    ws.onerror = null
    ws.onclose = null
    ws.close()
    ws = null
  }
}

function resetQrState() {
  cleanupQrSocket()
  status.value = 'initializing'
  qrImage.value = ''
  errorMessage.value = ''
  rolesCount.value = 0
}

function resetSmsState() {
  smsForm.value = {
    mobile: '',
    captcha: '',
    aigis: '',
  }
  smsCaptchaSending.value = false
  smsVerifying.value = false
  smsCaptchaMessage.value = ''
  smsActionType.value = ''
  smsVerifyResult.value = null
}

function resetDialogState() {
  activeTab.value = 'qr'
  resetQrState()
  resetSmsState()
}

function applyQrProgressStatus(nextStatus: string) {
  // 后端轮询协议里的 `pending` 只是“尚未扫码确认”的中间态，不是一个可直接展示的 UI 状态。
  // 如果这里把它原样覆盖到 `status`，模板分支会匹配不到任何内容，表现成“二维码显示几秒后突然消失”。
  // 维护时不要把协议层状态枚举与界面态一一硬绑；二维码图片一旦已经拿到，未扫码阶段就应持续保持可见。
  if (nextStatus === 'pending') {
    status.value = qrImage.value ? 'qr_ready' : 'initializing'
    return
  }

  if (nextStatus === 'scanned' || nextStatus === 'success' || nextStatus === 'failed' || nextStatus === 'timeout') {
    status.value = nextStatus
  }
}

function handleDialogClose() {
  resetDialogState()
}

function startQrLogin() {
  if (!props.sessionId) {
    status.value = 'failed'
    errorMessage.value = '缺少高权限登录会话，请关闭弹窗后重试'
    return
  }

  resetQrState()

  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  const host = window.location.host
  const userId = userStore.userInfo?.id || 0
  const query = new URLSearchParams({ user_id: String(userId) })
  if (props.accountId) {
    query.set('account_id', String(props.accountId))
  }
  const wsUrl = `${protocol}//${host}/ws/qr/${props.sessionId}?${query.toString()}`

  ws = new WebSocket(wsUrl)

  ws.onmessage = (event) => {
    const data = JSON.parse(event.data)

    switch (data.type) {
      case 'status':
        applyQrProgressStatus(String(data.status || ''))
        break
      case 'qr_code':
        qrImage.value = data.image
        status.value = 'qr_ready'
        break
      case 'success':
        status.value = 'success'
        rolesCount.value = data.roles_count || 0
        clearSuccessTimer()
        successTimer = window.setTimeout(() => emit('success'), 1500)
        break
      case 'error':
        status.value = 'failed'
        errorMessage.value = getDisplayErrorMessage(data.message || '')
        break
      case 'timeout':
        status.value = 'timeout'
        errorMessage.value = getDisplayErrorMessage(data.message || '')
        break
    }
  }

  ws.onerror = () => {
    status.value = 'failed'
    errorMessage.value = '连接失败，请检查网络'
  }

  ws.onclose = () => {
    if (status.value === 'initializing' || status.value === 'qr_ready') {
      status.value = 'failed'
      errorMessage.value = '连接已断开'
    }
  }
}

function validateMobile() {
  if (!/^1\d{10}$/.test(smsForm.value.mobile.trim())) {
    ElMessage.warning('请输入 11 位中国大陆手机号')
    return false
  }
  return true
}

async function handleSendSmsCaptcha() {
  if (!validateMobile()) return

  smsCaptchaSending.value = true
  try {
    const { data } = await accountApi.createSmsLoginCaptcha({
      mobile: smsForm.value.mobile.trim(),
      aigis: smsForm.value.aigis.trim() || undefined,
    })
    smsActionType.value = data.action_type || ''
    smsForm.value.aigis = data.aigis || smsForm.value.aigis
    smsCaptchaMessage.value = data.message || '验证码已发送'
    ElMessage.success(smsCaptchaMessage.value)
  } finally {
    smsCaptchaSending.value = false
  }
}

async function handleVerifySms() {
  if (!validateMobile()) return
  if (!smsActionType.value) {
    ElMessage.warning('请先发送验证码，使用服务端返回的动作标识完成校验')
    return
  }

  smsVerifying.value = true
  try {
    const { data } = await accountApi.verifySmsLogin({
      mobile: smsForm.value.mobile.trim(),
      captcha: smsForm.value.captcha.trim(),
      action_type: smsActionType.value,
      aigis: smsForm.value.aigis.trim() || undefined,
    })
    // 短信验证码接口当前只返回根凭据，不负责账号持久化。
    // 这里如果直接 emit success 或刷新账号列表，会把“验证码通过”误展示成“账号已绑定/已升级”，
    // 后续排障时用户和维护者都会被这个假成功态误导。
    smsVerifyResult.value = {
      stuid: data.stuid,
      mid: data.mid,
      login_ticket: data.login_ticket,
      credential_source: data.credential_source,
    }
    ElMessage.success('高权限根凭据已校验，请继续使用二维码完成账号绑定或升级')
  } finally {
    smsVerifying.value = false
  }
}

function switchToQrTab() {
  activeTab.value = 'qr'
}

watch(() => props.visible, (visible) => {
  if (visible) {
    resetDialogState()
    startQrLogin()
    return
  }
  resetDialogState()
})

watch(activeTab, (tab) => {
  if (!props.visible) return
  if (tab === 'qr') {
    startQrLogin()
    return
  }
  cleanupQrSocket()
})

watch(() => props.sessionId, (nextSessionId, previousSessionId) => {
  if (!props.visible || activeTab.value !== 'qr') return
  if (nextSessionId && nextSessionId !== previousSessionId) {
    startQrLogin()
  }
})
</script>

<style scoped>
.login-tabs {
  margin-top: -10px;
}

.qr-container,
.sms-container {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: var(--space-4) 0;
  min-height: 300px;
  justify-content: center;
}

.qr-loading {
  text-align: center;
  color: var(--text-tertiary);
}

.loading-icon {
  animation: spin 1s linear infinite;
  color: var(--brand-primary);
  margin-bottom: var(--space-4);
}

@keyframes spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

.qr-code {
  position: relative;
  width: 220px;
  height: 220px;
  border-radius: var(--radius-md);
  overflow: hidden;
  border: 1px solid var(--border-soft);
  background: white;
  padding: 8px;
}

.qr-code img {
  width: 100%;
  height: 100%;
  object-fit: contain;
}

.scanned-overlay {
  position: absolute;
  inset: 0;
  background: var(--bg-elevated);
  backdrop-filter: blur(4px);
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 8px;
  text-align: center;
  padding: 20px;
}

.scanned-overlay p {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-primary);
}

.qr-success,
.qr-error {
  text-align: center;
}

.qr-success p,
.qr-error p {
  margin-top: var(--space-3);
  font-size: 16px;
  font-weight: 700;
  color: var(--text-primary);
}

.sub-text {
  font-size: 13px !important;
  font-weight: 500 !important;
  color: var(--text-tertiary) !important;
}

.qr-hint {
  margin-top: var(--space-4);
  text-align: center;
}

.qr-hint p {
  font-size: 13px;
  color: var(--text-secondary);
  margin: 4px 0;
}

.timeout-hint {
  font-size: 11px !important;
  color: var(--text-tertiary) !important;
}

.sms-container {
  align-items: stretch;
  justify-content: flex-start;
  gap: var(--space-4);
}

.sms-form {
  width: 100%;
}

.sms-actions {
  display: flex;
  gap: 12px;
  margin-top: var(--space-2);
}

.sms-actions .el-button {
  flex: 1;
}

.sms-result {
  border-radius: var(--radius-md);
  padding: var(--space-4);
  background: var(--bg-success-soft);
  border: 1px solid var(--border-success-soft);
}

.sms-result-head {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 12px;
}

.sms-result-title {
  font-size: 14px;
  font-weight: 700;
  color: var(--text-success);
}

.sms-result-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
}

.result-item {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.result-label {
  font-size: 11px;
  font-weight: 700;
  color: var(--text-tertiary);
  text-transform: uppercase;
}

.result-value {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-primary);
  font-variant-numeric: tabular-nums;
}

@media (max-width: 480px) {
  .sms-actions {
    flex-direction: column;
  }
}
</style>
