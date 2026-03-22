<template>
  <div class="app-page asset-page">
    <el-alert
      v-if="headlineSubtitle"
      :title="headlineSubtitle"
      type="info"
      show-icon
      :closable="false"
      class="page-info-alert"
    />

    <div class="summary-grid">
      <div class="summary-card summary-card-primary">
        <div class="summary-label">账号数</div>
        <div class="summary-value">{{ overview.summary.total_accounts }}</div>
        <div class="summary-note">已纳入资产总览的米游社账号数量</div>
      </div>
      <div class="summary-card">
        <div class="summary-label">角色数</div>
        <div class="summary-value">{{ overview.summary.total_roles }}</div>
        <div class="summary-note">已识别到的全部角色数量</div>
      </div>
      <div class="summary-card summary-card-warm">
        <div class="summary-label">已归档抽卡档案</div>
        <div class="summary-value">{{ overview.summary.gacha_archived_games }}</div>
        <div class="summary-note">按账号与游戏维度已落库的抽卡组合数</div>
      </div>
    </div>

    <el-card class="filter-card filter-panel" shadow="never">
      <div class="filter-row">
        <div class="filter-cluster">
          <el-select v-model="accountFilter" placeholder="全部账号" class="filter-select" clearable>
            <el-option
              v-for="account in overview.accounts"
              :key="account.account_id"
              :label="account.account_name"
              :value="String(account.account_id)"
            />
          </el-select>
          <el-select v-model="gameFilter" placeholder="全部游戏" class="filter-select" clearable>
            <el-option
              v-for="game in gameOptions"
              :key="game"
              :label="getGameName(game)"
              :value="game"
            />
          </el-select>
          <el-input
            v-model="keyword"
            class="filter-search"
            clearable
            placeholder="搜索账号名、角色名或 UID"
          />
        </div>
        <el-button :icon="Refresh" :loading="loading" @click="loadOverview">
          刷新
        </el-button>
      </div>
    </el-card>

    <el-skeleton :loading="loading" animated :rows="10">
      <template #default>
        <el-empty
          v-if="!overview.summary.total_accounts"
          description="还没有可展示的角色信息，先导入账号"
          :image-size="88"
        >
          <el-button type="primary" @click="router.push('/accounts')">前往账号管理</el-button>
        </el-empty>

        <el-empty
          v-else-if="!filteredAccounts.length"
          description="没有找到符合条件的角色"
          :image-size="88"
        />

        <div v-else class="account-section-list">
          <section
            v-for="account in filteredAccounts"
            :key="account.account_id"
            class="account-shell"
          >
            <div class="account-shell-head">
              <div>
                <div class="account-title-row">
                  <div class="account-title">{{ account.account_name }}</div>
                  <el-tag round effect="dark" :type="getCookieTagType(account.cookie_status)">
                    {{ getCookieStatusText(account.cookie_status) }}
                  </el-tag>
                </div>
                <div class="account-meta">
                  米游社 UID {{ account.mihoyo_uid || '-' }}
                  <span>· {{ account.roles.length }} 个角色</span>
                  <span v-if="account.last_refresh_status">· 最近校验 {{ getRefreshText(account.last_refresh_status) }}</span>
                </div>
              </div>
            </div>

            <div class="role-grid">
              <article
                v-for="role in account.roles"
                :key="role.role_id"
                class="role-card"
                :class="['game-' + role.game]"
              >
                <div class="role-card-inner">
                  <header class="role-header">
                    <div class="role-identity">
                      <div class="role-game-badge">
                        <span class="game-dot"></span>
                        {{ role.game_name }}
                      </div>
                      <h3 class="role-nickname">{{ role.nickname || role.game_uid }}</h3>
                      <div class="role-meta-tags">
                        <span class="meta-tag">
                          <el-icon><User /></el-icon>
                          {{ role.game_uid }}
                        </span>
                        <span v-if="role.region" class="meta-tag">
                          <el-icon><Location /></el-icon>
                          {{ role.region }}
                        </span>
                      </div>
                    </div>
                    <div class="role-stats">
                      <div class="level-box">
                        <span class="level-label">LV</span>
                        <span class="level-value">{{ role.level || '?' }}</span>
                      </div>
                    </div>
                  </header>

                  <div class="role-status-row">
                    <section class="status-box checkin-box" :class="'status-' + role.recent_checkin.last_status">
                      <div class="status-header">
                        <el-icon v-if="role.recent_checkin.last_status === 'success'"><CircleCheck /></el-icon>
                        <el-icon v-else-if="role.recent_checkin.last_status === 'failed'"><CircleClose /></el-icon>
                        <el-icon v-else><Warning /></el-icon>
                        最近签到
                      </div>
                      <div class="status-body">
                        <span class="status-text">{{ getCheckinStatusText(role.recent_checkin.last_status) }}</span>
                        <span v-if="role.recent_checkin.last_executed_at" class="status-time">
                          {{ formatTimeAgo(role.recent_checkin.last_executed_at) }}
                        </span>
                      </div>
                    </section>
                  </div>

                  <div class="role-details-group">
                    <div class="asset-pills">
                      <span
                        v-for="asset in role.supported_assets"
                        :key="asset"
                        class="asset-pill-mini"
                      >
                        <el-icon v-if="asset === 'checkin'"><Calendar /></el-icon>
                        <el-icon v-else-if="asset === 'gacha'"><TrendCharts /></el-icon>
                        <el-icon v-else-if="asset === 'redeem'"><Ticket /></el-icon>
                        {{ getAssetLabel(asset) }}
                      </span>
                      <span v-if="!role.supported_assets.length" class="asset-pill-mini muted">
                        暂无可用功能
                      </span>
                    </div>
                    <div v-if="role.has_gacha_archive" class="archive-status">
                      <el-icon><Coin /></el-icon>
                      已归档抽卡
                    </div>
                  </div>

                  <footer class="role-actions-bar">
                    <el-button
                      size="small"
                      link
                      class="action-btn-link"
                      v-if="role.supported_assets.includes('gacha')"
                      @click="jumpToGacha(account.account_id, role.game, role.game_uid)"
                    >
                      <template #icon><el-icon><TrendCharts /></el-icon></template>
                      抽卡记录
                    </el-button>
                    <el-button
                      size="small"
                      link
                      class="action-btn-link"
                      v-if="role.supported_assets.includes('redeem')"
                      @click="jumpToRedeem(account.account_id, role.game)"
                    >
                      <template #icon><el-icon><Ticket /></el-icon></template>
                      兑换码
                    </el-button>
                    <div class="flex-spacer"></div>
                    <div class="action-hint">查看详情 <el-icon><ArrowRight /></el-icon></div>
                  </footer>
                </div>
              </article>
            </div>
          </section>
        </div>
      </template>
    </el-skeleton>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { 
  Refresh, User, Location, Calendar, Ticket, 
  TrendCharts, Coin, Timer, CircleCheck, CircleClose, Warning,
  ArrowRight
} from '@element-plus/icons-vue'
import { assetApi } from '../api'
import { getGameName } from '../constants/game'

function formatTimeAgo(value?: string | null) {
  if (!value) return ''
  const date = new Date(value)
  const now = new Date()
  const diff = now.getTime() - date.getTime()
  const minutes = Math.floor(diff / 60000)
  const hours = Math.floor(minutes / 60)
  const days = Math.floor(hours / 24)

  if (days > 0) return `${days}天前`
  if (hours > 0) return `${hours}小时前`
  if (minutes > 0) return `${minutes}分钟前`
  return '刚刚'
}

type RoleAssetCheckin = {
  last_status?: string | null
  last_message?: string | null
  last_executed_at?: string | null
}

type RoleAsset = {
  role_id: number
  game: string
  game_name: string
  game_biz: string
  game_uid: string
  nickname?: string | null
  region?: string | null
  level?: number | null
  is_enabled: boolean
  supported_assets: string[]
  has_gacha_archive: boolean
  recent_checkin: RoleAssetCheckin
}

type RoleAssetAccount = {
  account_id: number
  account_name: string
  nickname?: string | null
  mihoyo_uid?: string | null
  cookie_status: string
  last_refresh_status?: string | null
  roles: RoleAsset[]
}

type RoleAssetOverview = {
  summary: {
    total_accounts: number
    total_roles: number
    gacha_archived_games: number
  }
  accounts: RoleAssetAccount[]
}

const router = useRouter()
const loading = ref(false)
const accountFilter = ref('')
const gameFilter = ref('')
const keyword = ref('')
const overview = ref<RoleAssetOverview>({
  summary: {
    total_accounts: 0,
    total_roles: 0,
    gacha_archived_games: 0,
  },
  accounts: [],
})

const gameOptions = computed(() => Array.from(new Set(
  overview.value.accounts.flatMap((account) => account.roles.map((role) => role.game)),
)))

const filteredAccounts = computed(() => {
  const normalizedKeyword = keyword.value.trim().toLowerCase()
  return overview.value.accounts
    .filter((account) => !accountFilter.value || String(account.account_id) === accountFilter.value)
    .map((account) => ({
      ...account,
      roles: account.roles.filter((role) => {
        if (gameFilter.value && role.game !== gameFilter.value) {
          return false
        }
        if (!normalizedKeyword) {
          return true
        }
        const haystack = `${account.account_name} ${account.mihoyo_uid || ''} ${role.nickname || ''} ${role.game_uid}`.toLowerCase()
        return haystack.includes(normalizedKeyword)
      }),
    }))
    .filter((account) => account.roles.length > 0)
})

const headlineTitle = computed(() => `${overview.value.summary.total_accounts} 个账号 / ${overview.value.summary.total_roles} 个角色`)

const headlineSubtitle = computed(() => {
  if (!overview.value.summary.total_roles) {
    return '先绑定账号并同步角色信息，之后就能查看角色信息。'
  }
  return `${overview.value.summary.gacha_archived_games} 组账号游戏已归档抽卡记录。`
})

async function loadOverview() {
  loading.value = true
  try {
    const { data } = await assetApi.getOverview()
    overview.value = data
  } finally {
    loading.value = false
  }
}

function getCookieStatusText(status: string) {
  if (status === 'reauth_required') return '需重新登录'
  if (status === 'expired') return '登录态过期'
  if (status === 'valid') return '登录态可用'
  return '状态待确认'
}

function getCookieTagType(status: string) {
  if (status === 'reauth_required') return 'danger'
  if (status === 'expired') return 'warning'
  if (status === 'valid') return 'success'
  return 'info'
}

function getRefreshText(status?: string | null) {
  if (status === 'success') return '成功'
  if (status === 'valid') return '有效'
  if (status === 'warning') return '预警'
  if (status === 'network_error') return '网络异常'
  if (status === 'reauth_required') return '需重登'
  return status || '待确认'
}

function getCheckinStatusText(status?: string | null) {
  if (status === 'success') return '签到成功'
  if (status === 'already_signed') return '今日已签'
  if (status === 'failed') return '签到失败'
  if (status === 'risk') return '风控'
  return '暂无记录'
}

function getCheckinNote(message?: string | null, executedAt?: string | null) {
  if (!executedAt) {
    return '还没有这名角色的签到记录'
  }
  return `${formatDateTime(executedAt)} · ${message || '已记录最近一次签到结果'}`
}

function getAssetLabel(asset: string) {
  if (asset === 'checkin') return '签到'
  if (asset === 'gacha') return '抽卡'
  if (asset === 'redeem') return '兑换码'
  return asset
}

function formatDateTime(value?: string | null) {
  if (!value) return '未知时间'
  return new Date(value).toLocaleString('zh-CN')
}

function jumpToGacha(accountId: number, game: string, gameUid: string) {
  router.push({
    path: '/gacha',
    query: {
      account_id: String(accountId),
      game,
      // 角色资产页已经掌握了最精确的角色上下文，这里必须把 `game_uid` 一并透传到抽卡页。
      // 如果误删该字段，拥有多个同游戏角色的账号会在抽卡页默认落到首个 UID，
      // 用户看到的统计、导出和重置对象都会与点击的角色卡片不一致。
      game_uid: gameUid,
    },
  })
}

function jumpToRedeem(accountId: number, game: string) {
  router.push({
    path: '/redeem',
    query: {
      account_id: String(accountId),
      game,
    },
  })
}

onMounted(loadOverview)
</script>

<style scoped>
.asset-page {
  width: 100%;
}

.summary-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 16px;
}

.summary-card {
  padding: 22px;
  border-radius: 20px;
  border: 1px solid var(--border-soft);
  background: var(--bg-elevated);
  box-shadow: var(--shadow-soft);
}

.summary-card-primary {
  background: var(--bg-elevated);
}

.summary-card-warm {
  background: var(--bg-elevated);
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

.filter-card {
  padding: 0;
}

.filter-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
}

.filter-cluster {
  display: flex;
  flex: 1;
  gap: 12px;
  flex-wrap: wrap;
}

.filter-select {
  width: 200px;
}

.filter-search {
  width: 320px;
}

.account-section-list {
  display: flex;
  flex-direction: column;
  gap: 18px;
}

.account-shell {
  padding: 20px;
  border-radius: 24px;
  border: 1px solid var(--border-soft);
  background: var(--bg-elevated);
  box-shadow: var(--shadow-soft);
}

.account-shell-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 18px;
}

.account-title-row {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}

.account-title {
  font-size: 20px;
  font-weight: 700;
  color: var(--text-primary);
}

.account-meta {
  margin-top: 8px;
  font-size: 12px;
  line-height: 1.7;
  color: var(--text-secondary);
}

.role-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 20px;
}

.role-card {
  border-radius: var(--radius-xl);
  background: var(--bg-elevated);
  border: 1px solid var(--border-soft);
  box-shadow: var(--shadow-soft);
  transition: all var(--transition-medium);
  overflow: hidden;
  position: relative;
}

.role-card:hover {
  transform: translateY(-4px);
  box-shadow: var(--shadow-medium);
  border-color: var(--border-strong);
}

.role-card::after {
  content: '';
  position: absolute;
  top: 0; right: 0;
  width: 100px; height: 100px;
  background: radial-gradient(circle at top right, var(--accent-color, transparent), transparent 70%);
  opacity: 0.1;
  pointer-events: none;
}

.role-card-inner {
  padding: 24px;
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.role-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
}

.role-game-badge {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px 10px;
  background: var(--bg-soft);
  border-radius: 999px;
  font-size: 11px;
  font-weight: 700;
  color: var(--text-secondary);
  margin-bottom: 8px;
}

.game-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--accent-color, var(--text-tertiary));
}

.role-nickname {
  margin: 0 0 6px 0;
  font-size: 22px;
  font-weight: 800;
  color: var(--text-primary);
  line-height: 1.2;
}

.role-meta-tags {
  display: flex;
  gap: 12px;
  flex-wrap: wrap;
}

.meta-tag {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 12px;
  color: var(--text-tertiary);
  font-family: var(--font-mono, monospace);
}

.meta-tag .el-icon { font-size: 14px; }

.level-box {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  width: 52px;
  height: 52px;
  background: var(--bg-soft);
  border-radius: 14px;
  border: 1px solid var(--border-soft);
}

.level-label { font-size: 9px; font-weight: 800; color: var(--text-tertiary); }
.level-value { font-size: 20px; font-weight: 800; color: var(--accent-color, var(--text-primary)); font-family: var(--font-mono, monospace); }

.role-status-row {
  display: flex;
  gap: 12px;
}

.status-box {
  flex: 1;
  padding: 16px;
  border-radius: var(--radius-md);
  background: var(--bg-surface-muted);
  border: 1px solid var(--border-soft);
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.status-header {
  font-size: 12px;
  color: var(--text-secondary);
  display: flex;
  align-items: center;
  gap: 6px;
  font-weight: 600;
}

.status-body {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 8px;
}

.status-text {
  font-size: 15px;
  font-weight: 700;
  color: var(--text-primary);
}

.status-time {
  font-size: 11px;
  color: var(--text-tertiary);
}

.status-success { border-left: 3px solid var(--color-success); }
.status-success .status-header .el-icon { color: var(--color-success); }
.status-failed { border-left: 3px solid var(--color-danger); }
.status-failed .status-header .el-icon { color: var(--color-danger); }
.status-risk { border-left: 3px solid var(--color-warning); }

.role-details-group {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding-bottom: 2px;
}

.asset-pills {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}

.asset-pill-mini {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 3px 8px;
  background: var(--bg-info-soft);
  color: var(--text-info);
  border-radius: 6px;
  font-size: 11px;
  font-weight: 700;
}

.asset-pill-mini.muted { background: var(--bg-soft); color: var(--text-tertiary); }

.archive-status {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 11px;
  color: var(--text-success);
  font-weight: 700;
  background: var(--bg-success-soft);
  padding: 3px 8px;
  border-radius: 6px;
}

.role-actions-bar {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-top: 4px;
  padding-top: 16px;
  border-top: 1px dashed var(--border-soft);
}

.action-btn-link {
  font-weight: 700;
  color: var(--text-secondary);
  transition: all var(--transition-fast);
}

.action-btn-link:hover {
  color: var(--brand-primary);
}

.flex-spacer { flex: 1; }

.action-hint {
  font-size: 11px;
  color: var(--text-tertiary);
  display: flex;
  align-items: center;
  gap: 4px;
  opacity: 0;
  transform: translateX(-10px);
  transition: all var(--transition-medium);
}

.role-card:hover .action-hint {
  opacity: 1;
  transform: translateX(0);
}

/* Game Themed Accents */
.game-genshin, .game-hk4e_cn, .game-hk4e_bilibili { --accent-color: #4ade80; }
.game-starrail, .game-hkrpg_cn, .game-hkrpg_bilibili { --accent-color: #818cf8; }
.game-honkai3rd, .game-bh3_cn { --accent-color: #f472b6; }
.game-zenless, .game-nap_cn { --accent-color: #fbbf24; }

@media (max-width: 1280px) {
  .role-grid { grid-template-columns: 1fr; }
}

@media (max-width: 640px) {
  .role-card-inner { padding: 20px; }
  .role-header { flex-direction: column; gap: 16px; }
  .role-stats { align-self: flex-end; }
  .role-nickname { font-size: 20px; }
  .role-actions-bar { flex-wrap: wrap; }
}
</style>
