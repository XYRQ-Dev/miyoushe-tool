<template>
  <div class="app-page accounts-page">
    <section class="page-toolbar">
      <div class="page-title-group">
        <div class="page-kicker">Account Console</div>
        <h2 class="page-title">账号管理</h2>
        <p class="page-desc">绑定账号、校验网页登录状态，并查看每个账号下的角色信息。</p>
      </div>
      <div class="page-actions">
        <el-button type="primary" :icon="Plus" @click="handleAddAccount">
          添加账号
        </el-button>
      </div>
    </section>

    <!-- 空状态 -->
    <el-empty
      v-if="!loading && accounts.length === 0"
      description="还没有绑定米哈游账号"
    >
      <el-button type="primary" @click="handleAddAccount">扫码添加</el-button>
    </el-empty>

    <!-- 账号卡片列表 -->
    <div class="account-grid">
      <AccountCard
        v-for="account in accounts"
        :key="account.id"
        :account="account"
        @check="handleCheckLoginState(account)"
        @reauth="handleRefreshCookie(account)"
        @delete="handleDelete(account)"
      />
    </div>

    <!-- 二维码登录弹窗 -->
    <QrLoginDialog
      v-model:visible="qrDialogVisible"
      :session-id="currentSessionId"
      :account-id="currentRefreshAccountId"
      @success="onLoginSuccess"
    />
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { Plus } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { accountApi } from '../api'
import AccountCard from '../components/AccountCard.vue'
import QrLoginDialog from '../components/QrLoginDialog.vue'

const accounts = ref<any[]>([])
const loading = ref(false)
const qrDialogVisible = ref(false)
const currentSessionId = ref('')
const currentRefreshAccountId = ref<number | null>(null)

async function loadAccounts() {
  loading.value = true
  try {
    const { data } = await accountApi.list()
    accounts.value = data.accounts
  } finally {
    loading.value = false
  }
}

async function handleAddAccount() {
  try {
    const { data } = await accountApi.startQrLogin()
    currentRefreshAccountId.value = null
    currentSessionId.value = data.session_id
    qrDialogVisible.value = true
  } catch (e) {
    // 错误已在拦截器中处理
  }
}

async function handleRefreshCookie(account: any) {
  try {
    const { data } = await accountApi.refreshCookie(account.id)
    currentRefreshAccountId.value = account.id
    currentSessionId.value = data.session_id
    qrDialogVisible.value = true
  } catch (e) {
    // 错误已在拦截器中处理
  }
}

async function handleCheckLoginState(account: any) {
  try {
    const { data } = await accountApi.checkLoginState(account.id)
    const updatedMessage = data.message || data.last_refresh_message || '登录态校验已完成'
    ElMessage.success(updatedMessage)
    await loadAccounts()
  } catch (e) {
    // 错误已在拦截器中处理
  }
}

async function handleDelete(account: any) {
  try {
    await ElMessageBox.confirm(
      `确定删除账号「${account.nickname || account.mihoyo_uid}」？此操作不可撤销。`,
      '删除确认',
      { confirmButtonText: '删除', cancelButtonText: '取消', type: 'warning' }
    )
    await accountApi.delete(account.id)
    ElMessage.success('账号已删除')
    await loadAccounts()
  } catch (e: any) {
    if (e !== 'cancel') {
      // 非取消的错误在拦截器中处理
    }
  }
}

function onLoginSuccess() {
  const refreshedExistingAccount = currentRefreshAccountId.value !== null
  qrDialogVisible.value = false
  currentRefreshAccountId.value = null
  loadAccounts()
  ElMessage.success(refreshedExistingAccount ? '账号登录态已更新' : '账号绑定成功')
}

onMounted(loadAccounts)
</script>

<style scoped>
.accounts-page {
  width: 100%;
}

.account-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(360px, 1fr));
  gap: 16px;
}
</style>
