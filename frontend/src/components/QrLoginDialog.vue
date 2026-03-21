<template>
  <el-dialog
    :model-value="visible"
    @update:model-value="$emit('update:visible', $event)"
    :title="dialogTitle"
    width="460px"
    :close-on-click-modal="false"
    @close="handleDialogClose"
  >
    <el-tabs v-model="activeTab" class="login-tabs" stretch>
      <el-tab-pane label="高权限登录二维码" name="qr">
        <div class="qr-container">
          <div v-if="status === 'initializing'" class="qr-loading">
            <el-icon class="loading-icon" :size="40"><Loading /></el-icon>
            <p>正在准备高权限登录二维码...</p>
          </div>

          <div v-else-if="status === 'qr_ready' || status === 'scanned'" class="qr-code">
            <img v-if="qrImage" :src="'data:image/png;base64,' + qrImage" alt="高权限登录二维码" />
            <div v-if="status === 'scanned'" class="scanned-overlay">
              <el-icon :size="40" color="#10b981"><CircleCheck /></el-icon>
              <p>已扫码，请在米游社 App 内确认高权限登录</p>
            </div>
          </div>

          <div v-else-if="status === 'success'" class="qr-success">
            <el-icon :size="48" color="#10b981"><CircleCheck /></el-icon>
            <p>已升级高权限登录态</p>
            <p class="sub-text">
              {{ rolesCount > 0 ? `已同步 ${rolesCount} 个游戏角色` : '正在刷新账号列表' }}
            </p>
          </div>

          <div v-else-if="status === 'failed' || status === 'timeout'" class="qr-error">
            <el-icon :size="48" color="#ef4444"><CircleClose /></el-icon>
            <p>{{ errorMessage || '高权限登录失败' }}</p>
            <el-button type="primary" size="small" @click="startQrLogin">重新获取二维码</el-button>
          </div>

          <div v-if="status === 'qr_ready'" class="qr-hint">
            <p>打开米游社 App → 我的 → 左上角扫码</p>
            <p>确认后会直接升级当前账号的高权限登录态</p>
            <p class="timeout-hint">二维码有效期 3 分钟</p>
          </div>
        </div>
      </el-tab-pane>

      <el-tab-pane label="短信验证码登录" name="sms">
        <div class="sms-container">
          <el-alert
            type="warning"
            :closable="false"
            show-icon
            title="短信验证码入口当前只校验高权限根凭据"
            description="验证码通过后，前端不会把它当成“账号已绑定”或“已升级完成”。这是当前后端接口边界：短信登录返回根凭据，但不负责账号落库，因此仍需回到二维码页签完成绑定或升级。"
          />

          <el-form label-position="top" class="sms-form">
            <el-form-item label="手机号">
              <el-input
                v-model="smsForm.mobile"
                maxlength="11"
                placeholder="请输入米游社绑定手机号"
              />
            </el-form-item>

            <el-form-item label="短信验证码">
              <el-input
                v-model="smsForm.captcha"
                maxlength="8"
                placeholder="请输入短信验证码"
              >
                <template #append>
                  <el-button :loading="smsCaptchaSending" @click="handleSendSmsCaptcha">
                    发送验证码
                  </el-button>
                </template>
              </el-input>
              <div v-if="smsCaptchaMessage" class="form-hint">{{ smsCaptchaMessage }}</div>
            </el-form-item>

            <el-form-item label="Aigis 风控透传参数（可选）">
              <el-input
                v-model="smsForm.aigis"
                placeholder="如服务端要求风控透传，可在此填写或保留后端回传值"
              />
            </el-form-item>

            <div class="sms-actions">
              <el-button
                type="primary"
                :loading="smsVerifying"
                :disabled="!canVerifySms"
                @click="handleVerifySms"
              >
                校验高权限根凭据
              </el-button>
              <el-button @click="switchToQrTab">改用二维码完成绑定</el-button>
            </div>
          </el-form>

          <div v-if="smsVerifyResult" class="sms-result">
            <div class="sms-result-head">
              <el-icon :size="28" color="#10b981"><CircleCheck /></el-icon>
              <div>
                <div class="sms-result-title">高权限根凭据校验成功</div>
                <div class="sms-result-desc">
                  当前仅确认短信登录拿到了 Passport 根凭据；账号列表不会自动新增或升级。
                  请切回二维码页签完成{{ accountId ? '当前账号的高权限升级' : '账号绑定' }}。
                </div>
              </div>
            </div>

            <div class="sms-result-grid">
              <div class="result-item">
                <span class="result-label">米哈游通行证 UID</span>
                <span class="result-value">{{ smsVerifyResult.stuid || '-' }}</span>
              </div>
              <div class="result-item">
                <span class="result-label">MID</span>
                <span class="result-value">{{ smsVerifyResult.mid || '-' }}</span>
              </div>
              <div class="result-item">
                <span class="result-label">凭据来源</span>
                <span class="result-value">{{ smsVerifyResult.credential_source || 'passport_sms' }}</span>
              </div>
              <div class="result-item">
                <span class="result-label">Login Ticket</span>
                <span class="result-value">{{ smsVerifyResult.login_ticket || '-' }}</span>
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
  padding: 12px 8px 8px;
  min-height: 320px;
  justify-content: center;
}

.qr-loading {
  text-align: center;
  color: var(--text-secondary);
}

.loading-icon {
  animation: spin 1s linear infinite;
  color: var(--primary-color);
  margin-bottom: 16px;
}

@keyframes spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

.qr-code {
  position: relative;
  width: 240px;
  height: 240px;
  border-radius: 12px;
  overflow: hidden;
  border: 2px solid var(--border-color);
}

.qr-code img {
  width: 100%;
  height: 100%;
  object-fit: contain;
}

.scanned-overlay {
  position: absolute;
  inset: 0;
  background: rgba(255, 255, 255, 0.9);
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 8px;
}

:global(html.dark) .scanned-overlay {
  background: rgba(30, 41, 59, 0.9);
}

.qr-success,
.qr-error {
  text-align: center;
}

.qr-success p,
.qr-error p {
  margin-top: 12px;
  font-size: 16px;
  font-weight: 600;
  color: var(--text-primary);
}

.sub-text {
  font-size: 13px !important;
  font-weight: 400 !important;
  color: var(--text-secondary) !important;
}

.qr-hint {
  margin-top: 20px;
  text-align: center;
}

.qr-hint p {
  font-size: 13px;
  color: var(--text-secondary);
  margin: 4px 0;
}

.timeout-hint {
  font-size: 12px !important;
  opacity: 0.7;
}

.sms-container {
  align-items: stretch;
  justify-content: flex-start;
  gap: 16px;
}

.sms-form {
  width: 100%;
}

.sms-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
}

.form-hint {
  margin-top: 8px;
  font-size: 12px;
  line-height: 1.6;
  color: var(--text-secondary);
}

.sms-result {
  border-radius: 16px;
  padding: 16px;
  background: linear-gradient(135deg, rgba(236, 253, 245, 0.95), rgba(220, 252, 231, 0.86));
  border: 1px solid rgba(16, 185, 129, 0.18);
}

.sms-result-head {
  display: flex;
  align-items: flex-start;
  gap: 12px;
}

.sms-result-title {
  font-size: 15px;
  font-weight: 700;
  color: var(--text-primary);
}

.sms-result-desc {
  margin-top: 4px;
  font-size: 13px;
  line-height: 1.7;
  color: var(--text-secondary);
}

.sms-result-grid {
  margin-top: 14px;
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
}

.result-item {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 10px 12px;
  border-radius: 12px;
  background: rgba(255, 255, 255, 0.7);
}

.result-label {
  font-size: 12px;
  color: var(--text-secondary);
}

.result-value {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-primary);
  word-break: break-all;
}

@media (max-width: 640px) {
  .sms-actions :deep(.el-button) {
    flex: 1 1 100%;
  }

  .sms-result-grid {
    grid-template-columns: 1fr;
  }
}
</style>
