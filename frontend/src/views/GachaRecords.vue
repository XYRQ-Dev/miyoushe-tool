<template>
  <div class="gacha-page">
    <section class="hero-panel">
      <div class="hero-copy">
        <p class="hero-kicker">Asset Archive</p>
        <h3>抽卡记录中心</h3>
        <p class="hero-desc">
          把抽卡历史沉淀成可检索、可统计的个人档案。首版支持原神与星穹铁道的完整链接导入，
          自动去重并保留基础统计，适合作为后续资产中心的第一块基座。
        </p>
      </div>
      <div class="hero-meta">
        <div class="hero-meta-label">最近导入</div>
        <div class="hero-meta-value">{{ latestImportMessage }}</div>
      </div>
    </section>

    <el-card class="import-card" shadow="never">
      <template #header>
        <div class="section-header">
          <div>
            <div class="section-title">导入抽卡记录</div>
            <div class="section-desc">选择账号与游戏后，粘贴完整抽卡链接即可开始归档。</div>
          </div>
        </div>
      </template>

      <el-form label-position="top">
        <div class="import-grid">
          <el-form-item label="归属账号" class="field-block">
            <el-select
              v-model="selectedAccountId"
              placeholder="请选择账号"
              filterable
              @change="handleAccountChange"
            >
              <el-option
                v-for="account in accounts"
                :key="account.id"
                :label="formatAccountLabel(account)"
                :value="account.id"
              />
            </el-select>
          </el-form-item>

          <el-form-item label="游戏" class="field-block">
            <el-select
              v-model="selectedGame"
              placeholder="请选择游戏"
              :disabled="availableGames.length === 0"
              @change="handleGameChange"
            >
              <el-option
                v-for="option in availableGames"
                :key="option.value"
                :label="option.label"
                :value="option.value"
              />
            </el-select>
          </el-form-item>

          <el-form-item label="完整导入链接" class="field-block field-block-wide">
            <el-input
              v-model="importUrl"
              type="textarea"
              :rows="3"
              resize="none"
              placeholder="请粘贴包含 authkey 的完整抽卡记录链接"
            />
            <div class="field-hint">
              当前只接受完整 URL，不在前端保存历史链接，避免把高敏感参数长时间留在浏览器状态里。
            </div>
          </el-form-item>
        </div>

        <div class="import-actions">
          <el-button
            type="primary"
            :icon="Upload"
            :loading="importing"
            :disabled="!canImport"
            @click="handleImport"
          >
            开始导入
          </el-button>
          <el-button :icon="Refresh" @click="loadPageData">刷新数据</el-button>
        </div>
        <div class="backup-actions">
          <input
            ref="jsonFileInput"
            type="file"
            accept="application/json,.json"
            class="hidden-file-input"
            @change="handleJsonFileChange"
          />
          <el-button
            plain
            :disabled="!selectedAccountId || !selectedGame || importing || jsonImporting"
            :loading="jsonImporting"
            @click="openJsonFilePicker"
          >
            导入 JSON
          </el-button>
          <el-button
            plain
            :disabled="!selectedAccountId || !selectedGame || exporting"
            :loading="exporting"
            @click="handleExportJson"
          >
            导出 JSON
          </el-button>
          <el-button
            type="danger"
            plain
            :disabled="!selectedAccountId || !selectedGame || resetting"
            :loading="resetting"
            @click="handleReset"
          >
            重置当前数据
          </el-button>
        </div>
      </el-form>
    </el-card>

    <div class="stats-grid">
      <div class="stat-card stat-card-primary">
        <div class="stat-label">累计抽数</div>
        <div class="stat-value">{{ summary.total_count || 0 }}</div>
        <div class="stat-note">当前账号在所选游戏下已归档的总抽数</div>
      </div>

      <div class="stat-card">
        <div class="stat-label">五星次数</div>
        <div class="stat-value">{{ summary.five_star_count || 0 }}</div>
        <div class="stat-note">用于快速感知高价值出货数量</div>
      </div>

      <div class="stat-card">
        <div class="stat-label">四星次数</div>
        <div class="stat-value">{{ summary.four_star_count || 0 }}</div>
        <div class="stat-note">首版仅保留基础统计，不推导保底结论</div>
      </div>

      <div class="stat-card">
        <div class="stat-label">最近五星</div>
        <div class="stat-value stat-value-compact">{{ summary.latest_five_star_name || '暂无' }}</div>
        <div class="stat-note">{{ summary.latest_five_star_time || '导入后会显示最近出货时间' }}</div>
      </div>
    </div>

    <div class="content-grid">
      <el-card class="pool-card" shadow="never">
        <template #header>
          <div class="section-header">
            <div>
              <div class="section-title">卡池分布</div>
              <div class="section-desc">优先让用户知道自己的档案主要覆盖了哪些池子。</div>
            </div>
          </div>
        </template>

        <div v-if="summary.pool_summaries?.length" class="pool-list">
          <div v-for="pool in summary.pool_summaries" :key="pool.pool_type" class="pool-item">
            <div class="pool-head">
              <span class="pool-name">{{ pool.pool_name }}</span>
              <span class="pool-count">{{ pool.count }} 抽</span>
            </div>
            <div class="pool-bar">
              <span
                class="pool-bar-fill"
                :style="{ width: `${getPoolRatio(pool.count)}%` }"
              />
            </div>
          </div>
        </div>
        <el-empty
          v-else
          description="还没有可统计的卡池记录"
          :image-size="72"
        />
      </el-card>

      <el-card class="record-card" shadow="never">
        <template #header>
          <div class="section-header section-header-wrap">
            <div>
              <div class="section-title">抽卡明细</div>
              <div class="section-desc">支持按卡池筛选，并按时间倒序查看已归档记录。</div>
            </div>
            <el-select
              v-model="poolFilter"
              class="pool-filter"
              placeholder="全部卡池"
              clearable
              @change="handlePoolChange"
            >
              <el-option
                v-for="pool in summary.pool_summaries || []"
                :key="pool.pool_type"
                :label="pool.pool_name"
                :value="pool.pool_type"
              />
            </el-select>
          </div>
        </template>

        <el-skeleton :loading="recordsLoading" animated :rows="6">
          <template #default>
            <el-empty
              v-if="!records.length"
              description="暂无抽卡记录，先在上方导入一条完整链接"
              :image-size="88"
            />
            <template v-else>
              <el-table :data="records" class="record-table" stripe>
                <el-table-column prop="time_text" label="抽取时间" min-width="168" />
                <el-table-column prop="pool_name" label="卡池" min-width="132" />
                <el-table-column prop="item_name" label="物品" min-width="160" />
                <el-table-column prop="item_type" label="类型" width="96" />
                <el-table-column label="星级" width="108">
                  <template #default="{ row }">
                    <el-tag :type="getRankTagType(row.rank_type)" effect="dark" round>
                      {{ row.rank_type }} 星
                    </el-tag>
                  </template>
                </el-table-column>
              </el-table>

              <div class="record-footer">
                <div class="record-total">共 {{ recordTotal }} 条记录</div>
                <el-pagination
                  background
                  layout="prev, pager, next"
                  :current-page="currentPage"
                  :page-size="pageSize"
                  :total="recordTotal"
                  @current-change="handlePageChange"
                />
              </div>
            </template>
          </template>
        </el-skeleton>
      </el-card>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, useTemplateRef } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Refresh, Upload } from '@element-plus/icons-vue'
import { gachaApi } from '../api'
import { resolveRouteAccountPrefill } from '../utils/accountRoutePrefill'
import { resolveRouteGamePrefill } from '../utils/gameRoutePrefill'

type GameOption = { value: string; label: string }
type GachaAccount = { id: number; nickname?: string; mihoyo_uid?: string; supported_games: string[] }

const GAME_OPTIONS: Record<string, GameOption> = {
  genshin: { value: 'genshin', label: '原神' },
  starrail: { value: 'starrail', label: '星穹铁道' },
}

const accounts = ref<GachaAccount[]>([])
const selectedAccountId = ref<number | null>(null)
const selectedGame = ref('')
const importUrl = ref('')
const importing = ref(false)
const jsonImporting = ref(false)
const exporting = ref(false)
const resetting = ref(false)
const recordsLoading = ref(false)
const summary = ref<any>({ pool_summaries: [] })
const records = ref<any[]>([])
const recordTotal = ref(0)
const currentPage = ref(1)
const pageSize = 20
const poolFilter = ref<string | undefined>()
const latestImportMessage = ref('尚未执行导入')
const jsonFileInput = useTemplateRef<HTMLInputElement>('jsonFileInput')
const route = useRoute()
const routeAccountPrefillConsumed = ref(false)
const routeGamePrefillConsumed = ref(false)

const currentAccount = computed(() => (
  accounts.value.find((account) => account.id === selectedAccountId.value) || null
))

const availableGames = computed(() => {
  if (!currentAccount.value) return []
  return currentAccount.value.supported_games
    .map((game) => GAME_OPTIONS[game])
    .filter(Boolean)
})

const canImport = computed(() => Boolean(
  selectedAccountId.value && selectedGame.value && importUrl.value.trim()
))

function formatAccountLabel(account: GachaAccount) {
  return account.nickname
    ? `${account.nickname}${account.mihoyo_uid ? ` (${account.mihoyo_uid})` : ''}`
    : account.mihoyo_uid || `账号 ${account.id}`
}

function getRankTagType(rankType: string) {
  if (rankType === '5') return 'danger'
  if (rankType === '4') return 'warning'
  return 'info'
}

function getPoolRatio(count: number) {
  const total = summary.value.total_count || 0
  if (!total) return 0
  return Math.max(8, Math.round((count / total) * 100))
}

async function loadAccounts() {
  const { data } = await gachaApi.getAccounts()
  accounts.value = data.accounts || []

  const prefillResult = resolveRouteAccountPrefill(route.query.account_id, {
    consumed: routeAccountPrefillConsumed.value,
    availableAccountIds: accounts.value.map((account) => account.id),
  })
  routeAccountPrefillConsumed.value = prefillResult.consumed
  if (prefillResult.preferredAccountId !== null) {
    // 聚合页跳转到抽卡中心时优先使用 query 传入的账号，保证落地页上下文一致。
    selectedAccountId.value = prefillResult.preferredAccountId
  } else if (!selectedAccountId.value && accounts.value.length) {
    selectedAccountId.value = accounts.value[0].id
  }

  const account = accounts.value.find((item) => item.id === selectedAccountId.value)
  const prefilledGame = resolveRouteGamePrefill(route.query.game, {
    consumed: routeGamePrefillConsumed.value,
    availableGames: account?.supported_games || [],
  })
  routeGamePrefillConsumed.value = prefilledGame.consumed

  if (prefilledGame.preferredGame !== null) {
    // 角色资产页会同时带上账号和游戏上下文，抽卡页应优先落到该账号的对应游戏档案。
    selectedGame.value = prefilledGame.preferredGame
  } else if (account && (!selectedGame.value || !account.supported_games.includes(selectedGame.value))) {
    selectedGame.value = account.supported_games[0] || ''
  }
}

async function loadSummary() {
  if (!selectedAccountId.value || !selectedGame.value) {
    summary.value = { pool_summaries: [] }
    return
  }
  const { data } = await gachaApi.getSummary({
    account_id: selectedAccountId.value,
    game: selectedGame.value,
  })
  summary.value = data
}

async function loadRecords() {
  if (!selectedAccountId.value || !selectedGame.value) {
    records.value = []
    recordTotal.value = 0
    return
  }

  recordsLoading.value = true
  try {
    const { data } = await gachaApi.listRecords({
      account_id: selectedAccountId.value,
      game: selectedGame.value,
      pool_type: poolFilter.value,
      page: currentPage.value,
      page_size: pageSize,
    })
    records.value = data.records || []
    recordTotal.value = data.total || 0
  } finally {
    recordsLoading.value = false
  }
}

async function loadPageData() {
  await loadAccounts()
  await Promise.all([loadSummary(), loadRecords()])
}

async function handleImport() {
  if (!canImport.value) return
  importing.value = true
  try {
    const { data } = await gachaApi.import({
      account_id: selectedAccountId.value,
      game: selectedGame.value,
      import_url: importUrl.value.trim(),
    })
    latestImportMessage.value = `本次新增 ${data.inserted_count} 条，跳过重复 ${data.duplicate_count} 条`
    ElMessage.success(data.message || '抽卡记录导入完成')
    importUrl.value = ''
    currentPage.value = 1
    poolFilter.value = undefined
    await Promise.all([loadSummary(), loadRecords()])
  } finally {
    importing.value = false
  }
}

function openJsonFilePicker() {
  jsonFileInput.value?.click()
}

function normalizeJsonRecords(payload: any) {
  const rawRecords = Array.isArray(payload) ? payload : payload?.records
  if (!Array.isArray(rawRecords)) {
    throw new Error('JSON 文件结构无效，缺少 records 数组')
  }

  return rawRecords.map((record, index) => {
    const recordId = String(record.record_id ?? record.id ?? '').trim()
    const poolType = String(record.pool_type ?? '').trim()
    const itemName = String(record.item_name ?? '').trim()
    const rankType = String(record.rank_type ?? '').trim()
    const timeText = String(record.time_text ?? record.time ?? '').trim()

    if (!recordId || !poolType || !itemName || !rankType || !timeText) {
      throw new Error(`第 ${index + 1} 条记录缺少关键字段`)
    }

    return {
      record_id: recordId,
      pool_type: poolType,
      pool_name: record.pool_name ?? null,
      item_name: itemName,
      item_type: record.item_type ?? null,
      rank_type: rankType,
      time_text: timeText,
    }
  })
}

async function handleJsonFileChange(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  if (!file || !selectedAccountId.value || !selectedGame.value) {
    input.value = ''
    return
  }

  jsonImporting.value = true
  try {
    const text = await file.text()
    const parsed = JSON.parse(text)
    const records = normalizeJsonRecords(parsed)
    const { data } = await gachaApi.importJson({
      account_id: selectedAccountId.value,
      game: selectedGame.value,
      source_name: file.name,
      records,
    })
    latestImportMessage.value = `JSON 导入新增 ${data.inserted_count} 条，跳过重复 ${data.duplicate_count} 条`
    ElMessage.success(data.message || 'JSON 导入完成')
    currentPage.value = 1
    poolFilter.value = undefined
    await Promise.all([loadSummary(), loadRecords()])
  } catch (error: any) {
    if (error instanceof SyntaxError) {
      ElMessage.error('JSON 文件格式无效，请检查内容后重试')
    } else if (error instanceof Error) {
      ElMessage.error(error.message)
    }
  } finally {
    input.value = ''
    jsonImporting.value = false
  }
}

async function handleExportJson() {
  if (!selectedAccountId.value || !selectedGame.value) return

  exporting.value = true
  try {
    const { data } = await gachaApi.exportJson({
      account_id: selectedAccountId.value,
      game: selectedGame.value,
    })

    const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = `gacha-${selectedGame.value}-account-${selectedAccountId.value}.json`
    document.body.appendChild(link)
    link.click()
    document.body.removeChild(link)
    URL.revokeObjectURL(url)
    ElMessage.success(`已导出 ${data.total || 0} 条抽卡记录`)
  } finally {
    exporting.value = false
  }
}

async function handleReset() {
  if (!selectedAccountId.value || !selectedGame.value) return

  const accountLabel = currentAccount.value
    ? formatAccountLabel(currentAccount.value as GachaAccount)
    : `账号 ${selectedAccountId.value}`
  try {
    await ElMessageBox.confirm(
      `将删除账号“${accountLabel}”在当前游戏下的全部抽卡记录和导入历史，且不可恢复。`,
      '重置当前抽卡数据',
      {
        type: 'warning',
        confirmButtonText: '确认重置',
        cancelButtonText: '取消',
        confirmButtonClass: 'el-button--danger',
      }
    )
  } catch {
    return
  }

  resetting.value = true
  try {
    const { data } = await gachaApi.reset({
      account_id: selectedAccountId.value,
      game: selectedGame.value,
    })
    latestImportMessage.value = '当前抽卡数据已重置'
    ElMessage.success(data.message || '抽卡记录已重置')
    currentPage.value = 1
    poolFilter.value = undefined
    await Promise.all([loadSummary(), loadRecords()])
  } finally {
    resetting.value = false
  }
}

function handleAccountChange() {
  currentPage.value = 1
  poolFilter.value = undefined
  const account = currentAccount.value
  if (account && !account.supported_games.includes(selectedGame.value)) {
    selectedGame.value = account.supported_games[0] || ''
  }
  loadPageData()
}

function handleGameChange() {
  currentPage.value = 1
  poolFilter.value = undefined
  loadPageData()
}

function handlePoolChange() {
  currentPage.value = 1
  loadRecords()
}

function handlePageChange(page: number) {
  currentPage.value = page
  loadRecords()
}

onMounted(loadPageData)
</script>

<style scoped>
.gacha-page {
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
  padding: 28px;
  border-radius: 24px;
  background:
    radial-gradient(circle at top right, rgba(129, 140, 248, 0.34), transparent 30%),
    radial-gradient(circle at left bottom, rgba(244, 114, 182, 0.2), transparent 30%),
    linear-gradient(135deg, rgba(30, 27, 75, 0.96), rgba(67, 56, 202, 0.9));
  color: #eef2ff;
  box-shadow: 0 20px 48px rgba(49, 46, 129, 0.24);
}

.hero-kicker {
  font-size: 12px;
  letter-spacing: 0.18em;
  text-transform: uppercase;
  color: rgba(224, 231, 255, 0.78);
  margin-bottom: 10px;
}

.hero-copy h3 {
  font-size: 28px;
  font-weight: 700;
}

.hero-desc {
  max-width: 760px;
  margin-top: 12px;
  line-height: 1.75;
  color: rgba(224, 231, 255, 0.88);
}

.hero-meta {
  min-width: 220px;
  padding: 18px;
  border-radius: 18px;
  background: rgba(15, 23, 42, 0.18);
  border: 1px solid rgba(255, 255, 255, 0.12);
  backdrop-filter: blur(12px);
}

.hero-meta-label {
  font-size: 12px;
  color: rgba(224, 231, 255, 0.72);
}

.hero-meta-value {
  margin-top: 10px;
  line-height: 1.6;
  font-size: 15px;
  font-weight: 600;
}

.import-card,
.pool-card,
.record-card {
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

.import-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 18px;
}

.field-block {
  margin-bottom: 0;
}

.field-block-wide {
  grid-column: 1 / -1;
}

.field-hint {
  margin-top: 8px;
  line-height: 1.6;
  font-size: 12px;
  color: var(--text-secondary);
}

.import-actions {
  margin-top: 20px;
  display: flex;
  gap: 12px;
}

.backup-actions {
  margin-top: 14px;
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
}

.hidden-file-input {
  display: none;
}

.import-actions :deep(.el-button--primary) {
  background: linear-gradient(135deg, #6366f1 0%, #8b5cf6 100%);
  border: none;
  box-shadow: 0 14px 24px rgba(99, 102, 241, 0.22);
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
    linear-gradient(180deg, rgba(255, 255, 255, 0.96), rgba(248, 250, 252, 0.92));
  border: 1px solid rgba(148, 163, 184, 0.16);
  box-shadow: 0 12px 28px rgba(15, 23, 42, 0.08);
}

.stat-card-primary {
  background:
    radial-gradient(circle at top right, rgba(129, 140, 248, 0.24), transparent 34%),
    linear-gradient(180deg, rgba(255, 255, 255, 0.98), rgba(238, 242, 255, 0.94));
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

.stat-value-compact {
  font-size: 22px;
}

.stat-note {
  margin-top: 12px;
  line-height: 1.6;
  font-size: 12px;
  color: var(--text-secondary);
}

.content-grid {
  display: grid;
  grid-template-columns: 320px minmax(0, 1fr);
  gap: 16px;
  align-items: start;
}

.pool-list {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.pool-item {
  padding: 14px;
  border-radius: 16px;
  background: var(--bg-color);
  border: 1px solid var(--border-color);
}

.pool-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.pool-name {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary);
}

.pool-count {
  font-size: 12px;
  color: var(--text-secondary);
}

.pool-bar {
  margin-top: 12px;
  height: 8px;
  border-radius: 999px;
  background: rgba(148, 163, 184, 0.16);
  overflow: hidden;
}

.pool-bar-fill {
  display: block;
  height: 100%;
  border-radius: inherit;
  background: linear-gradient(135deg, #6366f1 0%, #ec4899 100%);
}

.pool-filter {
  width: 220px;
}

.record-table :deep(th) {
  background: rgba(99, 102, 241, 0.06);
  color: var(--text-primary);
}

.record-table :deep(.el-table__row td) {
  padding-top: 14px;
  padding-bottom: 14px;
}

.record-footer {
  margin-top: 18px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
}

.record-total {
  font-size: 13px;
  color: var(--text-secondary);
}

:deep(html.dark) .hero-panel,
:deep(.dark) .hero-panel {
  box-shadow: 0 20px 48px rgba(2, 6, 23, 0.35);
}

:deep(html.dark) .stat-card,
:deep(.dark) .stat-card {
  background:
    linear-gradient(180deg, rgba(30, 41, 59, 0.96), rgba(15, 23, 42, 0.92));
  border-color: rgba(99, 102, 241, 0.16);
}

:deep(html.dark) .stat-card-primary,
:deep(.dark) .stat-card-primary {
  background:
    radial-gradient(circle at top right, rgba(129, 140, 248, 0.18), transparent 34%),
    linear-gradient(180deg, rgba(30, 41, 59, 0.98), rgba(30, 27, 75, 0.78));
}

:deep(html.dark) .pool-item,
:deep(.dark) .pool-item {
  background: rgba(15, 23, 42, 0.52);
}

@media (max-width: 1100px) {
  .stats-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .content-grid {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 768px) {
  .gacha-page {
    gap: 16px;
  }

  .hero-panel {
    flex-direction: column;
    padding: 22px;
  }

  .hero-copy h3 {
    font-size: 24px;
  }

  .hero-meta {
    width: 100%;
  }

  .import-grid,
  .stats-grid {
    grid-template-columns: 1fr;
  }

  .record-footer {
    flex-direction: column;
    align-items: flex-start;
  }

  .pool-filter {
    width: 100%;
  }

  .backup-actions {
    flex-direction: column;
    align-items: stretch;
  }
}
</style>
