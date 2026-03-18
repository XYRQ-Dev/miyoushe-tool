<template>
  <div class="redeem-page">
    <section class="hero-panel">
      <div class="hero-copy">
        <p class="hero-kicker">Code Control</p>
        <h3>兑换码中心</h3>
        <p class="hero-desc">
          把看到兑换码、选账号执行、回看结果留痕收敛到一个页面。首版聚焦原神与星穹铁道，
          支持按游戏筛选账号、批量执行和查看历史批次。
        </p>
      </div>
      <div class="hero-meta">
        <div class="hero-meta-label">最近一批</div>
        <div class="hero-meta-value">{{ latestBatchTitle }}</div>
        <div class="hero-meta-subtitle">{{ latestBatchSummary }}</div>
      </div>
    </section>

    <el-card class="control-card" shadow="never">
      <template #header>
        <div class="section-header">
          <div>
            <div class="section-title">执行台</div>
            <div class="section-desc">先选游戏与账号，再输入兑换码发起批量执行。</div>
          </div>
          <el-button :icon="Refresh" :loading="accountsLoading || batchesLoading" @click="refreshAll">
            刷新数据
          </el-button>
        </div>
      </template>

      <div class="control-grid">
        <div class="control-main">
          <el-form label-position="top">
            <div class="form-grid">
              <el-form-item label="游戏">
                <el-select v-model="selectedGame" placeholder="请选择游戏" @change="handleGameChange">
                  <el-option
                    v-for="option in gameOptions"
                    :key="option.value"
                    :label="option.label"
                    :value="option.value"
                  />
                </el-select>
              </el-form-item>

              <el-form-item label="兑换码">
                <el-input
                  v-model="redeemCode"
                  maxlength="100"
                  placeholder="请输入或粘贴兑换码"
                  @keyup.enter="handleExecute"
                />
                <div class="field-hint">
                  兑换码不会保存在浏览器草稿中，避免公共设备上留下无关历史。
                </div>
              </el-form-item>
            </div>
          </el-form>

          <div class="account-header">
            <div>
              <div class="section-title">目标账号</div>
              <div class="section-desc">
                当前游戏下共 {{ filteredAccounts.length }} 个可执行账号，已选择 {{ selectedAccountIds.length }} 个。
              </div>
            </div>
            <div class="account-actions" v-if="filteredAccounts.length">
              <el-button text @click="selectAllAccounts">全选</el-button>
              <el-button text @click="clearSelectedAccounts">清空</el-button>
            </div>
          </div>

          <el-empty
            v-if="!filteredAccounts.length"
            class="account-empty"
            :image-size="72"
            description="当前没有可用于该游戏兑换的账号"
          />
          <div v-else class="account-grid">
            <label
              v-for="account in filteredAccounts"
              :key="account.id"
              class="account-tile"
              :class="{ 'account-tile-selected': isAccountSelected(account.id) }"
            >
              <input
                class="account-checkbox"
                type="checkbox"
                :checked="isAccountSelected(account.id)"
                @change="toggleAccount(account.id)"
              >
              <div class="account-tile-top">
                <div class="account-name">{{ formatAccountLabel(account) }}</div>
                <el-tag
                  size="small"
                  round
                  effect="plain"
                  :type="isAccountSelected(account.id) ? 'warning' : 'info'"
                >
                  {{ isAccountSelected(account.id) ? '已选择' : '待选择' }}
                </el-tag>
              </div>
              <div class="account-meta">
                支持 {{ account.supported_games.map((game) => getGameName(game)).join(' / ') }}
              </div>
            </label>
          </div>
        </div>

        <div class="control-side">
          <div class="action-summary">
            <div class="summary-kicker">Batch Preview</div>
            <div class="summary-title">{{ getGameName(selectedGame) || '请选择游戏' }}</div>
            <div class="summary-value">{{ selectedAccountIds.length }}</div>
            <div class="summary-caption">个账号将接收本次兑换</div>
          </div>

          <el-button
            type="primary"
            class="execute-button"
            :icon="Lightning"
            :loading="executing"
            :disabled="!canExecute"
            @click="handleExecute"
          >
            立即执行兑换
          </el-button>

          <div class="status-list">
            <div class="status-item">
              <span class="status-dot status-dot-success" />
              <span>成功、已兑换、无效码会分别归档，方便后续追溯。</span>
            </div>
            <div class="status-item">
              <span class="status-dot status-dot-warning" />
              <span>登录态失效的账号会直接标记，不会把整批任务打成 500。</span>
            </div>
          </div>
        </div>
      </div>
    </el-card>

    <div class="stats-grid">
      <div class="stat-card stat-card-primary">
        <div class="stat-label">最近批次账号数</div>
        <div class="stat-value">{{ latestBatch?.total_accounts || 0 }}</div>
        <div class="stat-note">当前选中历史批次覆盖的账号总数</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">成功兑换</div>
        <div class="stat-value">{{ latestBatch?.success_count || 0 }}</div>
        <div class="stat-note">真正完成兑换的账号数量</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">重复兑换</div>
        <div class="stat-value">{{ latestBatch?.already_redeemed_count || 0 }}</div>
        <div class="stat-note">已在历史中兑换过该码的账号</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">失败账号</div>
        <div class="stat-value">{{ latestBatch?.failed_count || 0 }}</div>
        <div class="stat-note">统计无效码、登录失效和其他异常账号</div>
      </div>
    </div>

    <div class="content-grid">
      <el-card class="history-card" shadow="never">
        <template #header>
          <div class="section-header section-header-wrap">
            <div>
              <div class="section-title">批次历史</div>
              <div class="section-desc">按游戏查看已经执行过的兑换批次。</div>
            </div>
            <el-tag round type="warning" effect="plain">
              {{ getGameName(selectedGame) }} · {{ batches.length }} 批
            </el-tag>
          </div>
        </template>

        <el-skeleton :loading="batchesLoading" animated :rows="6">
          <template #default>
            <el-empty
              v-if="!batches.length"
              :image-size="84"
              :description="selectedGame ? `还没有 ${getGameName(selectedGame)} 的兑换批次` : '还没有兑换批次'"
            />
            <div v-else class="history-list">
              <button
                v-for="batch in batches"
                :key="batch.batch_id"
                type="button"
                class="history-item"
                :class="{ 'history-item-active': selectedBatchId === batch.batch_id }"
                @click="handleBatchSelect(batch.batch_id)"
              >
                <div class="history-item-top">
                  <div class="history-code">{{ batch.code }}</div>
                  <el-tag size="small" :type="getBatchTagType(batch)" effect="dark" round>
                    {{ batch.success_count }}/{{ batch.total_accounts }}
                  </el-tag>
                </div>
                <div class="history-meta">
                  <span>{{ getGameName(batch.game) }}</span>
                  <span>{{ formatDateTime(batch.created_at) }}</span>
                </div>
                <div class="history-badges">
                  <span class="mini-pill mini-pill-success">成 {{ batch.success_count }}</span>
                  <span class="mini-pill mini-pill-warning">重 {{ batch.already_redeemed_count }}</span>
                  <span class="mini-pill mini-pill-danger">败 {{ batch.failed_count }}</span>
                </div>
              </button>
            </div>
          </template>
        </el-skeleton>
      </el-card>

      <el-card class="detail-card" shadow="never">
        <template #header>
          <div class="section-header section-header-wrap">
            <div>
              <div class="section-title">批次详情</div>
              <div class="section-desc">查看单账号执行状态、原因和时间留痕。</div>
            </div>
            <el-button
              text
              :icon="Refresh"
              :disabled="!selectedBatchId"
              :loading="detailLoading"
              @click="reloadSelectedBatch"
            >
              刷新详情
            </el-button>
          </div>
        </template>

        <el-skeleton :loading="detailLoading" animated :rows="8">
          <template #default>
            <el-empty
              v-if="!latestBatch"
              description="选择左侧批次后查看详细结果"
              :image-size="88"
            />
            <template v-else>
              <div class="detail-summary">
                <div class="detail-chip detail-chip-code">{{ latestBatch.code }}</div>
                <div class="detail-chip">{{ getGameName(latestBatch.game) }}</div>
                <div class="detail-chip">共 {{ latestBatch.total_accounts }} 个账号</div>
              </div>

              <div class="detail-stats">
                <div class="detail-stat detail-stat-success">
                  <span>成功</span>
                  <strong>{{ latestBatch.success_count }}</strong>
                </div>
                <div class="detail-stat detail-stat-warning">
                  <span>重复</span>
                  <strong>{{ latestBatch.already_redeemed_count }}</strong>
                </div>
                <div class="detail-stat detail-stat-danger">
                  <span>无效码</span>
                  <strong>{{ latestBatch.invalid_code_count }}</strong>
                </div>
                <div class="detail-stat">
                  <span>失效登录</span>
                  <strong>{{ latestBatch.invalid_cookie_count }}</strong>
                </div>
                <div class="detail-stat detail-stat-danger-soft">
                  <span>其他异常</span>
                  <strong>{{ latestBatch.error_count }}</strong>
                </div>
              </div>
              <div class="detail-stat-hint">
                其他异常包含网络波动、执行异常，以及当前账号未配置该游戏角色的未适配情况。
              </div>

              <div class="execution-list">
                <article
                  v-for="item in latestBatch.executions"
                  :key="item.id"
                  class="execution-item"
                >
                  <div class="execution-head">
                    <div>
                      <div class="execution-account">{{ item.account_name }}</div>
                      <div class="execution-time">{{ formatDateTime(item.executed_at) }}</div>
                    </div>
                    <el-tag
                      round
                      effect="dark"
                      :type="getExecutionTagType(item.status)"
                    >
                      {{ getExecutionStatusText(item.status) }}
                    </el-tag>
                  </div>
                  <div class="execution-message">
                    {{ item.message || '上游未返回额外说明' }}
                  </div>
                  <div v-if="item.upstream_code !== null && item.upstream_code !== undefined" class="execution-code">
                    上游状态码：{{ item.upstream_code }}
                  </div>
                </article>
              </div>
            </template>
          </template>
        </el-skeleton>
      </el-card>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Lightning, Refresh } from '@element-plus/icons-vue'
import { redeemApi } from '../api'
import { getGameName } from '../constants/game'
import { resolveRouteAccountPrefill } from '../utils/accountRoutePrefill'

type GameOption = { value: string; label: string }

type RedeemAccount = {
  id: number
  nickname?: string | null
  mihoyo_uid?: string | null
  supported_games: string[]
}

type RedeemExecution = {
  id: number
  account_id: number
  account_name: string
  game: string
  status: string
  upstream_code?: number | null
  message?: string | null
  executed_at: string
}

type RedeemBatch = {
  batch_id: number
  code: string
  game: string
  total_accounts: number
  success_count: number
  already_redeemed_count: number
  invalid_code_count: number
  invalid_cookie_count: number
  error_count: number
  failed_count: number
  message?: string | null
  created_at: string
}

type RedeemBatchDetail = RedeemBatch & {
  executions: RedeemExecution[]
}

const GAME_OPTIONS: GameOption[] = [
  { value: 'genshin', label: '原神' },
  { value: 'starrail', label: '星穹铁道' },
]

const accounts = ref<RedeemAccount[]>([])
const selectedGame = ref('genshin')
const selectedAccountIds = ref<number[]>([])
const redeemCode = ref('')
const batches = ref<RedeemBatch[]>([])
const selectedBatchId = ref<number | null>(null)
const latestBatch = ref<RedeemBatchDetail | null>(null)
const accountsLoading = ref(false)
const batchesLoading = ref(false)
const detailLoading = ref(false)
const executing = ref(false)
const route = useRoute()
const routeAccountPrefillConsumed = ref(false)

const gameOptions = computed(() => GAME_OPTIONS)

const filteredAccounts = computed(() => accounts.value.filter(
  (account) => account.supported_games.includes(selectedGame.value)
))

const latestBatchTitle = computed(() => {
  if (!latestBatch.value) return '尚未执行兑换'
  return `${getGameName(latestBatch.value.game)} · ${latestBatch.value.code}`
})

const latestBatchSummary = computed(() => {
  if (!latestBatch.value) return '执行后会在这里显示最近一次批次结果'
  return `成功 ${latestBatch.value.success_count} / 重复 ${latestBatch.value.already_redeemed_count} / 失败 ${latestBatch.value.failed_count}`
})

const canExecute = computed(() => Boolean(
  selectedGame.value && redeemCode.value.trim() && selectedAccountIds.value.length > 0 && !executing.value
))

function formatAccountLabel(account: RedeemAccount) {
  return account.nickname
    ? `${account.nickname}${account.mihoyo_uid ? ` (${account.mihoyo_uid})` : ''}`
    : account.mihoyo_uid || `账号 ${account.id}`
}

function formatDateTime(value?: string | null) {
  if (!value) return '未知时间'
  return new Date(value).toLocaleString('zh-CN')
}

function isAccountSelected(accountId: number) {
  return selectedAccountIds.value.includes(accountId)
}

function toggleAccount(accountId: number) {
  if (isAccountSelected(accountId)) {
    selectedAccountIds.value = selectedAccountIds.value.filter((id) => id !== accountId)
    return
  }
  selectedAccountIds.value = [...selectedAccountIds.value, accountId]
}

function selectAllAccounts() {
  selectedAccountIds.value = filteredAccounts.value.map((account) => account.id)
}

function clearSelectedAccounts() {
  selectedAccountIds.value = []
}

function syncSelectedAccounts() {
  const allowedIds = new Set(filteredAccounts.value.map((account) => account.id))
  selectedAccountIds.value = selectedAccountIds.value.filter((accountId) => allowedIds.has(accountId))
}

function applyPreferredAccountSelection() {
  const prefillResult = resolveRouteAccountPrefill(route.query.account_id, {
    consumed: routeAccountPrefillConsumed.value,
    availableAccountIds: accounts.value.map((account) => account.id),
  })
  routeAccountPrefillConsumed.value = prefillResult.consumed
  if (prefillResult.preferredAccountId === null) {
    syncSelectedAccounts()
    return
  }

  const preferredAccount = accounts.value.find((account) => account.id === prefillResult.preferredAccountId)
  if (!preferredAccount) {
    syncSelectedAccounts()
    return
  }

  if (!preferredAccount.supported_games.includes(selectedGame.value)) {
    selectedGame.value = preferredAccount.supported_games[0] || selectedGame.value
  }

  if (preferredAccount.supported_games.includes(selectedGame.value)) {
    // 从健康中心跳进兑换页时默认只保留目标账号，避免沿用历史批量勾选误发兑换请求。
    selectedAccountIds.value = [prefillResult.preferredAccountId]
    return
  }

  syncSelectedAccounts()
}

async function loadAccounts() {
  accountsLoading.value = true
  try {
    const { data } = await redeemApi.listAccounts()
    accounts.value = data.accounts || []

    if (!accounts.value.some((account) => account.supported_games.includes(selectedGame.value))) {
      const firstSupportedGame = accounts.value.find((account) => account.supported_games.length)?.supported_games[0]
      selectedGame.value = firstSupportedGame || 'genshin'
    }
    applyPreferredAccountSelection()
  } catch (error) {
    // 账号源失败时直接清空本地状态，避免用户继续对旧账号集合做批量操作。
    accounts.value = []
    selectedAccountIds.value = []
    batches.value = []
    selectedBatchId.value = null
    latestBatch.value = null
    throw error
  } finally {
    accountsLoading.value = false
  }
}

async function loadBatches() {
  batchesLoading.value = true
  try {
    const { data } = await redeemApi.listBatches(selectedGame.value ? { game: selectedGame.value } : undefined)
    batches.value = data.items || []

    if (!batches.value.length) {
      selectedBatchId.value = null
      latestBatch.value = null
      return
    }

    if (!selectedBatchId.value || !batches.value.some((item) => item.batch_id === selectedBatchId.value)) {
      selectedBatchId.value = batches.value[0].batch_id
    }

    await loadBatchDetail(selectedBatchId.value)
  } catch (error) {
    batches.value = []
    selectedBatchId.value = null
    latestBatch.value = null
    throw error
  } finally {
    batchesLoading.value = false
  }
}

async function loadBatchDetail(batchId: number | null) {
  if (!batchId) {
    latestBatch.value = null
    return
  }

  detailLoading.value = true
  try {
    const { data } = await redeemApi.getBatch(batchId)
    latestBatch.value = data
    selectedBatchId.value = data.batch_id
  } catch (error) {
    latestBatch.value = null
    throw error
  } finally {
    detailLoading.value = false
  }
}

async function refreshAll() {
  try {
    await loadAccounts()
    await loadBatches()
  } catch {
    // 具体提示由拦截器统一负责，这里只保证页面状态已收敛。
  }
}

async function handleGameChange() {
  syncSelectedAccounts()
  try {
    await loadBatches()
  } catch {
    // 保留用户当前游戏选择，但批次区域按最新失败状态清空，避免混入旧游戏的数据。
  }
}

async function handleBatchSelect(batchId: number) {
  try {
    await loadBatchDetail(batchId)
  } catch {
    // 失败后保留当前选中批次 id，便于用户重试，不回退到其他批次。
    selectedBatchId.value = batchId
  }
}

async function reloadSelectedBatch() {
  try {
    await loadBatchDetail(selectedBatchId.value)
  } catch {
    // 无额外处理，详情区域已在 loadBatchDetail 内清空。
  }
}

function getExecutionStatusText(status: string) {
  if (status === 'success') return '兑换成功'
  if (status === 'already_redeemed') return '已兑换'
  if (status === 'invalid_code') return '无效兑换码'
  if (status === 'invalid_cookie') return '登录失效'
  if (status === 'unsupported_game') return '未适配'
  if (status === 'network_error') return '网络异常'
  return '执行异常'
}

function getExecutionTagType(status: string) {
  if (status === 'success') return 'success'
  if (status === 'already_redeemed') return 'warning'
  if (status === 'invalid_code' || status === 'invalid_cookie') return 'danger'
  return 'info'
}

function getBatchTagType(batch: RedeemBatch) {
  if (batch.failed_count === 0 && batch.already_redeemed_count === 0) return 'success'
  if (batch.failed_count === 0) return 'warning'
  if (batch.success_count > 0) return 'warning'
  return 'danger'
}

async function handleExecute() {
  if (!canExecute.value) return

  const confirmedAccountCount = selectedAccountIds.value.length
  try {
    await ElMessageBox.confirm(
      `将对 ${confirmedAccountCount} 个账号执行 ${getGameName(selectedGame.value)} 兑换码“${redeemCode.value.trim()}”，该操作不可回滚。`,
      '确认批量兑换',
      {
        type: 'warning',
        confirmButtonText: '确认执行',
        cancelButtonText: '取消',
        confirmButtonClass: 'el-button--warning',
      }
    )
  } catch {
    return
  }

  executing.value = true
  try {
    const { data } = await redeemApi.execute({
      game: selectedGame.value,
      code: redeemCode.value.trim(),
      account_ids: selectedAccountIds.value,
    })
    latestBatch.value = data
    selectedBatchId.value = data.batch_id
    redeemCode.value = ''
    ElMessage.success(`已完成 ${data.total_accounts} 个账号的兑换执行`)
    await loadBatches()
  } catch {
    // 执行失败时保留输入与勾选状态，方便用户修正后重试。
  } finally {
    executing.value = false
  }
}

onMounted(refreshAll)
</script>

<style scoped>
.redeem-page {
  max-width: 1280px;
  margin: 0 auto;
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.hero-panel {
  display: flex;
  justify-content: space-between;
  gap: 24px;
  align-items: flex-start;
  padding: 30px;
  border-radius: 26px;
  background:
    radial-gradient(circle at top right, rgba(251, 191, 36, 0.28), transparent 32%),
    radial-gradient(circle at left bottom, rgba(248, 113, 113, 0.24), transparent 34%),
    linear-gradient(135deg, rgba(120, 53, 15, 0.96), rgba(180, 83, 9, 0.92));
  color: #fff7ed;
  box-shadow: 0 22px 48px rgba(146, 64, 14, 0.24);
}

.hero-kicker {
  margin-bottom: 10px;
  font-size: 12px;
  letter-spacing: 0.18em;
  text-transform: uppercase;
  color: rgba(255, 237, 213, 0.76);
}

.hero-copy h3 {
  font-size: 30px;
  font-weight: 700;
}

.hero-desc {
  max-width: 760px;
  margin-top: 12px;
  line-height: 1.78;
  color: rgba(255, 247, 237, 0.88);
}

.hero-meta {
  min-width: 250px;
  padding: 18px;
  border-radius: 18px;
  background: rgba(124, 45, 18, 0.24);
  border: 1px solid rgba(255, 255, 255, 0.12);
  backdrop-filter: blur(12px);
}

.hero-meta-label {
  font-size: 12px;
  color: rgba(255, 237, 213, 0.72);
}

.hero-meta-value {
  margin-top: 10px;
  font-size: 18px;
  font-weight: 700;
  line-height: 1.45;
}

.hero-meta-subtitle {
  margin-top: 10px;
  font-size: 13px;
  line-height: 1.7;
  color: rgba(255, 247, 237, 0.82);
}

.control-card,
.history-card,
.detail-card {
  border-radius: 20px;
  border: 1px solid var(--border-color);
}

.section-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
}

.section-header-wrap {
  flex-wrap: wrap;
}

.section-title {
  font-size: 16px;
  font-weight: 700;
  color: var(--text-primary);
}

.section-desc {
  margin-top: 4px;
  font-size: 13px;
  color: var(--text-secondary);
}

.control-grid {
  display: grid;
  grid-template-columns: minmax(0, 1.45fr) 320px;
  gap: 18px;
}

.form-grid {
  display: grid;
  grid-template-columns: 220px minmax(0, 1fr);
  gap: 18px;
}

.field-hint {
  margin-top: 8px;
  font-size: 12px;
  line-height: 1.6;
  color: var(--text-secondary);
}

.account-header {
  margin-top: 8px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
}

.account-actions {
  display: flex;
  gap: 4px;
}

.account-empty {
  padding: 18px 0 6px;
}

.account-grid {
  margin-top: 16px;
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 14px;
}

.account-tile {
  position: relative;
  display: block;
  min-height: 118px;
  padding: 18px;
  border-radius: 18px;
  border: 1px solid rgba(148, 163, 184, 0.18);
  background:
    linear-gradient(180deg, rgba(255, 255, 255, 0.96), rgba(255, 251, 235, 0.88));
  box-shadow: 0 10px 26px rgba(15, 23, 42, 0.06);
  cursor: pointer;
  transition: transform 0.2s ease, box-shadow 0.2s ease, border-color 0.2s ease;
}

.account-tile:hover {
  transform: translateY(-1px);
  box-shadow: 0 16px 30px rgba(180, 83, 9, 0.1);
}

.account-tile-selected {
  border-color: rgba(245, 158, 11, 0.46);
  background:
    radial-gradient(circle at top right, rgba(251, 191, 36, 0.18), transparent 36%),
    linear-gradient(180deg, rgba(255, 251, 235, 0.98), rgba(255, 247, 237, 0.92));
}

.account-checkbox {
  position: absolute;
  top: 16px;
  right: 16px;
  width: 18px;
  height: 18px;
}

.account-tile-top {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  padding-right: 28px;
}

.account-name {
  font-size: 15px;
  font-weight: 700;
  line-height: 1.6;
  color: var(--text-primary);
}

.account-meta {
  margin-top: 10px;
  font-size: 12px;
  line-height: 1.65;
  color: var(--text-secondary);
}

.control-side {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.action-summary {
  padding: 24px;
  border-radius: 22px;
  background:
    radial-gradient(circle at top right, rgba(251, 191, 36, 0.22), transparent 35%),
    linear-gradient(180deg, rgba(255, 255, 255, 0.98), rgba(255, 247, 237, 0.9));
  border: 1px solid rgba(251, 191, 36, 0.24);
  box-shadow: 0 14px 30px rgba(180, 83, 9, 0.08);
}

.summary-kicker {
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.16em;
  text-transform: uppercase;
  color: #b45309;
}

.summary-title {
  margin-top: 10px;
  font-size: 22px;
  font-weight: 700;
  color: #7c2d12;
}

.summary-value {
  margin-top: 18px;
  font-size: 44px;
  line-height: 1;
  font-weight: 800;
  color: #0f172a;
}

.summary-caption {
  margin-top: 10px;
  font-size: 13px;
  line-height: 1.7;
  color: #78716c;
}

.execute-button {
  min-height: 48px;
  background: linear-gradient(135deg, #f59e0b 0%, #ea580c 100%);
  border: none;
  box-shadow: 0 16px 28px rgba(234, 88, 12, 0.22);
}

.status-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 18px;
  border-radius: 18px;
  background: var(--bg-color);
  border: 1px solid var(--border-color);
}

.status-item {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  font-size: 12px;
  line-height: 1.7;
  color: var(--text-secondary);
}

.status-dot {
  width: 10px;
  height: 10px;
  margin-top: 5px;
  border-radius: 999px;
  flex: 0 0 auto;
}

.status-dot-success {
  background: #10b981;
}

.status-dot-warning {
  background: #f59e0b;
}

.stats-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 16px;
}

.stat-card {
  border-radius: 20px;
  padding: 22px;
  background:
    linear-gradient(180deg, rgba(255, 255, 255, 0.96), rgba(250, 250, 249, 0.92));
  border: 1px solid rgba(148, 163, 184, 0.16);
  box-shadow: 0 12px 28px rgba(15, 23, 42, 0.08);
}

.stat-card-primary {
  background:
    radial-gradient(circle at top right, rgba(251, 191, 36, 0.18), transparent 32%),
    linear-gradient(180deg, rgba(255, 255, 255, 0.98), rgba(255, 247, 237, 0.94));
}

.stat-label {
  font-size: 13px;
  color: var(--text-secondary);
}

.stat-value {
  margin-top: 10px;
  font-size: 32px;
  font-weight: 800;
  line-height: 1.1;
  color: var(--text-primary);
}

.stat-note {
  margin-top: 12px;
  font-size: 12px;
  line-height: 1.6;
  color: var(--text-secondary);
}

.content-grid {
  display: grid;
  grid-template-columns: 360px minmax(0, 1fr);
  gap: 16px;
  align-items: start;
}

.history-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.history-item {
  width: 100%;
  padding: 16px;
  border-radius: 18px;
  border: 1px solid rgba(148, 163, 184, 0.14);
  background: var(--card-bg);
  text-align: left;
  cursor: pointer;
  transition: border-color 0.2s ease, transform 0.2s ease, box-shadow 0.2s ease;
}

.history-item:hover {
  transform: translateY(-1px);
  border-color: rgba(245, 158, 11, 0.32);
  box-shadow: 0 14px 26px rgba(180, 83, 9, 0.08);
}

.history-item-active {
  border-color: rgba(245, 158, 11, 0.42);
  background:
    radial-gradient(circle at top right, rgba(251, 191, 36, 0.14), transparent 36%),
    linear-gradient(180deg, rgba(255, 251, 235, 0.96), rgba(255, 255, 255, 0.94));
}

.history-item-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 14px;
}

.history-code {
  font-size: 15px;
  font-weight: 700;
  color: var(--text-primary);
  word-break: break-all;
}

.history-meta {
  margin-top: 8px;
  display: flex;
  justify-content: space-between;
  gap: 12px;
  font-size: 12px;
  color: var(--text-secondary);
}

.history-badges {
  margin-top: 12px;
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.mini-pill {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-height: 26px;
  padding: 0 10px;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 600;
}

.mini-pill-success {
  background: rgba(16, 185, 129, 0.12);
  color: #047857;
}

.mini-pill-warning {
  background: rgba(245, 158, 11, 0.14);
  color: #b45309;
}

.mini-pill-danger {
  background: rgba(239, 68, 68, 0.12);
  color: #b91c1c;
}

.detail-summary {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
}

.detail-chip {
  display: inline-flex;
  align-items: center;
  min-height: 32px;
  padding: 0 12px;
  border-radius: 999px;
  background: rgba(148, 163, 184, 0.12);
  color: var(--text-primary);
  font-size: 13px;
  font-weight: 600;
}

.detail-chip-code {
  background: rgba(245, 158, 11, 0.12);
  color: #b45309;
}

.detail-stats {
  margin-top: 18px;
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  gap: 12px;
}

.detail-stat-hint {
  margin-top: 12px;
  font-size: 12px;
  line-height: 1.7;
  color: var(--text-secondary);
}

.detail-stat {
  padding: 16px;
  border-radius: 16px;
  background: var(--bg-color);
  border: 1px solid var(--border-color);
}

.detail-stat span {
  display: block;
  font-size: 12px;
  color: var(--text-secondary);
}

.detail-stat strong {
  display: block;
  margin-top: 8px;
  font-size: 24px;
  font-weight: 800;
  color: var(--text-primary);
}

.detail-stat-success {
  background: rgba(16, 185, 129, 0.08);
}

.detail-stat-warning {
  background: rgba(245, 158, 11, 0.08);
}

.detail-stat-danger {
  background: rgba(239, 68, 68, 0.08);
}

.detail-stat-danger-soft {
  background: rgba(248, 113, 113, 0.06);
}

.execution-list {
  margin-top: 18px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.execution-item {
  padding: 18px;
  border-radius: 18px;
  border: 1px solid rgba(148, 163, 184, 0.14);
  background:
    linear-gradient(180deg, rgba(255, 255, 255, 0.98), rgba(248, 250, 252, 0.92));
}

.execution-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
}

.execution-account {
  font-size: 15px;
  font-weight: 700;
  color: var(--text-primary);
}

.execution-time {
  margin-top: 6px;
  font-size: 12px;
  color: var(--text-secondary);
}

.execution-message {
  margin-top: 12px;
  font-size: 13px;
  line-height: 1.7;
  color: var(--text-primary);
}

.execution-code {
  margin-top: 8px;
  font-size: 12px;
  color: var(--text-secondary);
}

:deep(html.dark) .hero-panel,
:deep(.dark) .hero-panel {
  box-shadow: 0 22px 48px rgba(15, 23, 42, 0.36);
}

:deep(html.dark) .account-tile,
:deep(.dark) .account-tile,
:deep(html.dark) .stat-card,
:deep(.dark) .stat-card,
:deep(html.dark) .execution-item,
:deep(.dark) .execution-item {
  background:
    linear-gradient(180deg, rgba(30, 41, 59, 0.96), rgba(15, 23, 42, 0.92));
}

:deep(html.dark) .action-summary,
:deep(.dark) .action-summary {
  background:
    radial-gradient(circle at top right, rgba(251, 191, 36, 0.1), transparent 36%),
    linear-gradient(180deg, rgba(51, 65, 85, 0.98), rgba(30, 41, 59, 0.94));
}

:deep(html.dark) .history-item-active,
:deep(.dark) .history-item-active {
  background:
    radial-gradient(circle at top right, rgba(251, 191, 36, 0.12), transparent 36%),
    linear-gradient(180deg, rgba(51, 65, 85, 0.98), rgba(30, 41, 59, 0.94));
}

@media (max-width: 1180px) {
  .stats-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .content-grid,
  .control-grid {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 820px) {
  .hero-panel {
    flex-direction: column;
    padding: 24px;
  }

  .hero-meta {
    width: 100%;
  }

  .form-grid,
  .account-grid,
  .detail-stats {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 640px) {
  .redeem-page {
    gap: 16px;
  }

  .hero-copy h3 {
    font-size: 24px;
  }

  .stats-grid {
    grid-template-columns: 1fr;
  }

  .history-meta,
  .execution-head,
  .section-header {
    flex-direction: column;
    align-items: flex-start;
  }

  .account-header {
    flex-direction: column;
    align-items: flex-start;
  }
}
</style>
