<template>
  <el-dialog
    :model-value="visible"
    @update:model-value="$emit('update:visible', $event)"
    title="扫码登录米游社"
    width="420px"
    :close-on-click-modal="false"
    @open="startLogin"
    @close="cleanup"
  >
    <div class="qr-container">
      <!-- 加载中 -->
      <div v-if="status === 'initializing'" class="qr-loading">
        <el-icon class="loading-icon" :size="40"><Loading /></el-icon>
        <p>正在准备登录页面...</p>
      </div>

      <!-- 二维码展示 -->
      <div v-else-if="status === 'qr_ready' || status === 'scanned'" class="qr-code">
        <img v-if="qrImage" :src="'data:image/png;base64,' + qrImage" alt="二维码" />
        <div v-if="status === 'scanned'" class="scanned-overlay">
          <el-icon :size="40" color="#10b981"><CircleCheck /></el-icon>
          <p>已扫码，请在手机上确认</p>
        </div>
      </div>

      <!-- 成功 -->
      <div v-else-if="status === 'success'" class="qr-success">
        <el-icon :size="48" color="#10b981"><CircleCheck /></el-icon>
        <p>登录成功！</p>
        <p class="sub-text">已导入 {{ rolesCount }} 个游戏角色</p>
      </div>

      <!-- 失败/超时 -->
      <div v-else-if="status === 'failed' || status === 'timeout'" class="qr-error">
        <el-icon :size="48" color="#ef4444"><CircleClose /></el-icon>
        <p>{{ errorMessage || '登录失败' }}</p>
        <el-button type="primary" size="small" @click="startLogin">重试</el-button>
      </div>

      <!-- 提示文字 -->
      <div v-if="status === 'qr_ready'" class="qr-hint">
        <p>打开米游社 App → 我的 → 左上角扫码</p>
        <p class="timeout-hint">二维码有效期 3 分钟</p>
      </div>
    </div>
  </el-dialog>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue'
import { Loading, CircleCheck, CircleClose } from '@element-plus/icons-vue'
import { useUserStore } from '../stores/user'

const props = defineProps<{
  visible: boolean
  sessionId: string
}>()

const emit = defineEmits(['update:visible', 'success'])

const userStore = useUserStore()
const status = ref('initializing')
const qrImage = ref('')
const errorMessage = ref('')
const rolesCount = ref(0)
let ws: WebSocket | null = null

function startLogin() {
  if (!props.sessionId) return

  status.value = 'initializing'
  qrImage.value = ''
  errorMessage.value = ''

  // 连接 WebSocket
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  const host = window.location.host
  const userId = userStore.userInfo?.id || 0
  const wsUrl = `${protocol}//${host}/ws/qr/${props.sessionId}?user_id=${userId}`

  ws = new WebSocket(wsUrl)

  ws.onmessage = (event) => {
    const data = JSON.parse(event.data)

    switch (data.type) {
      case 'status':
        status.value = data.status
        break
      case 'qr_code':
        qrImage.value = data.image
        status.value = 'qr_ready'
        break
      case 'success':
        status.value = 'success'
        rolesCount.value = data.roles_count || 0
        // 延迟关闭弹窗
        setTimeout(() => emit('success'), 1500)
        break
      case 'error':
        status.value = 'failed'
        errorMessage.value = data.message
        break
      case 'timeout':
        status.value = 'timeout'
        errorMessage.value = data.message
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

function cleanup() {
  if (ws) {
    ws.close()
    ws = null
  }
}

watch(() => props.visible, (val) => {
  if (!val) cleanup()
})
</script>

<style scoped>
.qr-container {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 20px;
  min-height: 300px;
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

html.dark .scanned-overlay {
  background: rgba(30, 41, 59, 0.9);
}

.qr-success, .qr-error {
  text-align: center;
}

.qr-success p, .qr-error p {
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
</style>
