<template>
  <div class="app-page gacha-page">
    <el-alert
      v-if="latestImportMessage !== '尚未执行导入'"
      :title="latestImportMessage"
      type="success"
      show-icon
      :closable="false"
      class="page-info-alert"
    />

    <!-- 顶部全局筛选器 -->
    <div class="global-filters">
      <el-select v-model="selectedAccountId" placeholder="请选择账号" filterable @change="handleAccountChange" class="filter-item">
        <el-option v-for="account in accounts" :key="account.id" :label="formatAccountLabel(account)" :value="account.id" />
      </el-select>

      <el-select v-model="selectedGame" placeholder="请选择游戏" :disabled="availableGames.length === 0" @change="handleGameChange" class="filter-item">
        <el-option v-for="option in availableGames" :key="option.value" :label="option.label" :value="option.value" />
      </el-select>

      <el-select v-model="selectedGameUid" placeholder="请选择角色 UID" :disabled="availableRoles.length === 0" @change="handleRoleChange" class="filter-item">
        <el-option v-for="role in availableRoles" :key="role.game_uid" :label="formatRoleLabel(role)" :value="role.game_uid" />
      </el-select>
    </div>

    <!-- 核心数据展示区 (Tabs) -->
    <el-tabs v-model="activeTab" class="gacha-tabs" @tab-change="handleTabChange">
      <!-- 总览 Tab -->
      <el-tab-pane label="数据总览" name="overview">
        <div class="stats-premium-grid">
          <div class="stat-premium-card highlight">
            <div class="card-inner">
              <el-icon class="card-icon"><TrendCharts /></el-icon>
              <div class="stat-body">
                <div class="label">累计消耗抽数</div>
                <div class="value">{{ summary.total_count || 0 }}</div>
              </div>
            </div>
          </div>
          <div class="stat-premium-card rank-5">
            <div class="card-inner">
              <el-icon class="card-icon"><StarFilled /></el-icon>
              <div class="stat-body">
                <div class="label">五星产出总计</div>
                <div class="value">{{ summary.five_star_count || 0 }}</div>
              </div>
            </div>
          </div>
          <div class="stat-premium-card rank-4">
            <div class="card-inner">
              <el-icon class="card-icon"><StarFilled /></el-icon>
              <div class="stat-body">
                <div class="label">四星产出总计</div>
                <div class="value">{{ summary.four_star_count || 0 }}</div>
              </div>
            </div>
          </div>
          <div class="stat-premium-card latest">
            <div class="card-inner">
              <div class="item-icon-small" v-if="summary.latest_five_star_name">
                <ItemIcon :name="summary.latest_five_star_name" :game="selectedGame" rank-type="5" circle />
              </div>
              <div class="stat-body">
                <div class="label">最近五星</div>
                <div class="value compact">{{ summary.latest_five_star_name || '暂无' }}</div>
              </div>
            </div>
          </div>
        </div>

        <div class="main-content-split">
          <el-card class="pool-summary-card panel-card" shadow="never">
            <template #header>
              <div class="panel-title-row">
                <el-icon><Collection /></el-icon>
                <span>各卡池分布</span>
              </div>
            </template>
            <div v-if="summary.pool_summaries?.length" class="pool-vertical-list">
              <div v-for="pool in summary.pool_summaries" :key="pool.pool_type" class="pool-row">
                <div class="row-top">
                  <span class="name">{{ pool.pool_name }}</span>
                  <span class="count">{{ pool.count }} 抽</span>
                </div>
                <div class="bar-track">
                  <div class="bar-fill" :style="{ width: `${getPoolRatio(pool.count)}%` }"></div>
                </div>
              </div>
            </div>
            <el-empty v-else description="暂无分布数据" :image-size="64" />
          </el-card>

          <el-card class="all-records-card panel-card" shadow="never">
            <template #header>
              <div class="panel-title-row">
                <el-icon><Histogram /></el-icon>
                <span>全量抽卡记录</span>
              </div>
            </template>
            
            <el-skeleton :loading="recordsLoading" animated :rows="6">
              <template #default>
                <div v-if="records.length === 0">
                  <el-empty description="暂无抽卡记录" :image-size="88" />
                </div>
                <div v-else>
                  <el-table :data="records" class="custom-record-table" stripe>
                    <el-table-column label="物品" min-width="180">
                      <template #default="{ row }">
                        <div class="item-cell">
                          <ItemIcon :name="row.item_name" :game="selectedGame" :rank-type="row.rank_type" size="small" />
                          <span class="item-name">{{ row.item_name }}</span>
                        </div>
                      </template>
                    </el-table-column>
                    <el-table-column label="星级" width="100" align="center">
                      <template #default="{ row }">
                        <div class="rank-tag" :class="'rank-' + row.rank_type">
                          <span>{{ row.rank_type }}</span>
                          <el-icon :size="12"><StarFilled /></el-icon>
                        </div>
                      </template>
                    </el-table-column>
                    <el-table-column prop="item_type" label="类型" width="90" />
                    <el-table-column prop="pool_name" label="卡池" min-width="130" />
                    <el-table-column prop="time_text" label="时间" width="160" />
                  </el-table>
                  <div class="record-footer">
                    <el-pagination
                      background
                      layout="total, sizes, prev, pager, next"
                      v-model:current-page="currentPage"
                      v-model:page-size="pageSize"
                      :page-sizes="[20, 50, 100]"
                      :total="recordTotal"
                      @current-change="handlePageChange"
                      @size-change="handleSizeChange"
                    />
                  </div>
                </div>
              </template>
            </el-skeleton>
          </el-card>
        </div>
      </el-tab-pane>

      <el-tab-pane
        v-for="pool in summary.pool_summaries"
        :key="pool.pool_type"
        :label="pool.pool_name"
        :name="pool.pool_type"
      >
        <div class="pool-detailed-view">
          <div class="pool-top-stats">
            <div class="pity-giant-card">
              <div class="pity-label">当前已垫</div>
              <div class="pity-display">
                <span class="val" :class="getPityColorClass(pool.current_pity)">{{ pool.current_pity }}</span>
                <span class="limit">/ 80</span>
              </div>
              <div class="pity-bar-container">
                <div class="pity-bar-fill" 
                  :style="{ 
                    width: `${Math.min(100, (pool.current_pity / 80) * 100)}%`,
                    backgroundColor: getPityProgressColor(pool.current_pity)
                  }">
                </div>
              </div>
            </div>
            
            <div class="stats-mini-group">
              <div class="mini-stat-item">
                <div class="label">平均出金</div>
                <div class="val">{{ calculateAvgPity(pool) }}</div>
              </div>
              <div class="mini-stat-item">
                <div class="label">五星总数</div>
                <div class="val">{{ pool.five_star_count }}</div>
              </div>
              <div class="mini-stat-item">
                <div class="label">总计抽数</div>
                <div class="val">{{ pool.count }}</div>
              </div>
            </div>
          </div>

          <!-- 五星序列 -->
          <div v-if="pool.five_star_history?.length" class="history-vertical-wrap">
            <div class="history-title-row">
              <el-icon><Histogram /></el-icon>
              <span>五星出金序列时间线</span>
            </div>
            <div class="history-vertical-list">
              <div v-for="(item, idx) in pool.five_star_history" :key="idx" class="history-vertical-item">
                <ItemIcon :name="item.item_name" :game="selectedGame" rank-type="5" circle />
                <div class="item-main">
                  <div class="item-name">{{ item.item_name }}</div>
                  <div class="item-time">{{ item.time_text }}</div>
                </div>
                <div class="item-pity-tag" :class="getPityColorClass(item.pity_count)">
                  {{ item.pity_count }} 抽
                </div>
              </div>
            </div>
          </div>

          <el-card class="pool-detail-record panel-card" shadow="never">
            <template #header>
              <div class="panel-title-row">
                <el-icon><Collection /></el-icon>
                <span>{{ pool.pool_name }} 详细明细</span>
              </div>
            </template>
            <el-skeleton :loading="recordsLoading" animated :rows="6">
              <template #default>
                <div v-if="records.length === 0">
                  <el-empty description="暂无抽卡记录" :image-size="88" />
                </div>
                <div v-else>
                  <el-table :data="records" class="custom-record-table" stripe>
                    <el-table-column label="物品" min-width="180">
                      <template #default="{ row }">
                        <div class="item-cell">
                          <ItemIcon :name="row.item_name" :game="selectedGame" :rank-type="row.rank_type" size="small" />
                          <span class="item-name">{{ row.item_name }}</span>
                        </div>
                      </template>
                    </el-table-column>
                    <el-table-column label="星级" width="100" align="center">
                      <template #default="{ row }">
                        <div class="rank-tag" :class="'rank-' + row.rank_type">
                          <span>{{ row.rank_type }}</span>
                          <el-icon :size="12"><StarFilled /></el-icon>
                        </div>
                      </template>
                    </el-table-column>
                    <el-table-column prop="item_type" label="类型" width="90" />
                    <el-table-column prop="pool_name" label="卡池" min-width="130" />
                    <el-table-column prop="time_text" label="时间" width="160" />
                  </el-table>
                  <div class="record-footer">
                    <el-pagination
                      background
                      layout="total, sizes, prev, pager, next"
                      v-model:current-page="currentPage"
                      v-model:page-size="pageSize"
                      :page-sizes="[20, 50, 100]"
                      :total="recordTotal"
                      @current-change="handlePageChange"
                      @size-change="handleSizeChange"
                    />
                  </div>
                </div>
              </template>
            </el-skeleton>
          </el-card>
        </div>
      </el-tab-pane>
    </el-tabs>

    <!-- 底部数据管理区 (紧凑型导入表单) -->
    <el-card class="data-management-card panel-card" shadow="never">
      <template #header>
        <div class="section-header">
          <div class="section-title">数据同步与备份</div>
        </div>
      </template>

      <div class="data-actions-row">
        <el-input
          v-model="importUrl"
          placeholder="粘贴包含 authkey 的完整链接"
          class="inline-link-input"
          clearable
        >
          <template #append>
            <el-button type="primary" :icon="Upload" :loading="importing" :disabled="!canImport" @click="handleImport">
              导入链接
            </el-button>
          </template>
        </el-input>

        <el-button
          v-if="showImportFromAccount"
          :loading="accountImporting"
          :disabled="!canImportFromAccount"
          @click="handleImportFromAccount"
          type="primary"
          plain
        >
          从账号自动同步
        </el-button>
        <el-button :icon="Refresh" @click="loadPageData" plain>刷新</el-button>
      </div>

      <div class="backup-actions">
        <input
          ref="uigfFileInput"
          type="file"
          accept="application/json,.json"
          class="hidden-file-input"
          @change="handleUigfFileChange"
        />
        <el-button plain :disabled="!canOperateData" :loading="uigfImporting" @click="openUigfFilePicker">导入 UIGF</el-button>
        <el-button plain :disabled="!canOperateData || exporting" :loading="exporting" @click="handleExportUigf">导出 UIGF</el-button>
        <el-button type="danger" plain :disabled="!canOperateData || resetting" :loading="resetting" @click="handleReset">重置数据</el-button>
      </div>
      <div v-if="selectedGame" class="game-scope-hint">
        {{ gameScopeHint }}
      </div>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, useTemplateRef, h } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage, ElMessageBox, ElTable, ElTableColumn, ElTag, ElPagination, ElSkeleton, ElEmpty, ElIcon } from 'element-plus'
import { Refresh, Upload, Histogram, Collection, TrendCharts, StarFilled } from '@element-plus/icons-vue'
import { gachaApi } from '../api'
import { resolveRouteAccountPrefill } from '../utils/accountRoutePrefill'
import { resolveRouteGamePrefill } from '../utils/gameRoutePrefill'
import { formatGachaRoleLabel, resolveRouteGameUidPrefill } from '../utils/gameUidRoutePrefill'
import ItemIcon from '../components/ItemIcon.vue'

// --- Types ---
type GachaRole = { game: string; game_uid: string; nickname?: string | null; region?: string | null }
type GachaAccount = { id: number; nickname?: string; mihoyo_uid?: string; supported_games: string[]; gacha_roles: GachaRole[] }
type GachaPool = {
  pool_type: string
  pool_name: string
  count: number
  five_star_count: number
  four_star_count: number
  current_pity: number
  five_star_history: Array<{ item_name: string; time_text: string; pity_count: number }>
}

// --- State ---
const GAME_OPTIONS: Record<string, { value: string; label: string }> = {
  genshin: { value: 'genshin', label: '原神' },
  starrail: { value: 'starrail', label: '星穹铁道' },
}

const accounts = ref<GachaAccount[]>([])
const selectedAccountId = ref<number | null>(null)
const selectedGame = ref('')
const selectedGameUid = ref('')
const importUrl = ref('')
const importing = ref(false)
const accountImporting = ref(false)
const uigfImporting = ref(false)
const exporting = ref(false)
const resetting = ref(false)
const recordsLoading = ref(false)
const activeTab = ref('overview')
const summary = ref<{
  total_count: number
  five_star_count: number
  four_star_count: number
  latest_five_star_name?: string
  latest_five_star_time?: string
  pool_summaries: GachaPool[]
}>({ total_count: 0, five_star_count: 0, four_star_count: 0, pool_summaries: [] })

const records = ref<any[]>([])
const recordTotal = ref(0)
const currentPage = ref(1)
const pageSize = ref(20)
const latestImportMessage = ref('尚未执行导入')
const uigfFileInput = useTemplateRef<HTMLInputElement>('uigfFileInput')
const route = useRoute()

// --- Computed ---
const currentAccount = computed(() => accounts.value.find(a => a.id === selectedAccountId.value) || null)
const availableGames = computed(() => currentAccount.value?.supported_games.map(g => GAME_OPTIONS[g]).filter(Boolean) || [])
const availableRoles = computed(() => {
  if (!currentAccount.value || !selectedGame.value) return []
  const roleMap = new Map<string, GachaRole>()
  currentAccount.value.gacha_roles.forEach(role => {
    if (role.game === selectedGame.value && role.game_uid) roleMap.set(role.game_uid, role)
  })
  return Array.from(roleMap.values())
})
const currentRole = computed(() => availableRoles.value.find(r => r.game_uid === selectedGameUid.value) || null)
const showImportFromAccount = computed(() => selectedGame.value === 'genshin')
const isImportBusy = computed(() => importing.value || accountImporting.value || uigfImporting.value)
const canImportFromAccount = computed(() => !!(selectedAccountId.value && showImportFromAccount.value && selectedGameUid.value && !isImportBusy.value))
const canImport = computed(() => !!(selectedAccountId.value && selectedGame.value && selectedGameUid.value && importUrl.value.trim() && !isImportBusy.value))
const canOperateData = computed(() => !!(selectedAccountId.value && selectedGame.value && selectedGameUid.value && !isImportBusy.value))

const importSectionDescription = computed(() => showImportFromAccount.value 
  ? '原神可直接从账号自动导入，也支持手贴链接或导入 UIGF 备份。' 
  : '当前游戏支持手贴链接导入，以及导入或导出 UIGF 备份。')
const gameScopeHint = computed(() => currentRole.value 
  ? `当前角色：${formatRoleLabel(currentRole.value)}。` 
  : '当前游戏下还没有可用角色 UID。')

// --- Helper Functions ---
function formatAccountLabel(account: GachaAccount) {
  return account.nickname ? `${account.nickname}${account.mihoyo_uid ? ` (${account.mihoyo_uid})` : ''}` : `账号 ${account.id}`
}
function formatRoleLabel(role: GachaRole) { return formatGachaRoleLabel(role) }
function getPoolRatio(count: number) { return summary.value.total_count ? Math.max(8, Math.round((count / summary.value.total_count) * 100)) : 0 }

function getPityColorClass(pity: number) {
  if (pity >= 74) return 'is-hard'
  if (pity <= 50) return 'is-lucky'
  return 'is-normal'
}
function getPityProgressColor(pity: number) {
  if (pity >= 74) return 'var(--color-danger)' // Danger
  if (pity >= 60) return 'var(--color-warning)' // Warning
  return 'var(--brand-primary)' // Primary
}
function calculateAvgPity(pool: GachaPool) {
  if (pool.five_star_count === 0) return '-'
  // Simple avg: total in pool / five stars
  return (pool.count / pool.five_star_count).toFixed(1)
}

// --- Data Loading ---
async function loadSummary() {
  if (!selectedAccountId.value || !selectedGame.value || !selectedGameUid.value) return
  const { data } = await gachaApi.getSummary({ account_id: selectedAccountId.value, game: selectedGame.value, game_uid: selectedGameUid.value })
  summary.value = data
}

async function loadRecords() {
  if (!selectedAccountId.value || !selectedGame.value || !selectedGameUid.value) {
    records.value = []
    recordTotal.value = 0
    return
  }
  recordsLoading.value = true
  try {
    const { data } = await gachaApi.listRecords({
      account_id: selectedAccountId.value,
      game: selectedGame.value,
      game_uid: selectedGameUid.value,
      pool_type: activeTab.value === 'overview' ? undefined : activeTab.value,
      page: currentPage.value,
      page_size: pageSize.value
    })
    records.value = data.records || []
    recordTotal.value = data.total || 0
  } finally {
    recordsLoading.value = false
  }
}

function handleSizeChange(val: number) {
  pageSize.value = val
  currentPage.value = 1
  loadRecords()
}

async function loadPageData() {
  const { data } = await gachaApi.getAccounts()
  accounts.value = data.accounts || []
  if (accounts.value.length && !selectedAccountId.value) {
    selectedAccountId.value = accounts.value[0].id
    handleAccountChange()
  } else {
    await Promise.all([loadSummary(), loadRecords()])
  }
}

// --- Event Handlers ---
function handleAccountChange() {
  const games = currentAccount.value?.supported_games || []
  if (!games.includes(selectedGame.value)) selectedGame.value = games[0] || ''
  handleGameChange()
}
function handleGameChange() {
  const roles = availableRoles.value
  if (!roles.find(r => r.game_uid === selectedGameUid.value)) selectedGameUid.value = roles[0]?.game_uid || ''
  handleRoleChange()
}
async function handleRoleChange() {
  currentPage.value = 1
  activeTab.value = 'overview'
  await Promise.all([loadSummary(), loadRecords()])
}
async function handleTabChange() {
  currentPage.value = 1
  await loadRecords()
}
function handlePageChange(page: number) {
  currentPage.value = page
  loadRecords()
}

async function handleImport() {
  if (!canImport.value) return
  importing.value = true
  try {
    const { data } = await gachaApi.import({ account_id: selectedAccountId.value!, game: selectedGame.value, game_uid: selectedGameUid.value, import_url: importUrl.value.trim() })
    importUrl.value = ''
    latestImportMessage.value = `链接导入新增 ${data.inserted_count} 条，跳过重复 ${data.duplicate_count} 条`
    ElMessage.success('导入完成')
    await Promise.all([loadSummary(), loadRecords()])
  } finally { importing.value = false }
}

async function handleImportFromAccount() {
  if (!canImportFromAccount.value) return
  accountImporting.value = true
  try {
    const { data } = await gachaApi.importFromAccount({ account_id: selectedAccountId.value!, game: selectedGame.value, game_uid: selectedGameUid.value })
    latestImportMessage.value = `账号自动导入新增 ${data.inserted_count} 条，跳过重复 ${data.duplicate_count} 条`
    ElMessage.success('导入完成')
    await Promise.all([loadSummary(), loadRecords()])
  } finally { accountImporting.value = false }
}

function openUigfFilePicker() { uigfFileInput.value?.click() }
async function handleUigfFileChange(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  if (!file || !selectedAccountId.value || !selectedGame.value || !selectedGameUid.value) { input.value = ''; return }
  uigfImporting.value = true
  try {
    const text = await file.text()
    const { data } = await gachaApi.importUigf({ account_id: selectedAccountId.value, game: selectedGame.value, game_uid: selectedGameUid.value, source_name: file.name, uigf_json: text })
    latestImportMessage.value = `UIGF 导入新增 ${data.inserted_count} 条，跳过重复 ${data.duplicate_count} 条`
    ElMessage.success('UIGF 导入完成')
    await Promise.all([loadSummary(), loadRecords()])
  } catch (e: any) { ElMessage.error('解析文件失败') } finally { input.value = ''; uigfImporting.value = false }
}

async function handleExportUigf() {
  if (!selectedAccountId.value || !selectedGame.value || !selectedGameUid.value) return
  exporting.value = true
  try {
    const { data } = await gachaApi.exportUigf({ account_id: selectedAccountId.value, game: selectedGame.value, game_uid: selectedGameUid.value })
    const blob = new Blob([JSON.stringify(data.uigf, null, 2)], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `uigf-${selectedGame.value}-${selectedGameUid.value}.json`
    a.click()
    URL.revokeObjectURL(url)
    ElMessage.success(`已导出 ${data.total} 条记录`)
  } finally { exporting.value = false }
}

async function handleReset() {
  if (!selectedAccountId.value || !selectedGame.value || !selectedGameUid.value) return
  try {
    await ElMessageBox.confirm('确定要重置当前角色的抽卡记录吗？此操作不可撤销。', '警告', { type: 'warning', confirmButtonClass: 'el-button--danger' })
    resetting.value = true
    await gachaApi.reset({ account_id: selectedAccountId.value, game: selectedGame.value, game_uid: selectedGameUid.value })
    latestImportMessage.value = '抽卡记录已清空'
    ElMessage.success('已重置')
    await Promise.all([loadSummary(), loadRecords()])
  } catch { } finally { resetting.value = false }
}

onMounted(loadPageData)
</script>

<style scoped>
.gacha-page { width: 100%; display: flex; flex-direction: column; gap: 16px; }

/* 筛选器 */
.global-filters { display: flex; gap: 12px; align-items: center; flex-wrap: wrap; margin-bottom: 4px; }
.filter-item { width: 220px; }

/* 顶部高级统计卡片 */
.stats-premium-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 16px; margin-bottom: 12px; }
.stat-premium-card {
  padding: 16px 20px; border-radius: 16px; 
  background: var(--bg-elevated); border: 1px solid var(--border-soft);
  box-shadow: var(--shadow-soft); transition: transform 0.3s;
}
.stat-premium-card:hover { transform: translateY(-2px); }
.card-inner { display: flex; align-items: center; gap: 16px; overflow: hidden; }
.card-icon { font-size: 24px; opacity: 0.8; flex-shrink: 0; }
.stat-body { flex: 1; min-width: 0; }
.stat-body .label { font-size: 12px; color: var(--text-tertiary); margin-bottom: 4px; }
.stat-body .value { font-size: 24px; font-weight: 800; font-family: var(--font-mono); }
.stat-body .value.compact { font-size: 18px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }

.stat-premium-card.rank-5 .card-icon, .stat-premium-card.rank-5 .value { color: #f3d144; }
.stat-premium-card.rank-4 .card-icon, .stat-premium-card.rank-4 .value { color: #af89f5; }
.stat-premium-card.highlight { background: linear-gradient(135deg, rgba(37,99,235,0.05), transparent), var(--bg-elevated); border-color: rgba(37,99,235,0.2); }

/* 内容分栏 */
.main-content-split { display: grid; grid-template-columns: 320px 1fr; gap: 16px; align-items: start; }
.panel-title-row { display: flex; align-items: center; gap: 8px; font-weight: 700; font-size: 15px; }

.pool-vertical-list { display: flex; flex-direction: column; gap: 16px; }
.pool-row .row-top { display: flex; justify-content: space-between; margin-bottom: 8px; font-size: 13px; }
.pool-row .name { font-weight: 600; }
.pool-row .count { color: var(--text-secondary); }
.bar-track { height: 6px; background: var(--bg-soft); border-radius: 3px; overflow: hidden; }
.bar-fill { height: 100%; background: var(--brand-primary); border-radius: 3px; }

/* 详情视图 */
.pool-detailed-view { display: flex; flex-direction: column; gap: 20px; padding-top: 8px; }
.pool-top-stats { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }

.pity-giant-card {
  padding: 24px; border-radius: 20px; background: var(--bg-elevated);
  border: 1px solid var(--border-soft); text-align: center;
}
.pity-label { font-size: 13px; color: var(--text-tertiary); margin-bottom: 12px; }
.pity-display { display: flex; align-items: baseline; justify-content: center; gap: 4px; margin-bottom: 16px; }
.pity-display .val { font-size: 56px; font-weight: 900; line-height: 1; }
.pity-display .limit { font-size: 16px; color: var(--text-tertiary); font-weight: 700; }
.pity-bar-container { height: 8px; background: var(--bg-soft); border-radius: 4px; overflow: hidden; }
.pity-bar-fill { height: 100%; transition: width 0.6s ease-out; }

.stats-mini-group { display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; }
.mini-stat-item {
  padding: 16px; border-radius: 16px; background: var(--bg-soft);
  text-align: center; display: flex; flex-direction: column; justify-content: center;
}
.mini-stat-item .label { font-size: 11px; color: var(--text-tertiary); margin-bottom: 6px; }
.mini-stat-item .val { font-size: 20px; font-weight: 800; }

/* 垂直历史列表 */
.history-vertical-wrap { background: var(--bg-elevated); padding: 20px; border-radius: 20px; border: 1px solid var(--border-soft); }
.history-title-row { display: flex; align-items: center; gap: 8px; font-size: 14px; font-weight: 700; margin-bottom: 16px; }
.history-vertical-list { display: flex; flex-direction: column; gap: 10px; }
.history-vertical-item {
  display: flex; align-items: center; gap: 12px; padding: 10px;
  background: var(--bg-soft); border-radius: 12px;
}
.history-vertical-item .item-main { flex: 1; }
.history-vertical-item .item-name { font-size: 14px; font-weight: 700; }
.history-vertical-item .item-time { font-size: 11px; color: var(--text-tertiary); margin-top: 2px; }
.item-pity-tag { font-size: 12px; font-weight: 800; padding: 2px 8px; border-radius: 6px; }

/* 表格定制 */
.custom-record-table { border-radius: 12px; overflow: hidden; margin-top: 8px; }
.item-cell { display: flex; align-items: center; gap: 12px; }
.item-name { font-weight: 600; font-size: 14px; }
.rank-tag { display: flex; align-items: center; gap: 2px; font-weight: 800; font-size: 13px; padding: 2px 8px; border-radius: 6px; width: fit-content; }
.rank-5 { color: #f3d144; background: rgba(243,209,68,0.1); }
.rank-4 { color: #af89f5; background: rgba(175,137,245,0.1); }

.is-hard { color: #f56c6c !important; }
.is-lucky { color: #67c23a !important; }
.is-normal { color: var(--brand-primary) !important; }
.history-vertical-item .item-pity-tag.is-hard { background: rgba(245,108,108,0.15); }
.history-vertical-item .item-pity-tag.is-lucky { background: rgba(103,194,58,0.15); }
.history-vertical-item .item-pity-tag.is-normal { background: rgba(37,99,235,0.1); }

/* 底部同步卡片 */
.data-management-card { margin-top: 12px; }
.data-actions-row { display: flex; gap: 12px; align-items: stretch; flex-wrap: wrap; margin-bottom: 20px; }
.inline-link-input { flex: 1; min-width: 300px; }
.backup-actions { display: flex; flex-wrap: wrap; gap: 12px; align-items: center; }

:deep(.record-footer) { 
  margin-top: 24px; 
  display: flex !important; 
  justify-content: flex-end !important; 
  align-items: center !important; 
  width: 100% !important;
}

:deep(.el-pagination.is-background .el-pager li:not(.is-active)) {
  background-color: var(--bg-soft);
  color: var(--text-secondary);
  border-radius: 8px;
}
:deep(.el-pagination.is-background .el-pager li.is-active) {
  background: var(--brand-primary);
  color: #fff;
  border-radius: 8px;
  box-shadow: 0 4px 12px rgba(37,99,235,0.2);
}
:deep(.el-pagination.is-background .btn-prev), 
:deep(.el-pagination.is-background .btn-next) {
  background-color: var(--bg-soft);
  border-radius: 8px;
}

/* 核心修复：隐藏原生文件输入 */
.hidden-file-input { 
  display: none !important; 
  visibility: hidden !important; 
  position: absolute !important; 
  width: 0 !important; 
  height: 0 !important; 
  opacity: 0 !important;
  pointer-events: none !important;
}

.game-scope-hint { margin-top: 16px; font-size: 12px; color: var(--text-tertiary); }

@media (max-width: 1024px) {
  .stats-premium-grid { grid-template-columns: repeat(2, 1fr); }
  .main-content-split { grid-template-columns: 1fr; }
  .pool-top-stats { grid-template-columns: 1fr; }
}
@media (max-width: 640px) {
  .stats-premium-grid { grid-template-columns: 1fr; }
}
</style>
