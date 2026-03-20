<template>
  <div class="app-page health-page">
    <section class="page-toolbar">
      <div class="page-title-group">
        <div class="page-kicker">System Pulse</div>
        <h2 class="page-title">账号健康中心</h2>
        <p class="page-desc">{{ headlineSubtitle }}</p>
      </div>
      <div class="page-actions">
        <div class="soft-chip">{{ headlineTitle }}</div>
        <el-button :icon="Refresh" :loading="loading" @click="loadOverview">刷新</el-button>
      </div>
    </section>

    <div class="summary-grid">
      <div class="summary-card summary-card-primary">
        <div class="summary-label">绑定账号</div>
        <div class="summary-value">{{ overview.summary.total_accounts }}</div>
        <div class="summary-note">已添加到系统中的账号总数</div>
      </div>
      <div class="summary-card">
        <div class="summary-label">健康账号</div>
        <div class="summary-value">{{ overview.summary.healthy_accounts }}</div>
        <div class="summary-note">登录态稳定且近 7 天无失败签到</div>
      </div>
      <div class="summary-card summary-card-warning">
        <div class="summary-label">预警账号</div>
        <div class="summary-value">{{ overview.summary.warning_accounts }}</div>
        <div class="summary-note">存在失败签到或最近校验异常</div>
      </div>
      <div class="summary-card summary-card-danger">
        <div class="summary-label">需重登</div>
        <div class="summary-value">{{ overview.summary.reauth_required_accounts }}</div>
        <div class="summary-note">登录态失效，需要重新扫码</div>
      </div>
    </div>

    <el-card class="filter-card filter-panel" shadow="never">
      <div class="filter-row">
        <div class="filter-group">
          <span class="filter-label">筛选</span>
          <el-radio-group v-model="levelFilter" size="small">
            <el-radio-button value="all">全部</el-radio-button>
            <el-radio-button value="danger">危险</el-radio-button>
            <el-radio-button value="warning">预警</el-radio-button>
            <el-radio-button value="healthy">健康</el-radio-button>
            <el-radio-button value="unknown">待判定</el-radio-button>
          </el-radio-group>
        </div>

        <div class="filter-actions">
          <el-input
            v-model="searchKeyword"
            placeholder="搜索账号昵称或米游社 UID"
            clearable
            class="search-input"
          />
          <el-button :icon="Refresh" :loading="loading" @click="loadOverview">
            刷新
          </el-button>
        </div>
      </div>
    </el-card>

    <el-skeleton :loading="loading" animated :rows="10">
      <template #default>
        <el-empty
          v-if="!overview.summary.total_accounts"
          description="还没有可查看状态的账号，先导入一个账号"
          :image-size="84"
        >
          <el-button type="primary" @click="router.push('/accounts')">前往账号管理</el-button>
        </el-empty>

        <el-empty
          v-else-if="!filteredAccounts.length"
          description="没有找到符合条件的账号"
          :image-size="84"
        />

        <div v-else class="account-grid">
          <article
            v-for="account in filteredAccounts"
            :id="`health-account-${account.account_id}`"
            :key="account.account_id"
            class="health-card"
            :class="[
              `health-card-${account.health_level}`,
              { 'health-card-highlighted': highlightedAccountId === account.account_id },
            ]"
          >
            <div class="card-head">
              <div>
                <div class="account-name">{{ formatAccountName(account) }}</div>
                <div class="account-meta">
                  UID {{ account.mihoyo_uid || '-' }}
                  <span>· {{ account.game_role_count }} 个角色</span>
                </div>
              </div>
              <el-tag round effect="dark" :type="getHealthTagType(account.health_level)">
                {{ getHealthText(account.health_level) }}
              </el-tag>
            </div>

            <div class="health-panel" :class="`health-panel-${account.health_level}`">
              <div class="health-title">{{ account.health_reason }}</div>
              <div class="health-meta">
                <span class="meta-chip">网页登录 Cookie</span>
                <span v-if="account.last_refresh_attempt_at" class="meta-text">
                  最近校验 {{ formatDateTime(account.last_refresh_attempt_at) }}
                </span>
              </div>
              <div v-if="account.last_refresh_message" class="health-note">
                {{ account.last_refresh_message }}
              </div>
            </div>

            <div class="info-grid">
              <div class="info-card">
                <div class="info-label">近 7 天签到</div>
                <div class="info-value">
                  成 {{ account.recent_checkin.success_count_7d }}
                  / 败 {{ account.recent_checkin.failed_count_7d }}
                  / 风险 {{ account.recent_checkin.risk_count_7d }}
                </div>
                <div class="info-note">
                  {{ getLatestCheckinText(account) }}
                </div>
              </div>
              <div class="info-card">
                <div class="info-label">可用功能</div>
                <div class="chip-group">
                  <span
                    v-for="asset in account.supported_assets"
                    :key="asset"
                    class="asset-chip"
                  >
                    {{ getAssetLabel(asset) }}
                  </span>
                  <span v-if="!account.supported_assets.length" class="asset-chip asset-chip-muted">
                    暂无可用功能
                  </span>
                </div>
                <div class="info-note">
                  {{ formatSupportedGames(account.supported_games) }}
                </div>
              </div>
            </div>

            <div class="action-row">
              <el-button
                size="small"
                plain
                :loading="maintainingAccountId === account.account_id"
                @click="handleCheck(account)"
              >
                校验登录态
              </el-button>
              <el-button
                size="small"
                type="primary"
                :loading="reauthingAccountId === account.account_id"
                @click="handleReauth(account)"
              >
                {{ account.cookie_status === 'reauth_required' ? '重新扫码' : '扫码更新凭据' }}
              </el-button>
              <el-button
                size="small"
                plain
                :disabled="!account.supported_assets.includes('gacha')"
                @click="jumpToAsset('/gacha', account.account_id)"
              >
                抽卡记录
              </el-button>
              <el-button
                size="small"
                plain
                :disabled="!account.supported_assets.includes('redeem')"
                @click="jumpToAsset('/redeem', account.account_id)"
              >
                兑换码中心
              </el-button>
            </div>
          </article>
        </div>
      </template>
    </el-skeleton>

    <el-card class="events-card panel-card" shadow="never">
      <template #header>
        <div class="section-header">
          <div>
            <div class="section-title">最近异常流</div>
            <div class="section-desc">优先展示需要你立即处理的登录态和签到异常。</div>
          </div>
          <el-tag round effect="plain" type="warning">
            {{ overview.recent_events.length }} 条
          </el-tag>
        </div>
      </template>

      <el-empty
        v-if="!overview.recent_events.length"
        description="当前没有需要关注的异常事件"
        :image-size="72"
      />

      <div v-else class="event-list">
        <button
          v-for="event in overview.recent_events"
          :key="`${event.event_type}-${event.account_id}-${event.occurred_at}`"
          type="button"
          class="event-item"
          @click="focusAccount(event.account_id)"
        >
          <div class="event-main">
            <div class="event-title">
              {{ event.account_name }} · {{ getEventLabel(event) }}
            </div>
            <div class="event-message">{{ event.message }}</div>
          </div>
          <div class="event-side">
            <el-tag size="small" :type="getEventTagType(event.status)" round>
              {{ getEventStatusText(event) }}
            </el-tag>
            <div class="event-time">{{ formatDateTime(event.occurred_at) }}</div>
          </div>
        </button>
      </div>
    </el-card>

    <QrLoginDialog
      v-model:visible="qrDialogVisible"
      :session-id="currentSessionId"
      :account-id="currentRefreshAccountId"
      @success="onLoginSuccess"
    />
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Refresh } from '@element-plus/icons-vue'
import { accountApi, healthCenterApi } from '../api'
import QrLoginDialog from '../components/QrLoginDialog.vue'
import { getGameName } from '../constants/game'

type HealthSummary = {
  total_accounts: number
  healthy_accounts: number
  reauth_required_accounts: number
  warning_accounts: number
  failed_accounts_7d: number
}

type HealthCheckin = {
  success_count_7d: number
  failed_count_7d: number
  risk_count_7d: number
  last_checkin_at?: string | null
  last_checkin_status?: string | null
  last_checkin_message?: string | null
}

type HealthAccount = {
  account_id: number
  nickname?: string | null
  mihoyo_uid?: string | null
  cookie_status: string
  last_refresh_status?: string | null
  last_refresh_message?: string | null
  last_refresh_attempt_at?: string | null
  game_role_count: number
  supported_games: string[]
  supported_assets: string[]
  health_level: string
  health_reason: string
  recent_checkin: HealthCheckin
}

type HealthEvent = {
  account_id: number
  account_name: string
  event_type: string
  status: string
  message: string
  occurred_at: string
}

type HealthOverview = {
  summary: HealthSummary
  accounts: HealthAccount[]
  recent_events: HealthEvent[]
}

const router = useRouter()
const loading = ref(false)
const levelFilter = ref('all')
const searchKeyword = ref('')
const highlightedAccountId = ref<number | null>(null)
const maintainingAccountId = ref<number | null>(null)
const reauthingAccountId = ref<number | null>(null)
const qrDialogVisible = ref(false)
const currentSessionId = ref('')
const currentRefreshAccountId = ref<number | null>(null)
const overview = ref<HealthOverview>({
  summary: {
    total_accounts: 0,
    healthy_accounts: 0,
    reauth_required_accounts: 0,
    warning_accounts: 0,
    failed_accounts_7d: 0,
  },
  accounts: [],
  recent_events: [],
})

const filteredAccounts = computed(() => {
  const keyword = searchKeyword.value.trim().toLowerCase()
  return overview.value.accounts.filter((account) => {
    if (levelFilter.value !== 'all' && account.health_level !== levelFilter.value) {
      return false
    }
    if (!keyword) return true
    return `${account.nickname || ''} ${account.mihoyo_uid || ''}`.toLowerCase().includes(keyword)
  })
})

const headlineTitle = computed(() => {
  if (overview.value.summary.reauth_required_accounts > 0) {
    return `${overview.value.summary.reauth_required_accounts} 个账号需要重新扫码`
  }
  if (overview.value.summary.warning_accounts > 0) {
    return `${overview.value.summary.warning_accounts} 个账号进入预警`
  }
  if (overview.value.summary.total_accounts > 0) {
    return `${overview.value.summary.healthy_accounts} 个账号处于健康状态`
  }
  return '尚未接入账号'
})

const headlineSubtitle = computed(() => {
  if (overview.value.summary.reauth_required_accounts > 0) {
    return '有账号需要重新登录，建议优先处理。'
  }
  if (overview.value.summary.warning_accounts > 0) {
    return '有账号近期出现签到失败或校验异常，建议先查看下方详情。'
  }
  if (overview.value.summary.total_accounts > 0) {
    return '所有账号目前状态正常，可继续使用相关功能。'
  }
  return '先在账号管理中导入账号，再回来查看状态。'
})

function formatAccountName(account: HealthAccount) {
  return account.nickname || account.mihoyo_uid || `账号 ${account.account_id}`
}

function formatDateTime(value?: string | null) {
  if (!value) return '未知时间'
  return new Date(value).toLocaleString('zh-CN')
}

function formatSupportedGames(games: string[]) {
  if (!games.length) return '暂无角色信息'
  return `覆盖 ${games.map((game) => getGameName(game)).join(' / ')}`
}

function getHealthText(level: string) {
  if (level === 'danger') return '危险'
  if (level === 'warning') return '预警'
  if (level === 'healthy') return '健康'
  return '待判定'
}

function getHealthTagType(level: string) {
  if (level === 'danger') return 'danger'
  if (level === 'warning') return 'warning'
  if (level === 'healthy') return 'success'
  return 'info'
}

function getAssetLabel(asset: string) {
  if (asset === 'checkin') return '签到'
  if (asset === 'gacha') return '抽卡'
  if (asset === 'redeem') return '兑换码'
  return asset
}

function getLatestCheckinText(account: HealthAccount) {
  if (!account.recent_checkin.last_checkin_at) {
    return '近 7 天暂无签到记录'
  }
  return `${formatDateTime(account.recent_checkin.last_checkin_at)} · ${account.recent_checkin.last_checkin_message || '已记录最近一次签到结果'}`
}

function getEventLabel(event: HealthEvent) {
  return event.event_type === 'login_state' ? '登录态异常' : '签到异常'
}

function getEventStatusText(event: HealthEvent) {
  if (event.event_type === 'login_state') {
    if (event.status === 'reauth_required') return '需重登'
    if (event.status === 'expired') return '已过期'
    if (event.status === 'network_error') return '网络异常'
    return '状态异常'
  }
  if (event.status === 'risk') return '风控'
  return '失败'
}

function getEventTagType(status: string) {
  if (status === 'failed' || status === 'reauth_required') return 'danger'
  if (status === 'risk' || status === 'expired' || status === 'network_error') return 'warning'
  return 'info'
}

async function loadOverview() {
  loading.value = true
  try {
    const { data } = await healthCenterApi.getOverview()
    overview.value = data
  } finally {
    loading.value = false
  }
}

async function handleCheck(account: HealthAccount) {
  maintainingAccountId.value = account.account_id
  try {
    const { data } = await accountApi.checkLoginState(account.account_id)
    ElMessage.success(data.message || data.last_refresh_message || '登录态校验已完成')
    await loadOverview()
  } finally {
    maintainingAccountId.value = null
  }
}

async function handleReauth(account: HealthAccount) {
  reauthingAccountId.value = account.account_id
  try {
    const { data } = await accountApi.refreshCookie(account.account_id)
    currentRefreshAccountId.value = account.account_id
    currentSessionId.value = data.session_id
    qrDialogVisible.value = true
  } finally {
    reauthingAccountId.value = null
  }
}

function jumpToAsset(path: string, accountId: number) {
  router.push({
    path,
    query: { account_id: String(accountId) },
  })
}

async function focusAccount(accountId: number) {
  levelFilter.value = 'all'
  searchKeyword.value = ''
  highlightedAccountId.value = accountId
  await nextTick()
  document.getElementById(`health-account-${accountId}`)?.scrollIntoView({
    behavior: 'smooth',
    block: 'center',
  })
  window.setTimeout(() => {
    if (highlightedAccountId.value === accountId) {
      highlightedAccountId.value = null
    }
  }, 2200)
}

async function onLoginSuccess() {
  qrDialogVisible.value = false
  currentRefreshAccountId.value = null
  await loadOverview()
  ElMessage.success('账号登录态已更新')
}

onMounted(loadOverview)
</script>

<style scoped>
.health-page {
  width: 100%;
}

.summary-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 16px;
}

.summary-card {
  padding: 22px;
  border-radius: 20px;
  border: 1px solid var(--border-color);
  background:
    linear-gradient(180deg, rgba(255, 255, 255, 0.98), rgba(248, 250, 252, 0.94));
  box-shadow: 0 12px 28px rgba(15, 23, 42, 0.06);
}

.summary-card-primary {
  background:
    radial-gradient(circle at top right, rgba(45, 212, 191, 0.12), transparent 32%),
    linear-gradient(180deg, rgba(240, 253, 250, 0.98), rgba(204, 251, 241, 0.82));
}

.summary-card-warning {
  background:
    radial-gradient(circle at top right, rgba(251, 191, 36, 0.12), transparent 32%),
    linear-gradient(180deg, rgba(255, 251, 235, 0.98), rgba(254, 243, 199, 0.84));
}

.summary-card-danger {
  background:
    radial-gradient(circle at top right, rgba(248, 113, 113, 0.12), transparent 32%),
    linear-gradient(180deg, rgba(254, 242, 242, 0.98), rgba(254, 226, 226, 0.84));
}

.summary-label {
  font-size: 13px;
  color: var(--text-secondary);
}

.summary-value {
  margin-top: 12px;
  font-size: 34px;
  font-weight: 800;
  color: var(--text-primary);
}

.summary-note {
  margin-top: 10px;
  font-size: 12px;
  line-height: 1.7;
  color: var(--text-secondary);
}

.filter-card,
.events-card {
  overflow: hidden;
}

.filter-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
}

.filter-group,
.filter-actions,
.section-header {
  display: flex;
  align-items: center;
  gap: 12px;
}

.section-header {
  justify-content: space-between;
}

.filter-label,
.section-title {
  font-size: 14px;
  font-weight: 700;
  color: var(--text-primary);
}

.section-desc {
  margin-top: 4px;
  font-size: 12px;
  color: var(--text-secondary);
}

.search-input {
  width: 280px;
}

.account-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 16px;
}

.health-card {
  padding: 22px;
  border-radius: 22px;
  border: 1px solid rgba(148, 163, 184, 0.16);
  background:
    linear-gradient(180deg, rgba(255, 255, 255, 0.98), rgba(248, 250, 252, 0.92));
  box-shadow: 0 16px 34px rgba(15, 23, 42, 0.08);
  transition: transform 0.2s ease, box-shadow 0.2s ease, border-color 0.2s ease;
}

.health-card:hover {
  transform: translateY(-2px);
  box-shadow: 0 20px 40px rgba(15, 23, 42, 0.12);
}

.health-card-highlighted {
  border-color: rgba(20, 184, 166, 0.72);
  box-shadow: 0 0 0 2px rgba(45, 212, 191, 0.18), 0 20px 40px rgba(15, 23, 42, 0.14);
}

.card-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
}

.account-name {
  font-size: 18px;
  font-weight: 700;
  color: var(--text-primary);
}

.account-meta {
  margin-top: 6px;
  font-size: 12px;
  color: var(--text-secondary);
}

.health-panel {
  margin-top: 16px;
  padding: 16px;
  border-radius: 18px;
  border: 1px solid transparent;
}

.health-panel-healthy {
  background: linear-gradient(135deg, rgba(236, 253, 245, 0.96), rgba(209, 250, 229, 0.82));
  border-color: rgba(16, 185, 129, 0.2);
}

.health-panel-warning {
  background: linear-gradient(135deg, rgba(255, 251, 235, 0.96), rgba(254, 243, 199, 0.82));
  border-color: rgba(245, 158, 11, 0.22);
}

.health-panel-danger {
  background: linear-gradient(135deg, rgba(254, 242, 242, 0.96), rgba(254, 226, 226, 0.82));
  border-color: rgba(239, 68, 68, 0.22);
}

.health-panel-unknown {
  background: linear-gradient(135deg, rgba(241, 245, 249, 0.96), rgba(226, 232, 240, 0.82));
  border-color: rgba(148, 163, 184, 0.22);
}

.health-title {
  font-size: 14px;
  font-weight: 700;
  color: var(--text-primary);
}

.health-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 8px 12px;
  margin-top: 10px;
}

.meta-chip {
  min-height: 28px;
  padding: 0 12px;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.62);
  display: inline-flex;
  align-items: center;
  font-size: 12px;
  font-weight: 600;
  color: var(--text-primary);
}

.meta-text,
.health-note,
.info-note,
.event-time {
  font-size: 12px;
  color: var(--text-secondary);
}

.health-note {
  margin-top: 10px;
  line-height: 1.7;
}

.info-grid {
  margin-top: 16px;
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}

.info-card {
  padding: 14px;
  border-radius: 16px;
  background: var(--bg-color);
  border: 1px solid var(--border-color);
}

.info-label {
  font-size: 12px;
  color: var(--text-secondary);
}

.info-value {
  margin-top: 10px;
  font-size: 15px;
  font-weight: 700;
  color: var(--text-primary);
  line-height: 1.6;
}

.chip-group {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 10px;
}

.asset-chip {
  min-height: 28px;
  padding: 0 10px;
  border-radius: 999px;
  display: inline-flex;
  align-items: center;
  font-size: 12px;
  font-weight: 600;
  color: #115e59;
  background: rgba(45, 212, 191, 0.12);
}

.asset-chip-muted {
  color: var(--text-secondary);
  background: rgba(148, 163, 184, 0.12);
}

.action-row {
  margin-top: 16px;
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.event-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.event-item {
  width: 100%;
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  padding: 16px;
  border-radius: 16px;
  border: 1px solid rgba(148, 163, 184, 0.16);
  background:
    linear-gradient(180deg, rgba(255, 255, 255, 0.98), rgba(248, 250, 252, 0.92));
  text-align: left;
  cursor: pointer;
  transition: transform 0.2s ease, box-shadow 0.2s ease;
}

.event-item:hover {
  transform: translateY(-1px);
  box-shadow: 0 12px 26px rgba(15, 23, 42, 0.08);
}

.event-title {
  font-size: 14px;
  font-weight: 700;
  color: var(--text-primary);
}

.event-message {
  margin-top: 8px;
  font-size: 13px;
  line-height: 1.7;
  color: var(--text-primary);
}

.event-side {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 10px;
}

:deep(html.dark) .summary-card,
:deep(.dark) .summary-card,
:deep(html.dark) .health-card,
:deep(.dark) .health-card,
:deep(html.dark) .event-item,
:deep(.dark) .event-item {
  background:
    linear-gradient(180deg, rgba(30, 41, 59, 0.96), rgba(15, 23, 42, 0.92));
}

@media (max-width: 1180px) {
  .summary-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .account-grid {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 860px) {
  .filter-row,
  .filter-group,
  .filter-actions,
  .section-header,
  .event-item {
    flex-direction: column;
    align-items: flex-start;
  }

  .search-input {
    width: 100%;
  }

  .info-grid {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 640px) {
  .health-page {
    gap: 16px;
  }

  .summary-grid {
    grid-template-columns: 1fr;
  }
}
</style>
