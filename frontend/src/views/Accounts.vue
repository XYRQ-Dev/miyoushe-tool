<template>
  <div class="app-page accounts-page">
    <div class="action-bar">
      <el-button type="primary" :icon="Plus" class="add-btn" @click="handleAddAccount">
        添加高权限账号
      </el-button>
    </div>

    <section class="account-notice-grid">
      <div class="account-notice account-notice-info">
        <el-icon class="notice-icon"><InfoFilled /></el-icon>
        <div class="notice-content">
          <div class="notice-title">登录态维护说明</div>
          <div class="notice-desc">
            卡片中的“校验登录态”当前语义是“校验并尝试修复登录态”。
            如果账号仍停留在旧网页登录形态，系统会提示重新走高权限登录升级。
          </div>
        </div>
      </div>

      <div
        v-if="accountsNeedingUpgrade.length"
        class="account-notice account-notice-warning"
      >
        <el-icon class="notice-icon"><WarningFilled /></el-icon>
        <div class="notice-content">
          <div class="notice-title">发现 {{ accountsNeedingUpgrade.length }} 个待升级账号</div>
          <div class="notice-desc">
            这些账号仍只有旧网页登录 Cookie，缺少 Passport 根凭据。
            请在对应卡片上使用“扫码更新凭据”升级到高权限登录态，否则后续自动修复能力不完整。
          </div>
        </div>
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
          <el-icon class="banner-icon" :class="account.upgrade_required || !account.has_high_privilege_auth ? 'text-warning' : 'text-success'">
            <WarningFilled v-if="account.upgrade_required || !account.has_high_privilege_auth" />
            <SuccessFilled v-else />
          </el-icon>
          <div class="credential-banner-main">
            <div class="credential-banner-title">{{ getCredentialBannerTitle(account) }}</div>
            <div class="credential-banner-desc" :title="getCredentialBannerDescription(account)">
              {{ getCredentialBannerDescription(account) }}
            </div>
          </div>
          <el-button
            v-if="account.upgrade_required || !account.has_high_privilege_auth"
            size="small"
            type="warning"
            plain
            class="upgrade-btn"
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
import { Plus, InfoFilled, WarningFilled, SuccessFilled } from '@element-plus/icons-vue'
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
  return '高权限状态待确认'
}

function getCredentialBannerDescription(account: AccountItem) {
  if (account.upgrade_required) {
    return '该账号依赖网页 Cookie。请扫码升级，否则修复能力受限。'
  }
  if (!account.has_high_privilege_auth) {
    return '建议尽快补齐 Passport 根凭据。'
  }
  if (account.credential_status === 'valid') {
    return '系统优先基于高权限凭据修复 Cookie。'
  }
  if (account.credential_status === 'reauth_required') {
    return account.last_refresh_message || '需要重新扫码更新。'
  }
  return '可先执行一次登录态校验再确认。'
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
  gap: var(--space-3);
}

.action-bar {
  display: flex;
  justify-content: flex-start;
}

.add-btn {
  font-weight: 600;
  box-shadow: var(--shadow-sm);
}

.account-notice-grid {
  display: grid;
  grid-template-columns: 1fr;
  gap: var(--space-3);
}

@media (min-width: 768px) {
  .account-notice-grid {
    grid-template-columns: repeat(auto-fit, minmax(400px, 1fr));
  }
}

.account-notice {
  display: flex;
  gap: var(--space-2);
  padding: 12px 16px;
  border-radius: var(--radius-lg);
  border: 1px solid var(--border-soft);
}

.account-notice-info {
  background: var(--bg-info-soft);
  border-color: var(--color-info-light-8);
}

.account-notice-warning {
  background: var(--bg-warning-soft);
  border-color: var(--color-warning-light-8);
}

.notice-icon {
  font-size: 24px;
  flex-shrink: 0;
}

.account-notice-info .notice-icon { color: var(--color-info); }
.account-notice-warning .notice-icon { color: var(--color-warning); }

.notice-content {
  flex: 1;
}

.notice-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary);
  margin-bottom: 4px;
}

.notice-desc {
  font-size: 13px;
  line-height: 1.5;
  color: var(--text-secondary);
}

.account-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(360px, 1fr));
  gap: var(--space-5);
}

.account-item {
  display: flex;
  flex-direction: column;
  background: var(--bg-surface);
  border-radius: var(--radius-xl);
  border: 1px solid var(--border-soft);
  box-shadow: var(--shadow-soft);
  overflow: hidden;
  transition: transform var(--transition-medium), box-shadow var(--transition-medium), border-color var(--transition-medium);
}

.account-item:hover {
  transform: translateY(-2px);
  box-shadow: var(--shadow-md);
  border-color: var(--border-medium);
}

.credential-banner {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  padding: 12px 16px;
  border-bottom: 1px solid var(--border-soft);
}

.credential-banner-warning { background: var(--bg-warning-soft); }
.credential-banner-success { background: var(--bg-success-soft); }

.banner-icon { font-size: 18px; }
.text-warning { color: var(--color-warning); }
.text-success { color: var(--color-success); }

.credential-banner-main {
  flex: 1;
  min-width: 0;
}

.credential-banner-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-primary);
  margin-bottom: 2px;
}

.credential-banner-desc {
  font-size: 12px;
  color: var(--text-tertiary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.upgrade-btn {
  font-weight: 600;
}

.account-item :deep(.account-card) {
  border: none;
  border-radius: 0;
  box-shadow: none;
  background: transparent;
}

@media (max-width: 768px) {
  .credential-banner {
    flex-direction: column;
    align-items: flex-start;
    gap: 8px;
  }
}
</style>

