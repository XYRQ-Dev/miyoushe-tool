<template>
  <div class="app-page accounts-page">
    <section class="page-toolbar">
      <div class="page-title-group">
        <div class="page-kicker">Account Console</div>
        <h2 class="page-title">账号管理</h2>
        <p class="page-desc">绑定高权限账号、校验并尝试修复登录态，并查看每个账号下的角色信息。</p>
      </div>
      <div class="page-actions">
        <el-button type="primary" :icon="Plus" @click="handleAddAccount">
          添加高权限账号
        </el-button>
      </div>
    </section>

    <section class="account-notice-grid">
      <div class="account-notice account-notice-info">
        <div class="notice-title">登录态维护说明</div>
        <p class="notice-desc">
          卡片中的“校验登录态”当前语义是“校验并尝试修复登录态”。
          如果账号仍停留在旧网页登录形态，系统会提示重新走高权限登录升级。
        </p>
      </div>

      <div
        v-if="accountsNeedingUpgrade.length"
        class="account-notice account-notice-warning"
      >
        <div class="notice-title">发现 {{ accountsNeedingUpgrade.length }} 个待升级账号</div>
        <p class="notice-desc">
          这些账号仍只有旧网页登录 Cookie，缺少 Passport 根凭据。
          请在对应卡片上使用“扫码更新凭据”升级到高权限登录态，否则后续自动修复能力不完整。
        </p>
      </div>
    </section>

    <!-- 空状态 -->
    <el-empty
      v-if="!loading && accounts.length === 0"
      description="还没有绑定高权限米哈游账号"
    >
      <el-button type="primary" @click="handleAddAccount">高权限登录添加账号</el-button>
    </el-empty>

    <!-- 账号卡片列表 -->
    <div class="account-grid">
      <div
        v-for="account in accounts"
        :key="account.id"
        class="account-item"
      >
        <div
          class="credential-banner"
          :class="account.upgrade_required || !account.has_high_privilege_auth
            ? 'credential-banner-warning'
            : 'credential-banner-success'"
        >
          <div class="credential-banner-main">
            <div class="credential-banner-title">{{ getCredentialBannerTitle(account) }}</div>
            <div class="credential-banner-desc">{{ getCredentialBannerDescription(account) }}</div>
          </div>
          <el-button
            v-if="account.upgrade_required || !account.has_high_privilege_auth"
            size="small"
            type="warning"
            plain
            @click="handleRefreshCookie(account)"
          >
            立即升级
          </el-button>
        </div>

        <AccountCard
          :account="account"
          @check="handleCheckLoginState(account)"
          @reauth="handleRefreshCookie(account)"
          @delete="handleDelete(account)"
        />
      </div>
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
import { computed, onMounted, ref } from 'vue'
import { Plus } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { accountApi } from '../api'
import AccountCard from '../components/AccountCard.vue'
import QrLoginDialog from '../components/QrLoginDialog.vue'

type AccountItem = {
  id: number
  nickname?: string | null
  mihoyo_uid?: string | null
  credential_status?: string | null
  has_high_privilege_auth?: boolean
  upgrade_required?: boolean
  cookie_status?: string
  last_refresh_message?: string | null
}

const accounts = ref<AccountItem[]>([])
const loading = ref(false)
const qrDialogVisible = ref(false)
const currentSessionId = ref('')
const currentRefreshAccountId = ref<number | null>(null)
const accountsNeedingUpgrade = computed(() => (
  accounts.value.filter((account) => account.upgrade_required || !account.has_high_privilege_auth)
))

async function loadAccounts() {
  loading.value = true
  try {
    const { data } = await accountApi.list()
    accounts.value = data.accounts || []
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

async function handleRefreshCookie(account: AccountItem) {
  try {
    const { data } = await accountApi.refreshCookie(account.id)
    currentRefreshAccountId.value = account.id
    currentSessionId.value = data.session_id
    qrDialogVisible.value = true
  } catch (e) {
    // 错误已在拦截器中处理
  }
}

async function handleCheckLoginState(account: AccountItem) {
  try {
    const { data } = await accountApi.checkLoginState(account.id)
    const updatedMessage = data.message || data.last_refresh_message || '已完成登录态校验，并已尝试修复'
    ElMessage.success(updatedMessage)
    await loadAccounts()
  } catch (e) {
    // 错误已在拦截器中处理
  }
}

async function handleDelete(account: AccountItem) {
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

function getCredentialBannerTitle(account: AccountItem) {
  if (account.upgrade_required) {
    return '旧账号需要升级到高权限登录'
  }
  if (!account.has_high_privilege_auth) {
    return '尚未接入高权限根凭据'
  }
  if (account.credential_status === 'valid') {
    return '高权限登录已接入'
  }
  if (account.credential_status === 'reauth_required') {
    return '高权限登录需要重新确认'
  }
  return '高权限登录状态待确认'
}

function getCredentialBannerDescription(account: AccountItem) {
  if (account.upgrade_required) {
    return '该账号仍依赖旧网页登录 Cookie。请重新扫码升级，否则后续登录态校验只能提示风险，无法稳定自修复。'
  }
  if (!account.has_high_privilege_auth) {
    return '当前账号还没有 Passport 根凭据，建议尽快补齐高权限登录态。'
  }
  if (account.credential_status === 'valid') {
    return 'Passport 根凭据已接入；后续登录态校验会优先基于高权限凭据尝试修复工作 Cookie。'
  }
  if (account.credential_status === 'reauth_required') {
    return account.last_refresh_message || '系统已确认当前高权限登录态需要重新扫码更新。'
  }
  return '当前账号的高权限状态尚未有明确结论，可先执行一次登录态校验。'
}

function onLoginSuccess() {
  const refreshedExistingAccount = currentRefreshAccountId.value !== null
  qrDialogVisible.value = false
  currentRefreshAccountId.value = null
  loadAccounts()
  ElMessage.success(refreshedExistingAccount ? '已升级高权限登录态' : '高权限账号绑定成功')
}

onMounted(loadAccounts)
</script>

<style scoped>
.accounts-page {
  width: 100%;
}

.account-notice-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
  gap: 16px;
}

.account-notice {
  border-radius: 20px;
  padding: 18px 20px;
  border: 1px solid transparent;
}

.account-notice-info {
  background: linear-gradient(135deg, rgba(239, 246, 255, 0.96), rgba(219, 234, 254, 0.86));
  border-color: rgba(59, 130, 246, 0.16);
}

.account-notice-warning {
  background: linear-gradient(135deg, rgba(255, 251, 235, 0.98), rgba(254, 243, 199, 0.88));
  border-color: rgba(245, 158, 11, 0.18);
}

.notice-title {
  font-size: 15px;
  font-weight: 700;
  color: var(--text-primary);
}

.notice-desc {
  margin-top: 8px;
  font-size: 13px;
  line-height: 1.7;
  color: var(--text-secondary);
}

.account-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(360px, 1fr));
  gap: 16px;
}

.account-item {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.credential-banner {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  border-radius: 16px;
  padding: 14px 16px;
  border: 1px solid transparent;
}

.credential-banner-warning {
  background: linear-gradient(135deg, rgba(255, 247, 237, 0.98), rgba(255, 237, 213, 0.9));
  border-color: rgba(249, 115, 22, 0.18);
}

.credential-banner-success {
  background: linear-gradient(135deg, rgba(236, 253, 245, 0.96), rgba(220, 252, 231, 0.88));
  border-color: rgba(16, 185, 129, 0.18);
}

.credential-banner-main {
  min-width: 0;
}

.credential-banner-title {
  font-size: 14px;
  font-weight: 700;
  color: var(--text-primary);
}

.credential-banner-desc {
  margin-top: 4px;
  font-size: 12px;
  line-height: 1.7;
  color: var(--text-secondary);
}

@media (max-width: 768px) {
  .credential-banner {
    flex-direction: column;
    align-items: flex-start;
  }

  .credential-banner :deep(.el-button) {
    width: 100%;
  }
}
</style>
