<template>
  <div class="accounts-page">
    <div class="page-header">
      <h3>米哈游账号</h3>
      <el-button type="primary" :icon="Plus" @click="handleAddAccount" round>
        添加账号
      </el-button>
    </div>

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
        @refresh="handleRefreshCookie(account)"
        @delete="handleDelete(account)"
      />
    </div>

    <!-- 二维码登录弹窗 -->
    <QrLoginDialog
      v-model:visible="qrDialogVisible"
      :session-id="currentSessionId"
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
    currentSessionId.value = data.session_id
    qrDialogVisible.value = true
  } catch (e) {
    // 错误已在拦截器中处理
  }
}

async function handleRefreshCookie(account: any) {
  try {
    const { data } = await accountApi.refreshCookie(account.id)
    currentSessionId.value = data.session_id
    qrDialogVisible.value = true
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
  qrDialogVisible.value = false
  loadAccounts()
  ElMessage.success('账号绑定成功')
}

onMounted(loadAccounts)
</script>

<style scoped>
.accounts-page {
  max-width: 1200px;
  margin: 0 auto;
}

.page-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 24px;
}

.page-header h3 {
  font-size: 16px;
  color: var(--text-primary);
}

.page-header .el-button--primary {
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  border: none;
}

.account-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(360px, 1fr));
  gap: 16px;
}
</style>
