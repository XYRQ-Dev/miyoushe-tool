<template>
  <div class="app-page asset-page">
    <section class="page-toolbar">
      <div class="page-title-group">
        <div class="page-kicker">Asset Hub</div>
        <h2 class="page-title">角色资产总览</h2>
        <p class="page-desc">{{ headlineSubtitle }}</p>
      </div>
      <div class="page-actions">
        <div class="soft-chip">{{ headlineTitle }}</div>
        <el-button :icon="Refresh" :loading="loading" @click="loadOverview">刷新</el-button>
      </div>
    </section>

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
              >
                <div class="role-card-head">
                  <div>
                    <div class="role-game-row">
                      <span class="role-game-chip">{{ role.game_name }}</span>
                    </div>
                    <div class="role-name">{{ role.nickname || role.game_uid }}</div>
                    <div class="role-meta">
                      UID {{ role.game_uid }}
                      <span v-if="role.region">· {{ role.region }}</span>
                      <span v-if="role.level">· Lv.{{ role.level }}</span>
                    </div>
                  </div>
                  <div class="archive-pill" :class="{ 'archive-pill-active': role.has_gacha_archive }">
                    {{ role.has_gacha_archive ? '已归档抽卡' : '未归档抽卡' }}
                  </div>
                </div>

                <div class="status-grid">
                  <div class="status-card">
                    <div class="status-label">最近签到</div>
                    <div class="status-value">
                      {{ getCheckinStatusText(role.recent_checkin.last_status) }}
                    </div>
                    <div class="status-note">
                      {{ getCheckinNote(role.recent_checkin.last_message, role.recent_checkin.last_executed_at) }}
                    </div>
                  </div>
                </div>

                <div class="chip-group">
                  <span
                    v-for="asset in role.supported_assets"
                    :key="asset"
                    class="asset-chip"
                  >
                    {{ getAssetLabel(asset) }}
                  </span>
                  <span v-if="!role.supported_assets.length" class="asset-chip asset-chip-muted">
                    暂无可用功能
                  </span>
                </div>

                <div class="action-row">
                  <el-button
                    size="small"
                    plain
                    :disabled="!role.supported_assets.includes('gacha')"
                    @click="jumpToGacha(account.account_id, role.game, role.game_uid)"
                  >
                    抽卡记录
                  </el-button>
                  <el-button
                    size="small"
                    type="primary"
                    plain
                    :disabled="!role.supported_assets.includes('redeem')"
                    @click="jumpToRedeem(account.account_id, role.game)"
                  >
                    兑换码
                  </el-button>
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
import { Refresh } from '@element-plus/icons-vue'
import { assetApi } from '../api'
import { getGameName } from '../constants/game'

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
  border: 1px solid rgba(148, 163, 184, 0.16);
  background:
    linear-gradient(180deg, rgba(255, 255, 255, 0.98), rgba(248, 250, 252, 0.94));
  box-shadow: 0 14px 30px rgba(15, 23, 42, 0.06);
}

.summary-card-primary {
  background:
    radial-gradient(circle at top right, rgba(125, 211, 252, 0.18), transparent 32%),
    linear-gradient(180deg, rgba(240, 249, 255, 0.98), rgba(224, 242, 254, 0.84));
}

.summary-card-warm {
  background:
    radial-gradient(circle at top right, rgba(251, 191, 36, 0.16), transparent 34%),
    linear-gradient(180deg, rgba(255, 251, 235, 0.98), rgba(254, 243, 199, 0.84));
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
  border: 1px solid rgba(148, 163, 184, 0.16);
  background:
    linear-gradient(180deg, rgba(255, 255, 255, 0.98), rgba(248, 250, 252, 0.94));
  box-shadow: 0 16px 32px rgba(15, 23, 42, 0.06);
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
  gap: 16px;
}

.role-card {
  padding: 18px;
  border-radius: 22px;
  border: 1px solid rgba(148, 163, 184, 0.14);
  background:
    linear-gradient(180deg, rgba(255, 255, 255, 0.98), rgba(248, 250, 252, 0.94));
  box-shadow: 0 12px 26px rgba(15, 23, 42, 0.05);
}

.role-card-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
}

.role-game-row {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 10px;
  flex-wrap: wrap;
}

.role-game-chip {
  min-height: 28px;
  padding: 0 12px;
  border-radius: 999px;
  display: inline-flex;
  align-items: center;
  background: rgba(15, 23, 42, 0.08);
  color: #0f172a;
  font-size: 12px;
  font-weight: 700;
}

.role-name {
  font-size: 20px;
  font-weight: 700;
  color: var(--text-primary);
}

.role-meta {
  margin-top: 6px;
  font-size: 12px;
  line-height: 1.65;
  color: var(--text-secondary);
}

.archive-pill {
  min-width: 104px;
  padding: 10px 12px;
  border-radius: 16px;
  font-size: 12px;
  line-height: 1.5;
  color: #64748b;
  background: rgba(255, 255, 255, 0.72);
  border: 1px solid rgba(148, 163, 184, 0.16);
}

.archive-pill-active {
  color: #0f766e;
  background: rgba(204, 251, 241, 0.72);
  border-color: rgba(45, 212, 191, 0.26);
}

.status-grid {
  margin-top: 16px;
  display: grid;
  grid-template-columns: 1fr;
  gap: 12px;
}

.status-card {
  padding: 14px;
  border-radius: 16px;
  background: rgba(255, 255, 255, 0.72);
  border: 1px solid rgba(226, 232, 240, 0.88);
}

.status-label {
  font-size: 12px;
  color: var(--text-secondary);
}

.status-value {
  margin-top: 8px;
  font-size: 16px;
  font-weight: 700;
  color: var(--text-primary);
}

.status-note {
  margin-top: 8px;
  font-size: 12px;
  line-height: 1.65;
  color: var(--text-secondary);
}

.chip-group {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 14px;
}

.asset-chip {
  min-height: 28px;
  padding: 0 10px;
  border-radius: 999px;
  display: inline-flex;
  align-items: center;
  background: rgba(14, 165, 233, 0.1);
  color: #0369a1;
  font-size: 12px;
  font-weight: 600;
}

.asset-chip-muted {
  background: rgba(148, 163, 184, 0.12);
  color: var(--text-secondary);
}

.action-row {
  margin-top: 16px;
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

:deep(html.dark) .summary-card,
:deep(.dark) .summary-card,
:deep(html.dark) .account-shell,
:deep(.dark) .account-shell,
:deep(html.dark) .role-card,
:deep(.dark) .role-card {
  background:
    linear-gradient(180deg, rgba(30, 41, 59, 0.96), rgba(15, 23, 42, 0.92));
}

@media (max-width: 1180px) {
  .summary-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .role-grid {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 900px) {
  .filter-row {
    flex-direction: column;
    align-items: flex-start;
  }

  .filter-search,
  .filter-select {
    width: 100%;
  }
}

@media (max-width: 640px) {
  .asset-page {
    gap: 16px;
  }

  .summary-grid {
    grid-template-columns: 1fr;
  }

  .role-card-head {
    flex-direction: column;
  }
}
</style>
