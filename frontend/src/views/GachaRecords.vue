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
        <div class="stats-grid">
          <div class="stat-card stat-card-primary">
            <div class="stat-label">累计抽数</div>
            <div class="stat-value">{{ summary.total_count || 0 }}</div>
            <div class="stat-note">保存的总抽数</div>
          </div>
          <div class="stat-card">
            <div class="stat-label">五星次数</div>
            <div class="stat-value">{{ summary.five_star_count || 0 }}</div>
            <div class="stat-note">累计出金总数</div>
          </div>
          <div class="stat-card">
            <div class="stat-label">四星次数</div>
            <div class="stat-value">{{ summary.four_star_count || 0 }}</div>
            <div class="stat-note">累计紫光总数</div>
          </div>
          <div class="stat-card">
            <div class="stat-label">最近五星</div>
            <div class="stat-value stat-value-compact">{{ summary.latest_five_star_name || '暂无' }}</div>
            <div class="stat-note">{{ summary.latest_five_star_time || '导入后显示' }}</div>
          </div>
        </div>

        <div class="content-grid">
          <el-card class="pool-card panel-card" shadow="never">
            <template #header>
              <div class="section-title">卡池分布</div>
            </template>
            <div v-if="summary.pool_summaries?.length" class="pool-list">
              <div v-for="pool in summary.pool_summaries" :key="pool.pool_type" class="pool-item">
                <div class="pool-head">
                  <span class="pool-name">{{ pool.pool_name }}</span>
                  <span class="pool-count">{{ pool.count }} 抽</span>
                </div>
                <div class="pool-bar">
                  <span class="pool-bar-fill" :style="{ width: `${getPoolRatio(pool.count)}%` }" />
                </div>
              </div>
            </div>
            <el-empty v-else description="暂无统计数据" :image-size="72" />
          </el-card>

          <el-card class="record-card panel-card" shadow="never">
            <template #header>
              <div class="section-title">全部记录</div>
            </template>
            <GachaTable :records="records" :loading="recordsLoading" :total="recordTotal" :page="currentPage" @page-change="handlePageChange" />
          </el-card>
        </div>
      </el-tab-pane>

      <!-- 各个卡池 Tab -->
      <el-tab-pane
        v-for="pool in summary.pool_summaries"
        :key="pool.pool_type"
        :label="pool.pool_name"
        :name="pool.pool_type"
      >
        <div class="pool-detail-layout">
          <div class="pool-stats-row">
            <div class="pool-metric-card">
              <div class="metric-label">已垫抽数</div>
              <div class="pity-value-group">
                <span class="pity-number" :class="getPityColorClass(pool.current_pity)">{{ pool.current_pity }}</span>
                <span class="pity-total">/ 90</span>
              </div>
              <el-progress
                :percentage="Math.min(100, (pool.current_pity / 80) * 100)"
                :stroke-width="10"
                :show-text="false"
                :color="getPityProgressColor(pool.current_pity)"
                class="pity-progress"
              />
              <div class="metric-note">距离下次保底（参考值）</div>
            </div>

            <div class="pool-metric-card">
              <div class="metric-label">平均出金</div>
              <div class="metric-value">{{ calculateAvgPity(pool) }}</div>
              <div class="metric-note">每 {{ pool.five_star_count > 0 ? '个五星消耗' : '池内总共' }}</div>
            </div>

            <div class="pool-metric-card">
              <div class="metric-label">五星数量</div>
              <div class="metric-value">{{ pool.five_star_count }}</div>
              <div class="metric-note">占总抽数 {{ ((pool.five_star_count / pool.count) * 100).toFixed(2) }}%</div>
            </div>

            <div class="pool-metric-card">
              <div class="metric-label">总计抽数</div>
              <div class="metric-value">{{ pool.count }}</div>
              <div class="metric-note">池内累计投入</div>
            </div>
          </div>

          <div v-if="pool.five_star_history?.length" class="history-section">
            <div class="section-title">出金历史</div>
            <div class="five-star-timeline">
              <div v-for="(item, idx) in pool.five_star_history" :key="idx" class="history-item">
                <div class="history-pity" :class="getPityColorClass(item.pity_count)">
                  {{ item.pity_count }}
                </div>
                <div class="history-main">
                  <div class="history-name">{{ item.item_name }}</div>
                  <div class="history-time">{{ item.time_text }}</div>
                </div>
              </div>
            </div>
          </div>

          <el-card class="record-card panel-card" shadow="never">
            <template #header>
              <div class="section-title">{{ pool.pool_name }} 明细</div>
            </template>
            <GachaTable :records="records" :loading="recordsLoading" :total="recordTotal" :page="currentPage" @page-change="handlePageChange" />
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
import { ElMessage, ElMessageBox, ElTable, ElTableColumn, ElTag, ElPagination, ElSkeleton, ElEmpty } from 'element-plus'
import { Refresh, Upload } from '@element-plus/icons-vue'
import { gachaApi } from '../api'
import { resolveRouteAccountPrefill } from '../utils/accountRoutePrefill'
import { resolveRouteGamePrefill } from '../utils/gameRoutePrefill'
import { formatGachaRoleLabel, resolveRouteGameUidPrefill } from '../utils/gameUidRoutePrefill'

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

// --- Inner Component: GachaTable ---
// Using a functional component style for the table to avoid separate file
const GachaTable = (props: { records: any[], loading: boolean, total: number, page: number }, { emit }: any) => {
  return h('div', [
    h(ElSkeleton, { loading: props.loading, animated: true, rows: 6 }, {
      default: () => props.records.length === 0 
        ? h(ElEmpty, { description: '暂无抽卡记录', imageSize: 88 })
        : [
            h(ElTable, { data: props.records, class: 'record-table', stripe: true }, {
              default: () => [
                h(ElTableColumn, { prop: 'time_text', label: '抽取时间', minWidth: '168' }),
                h(ElTableColumn, { prop: 'pool_name', label: '卡池', minWidth: '132' }),
                h(ElTableColumn, { prop: 'item_name', label: '物品', minWidth: '160' }),
                h(ElTableColumn, { prop: 'item_type', label: '类型', width: '96' }),
                h(ElTableColumn, { label: '星级', width: '108' }, {
                  default: ({ row }: any) => h(ElTag, { 
                    type: row.rank_type === '5' ? 'danger' : row.rank_type === '4' ? 'warning' : 'info',
                    effect: 'dark', round: true 
                  }, () => `${row.rank_type} 星`)
                })
              ]
            }),
            h('div', { class: 'record-footer' }, [
              h('div', { class: 'record-total' }, `共 ${props.total} 条记录`),
              h(ElPagination, {
                background: true,
                layout: 'prev, pager, next',
                currentPage: props.page,
                pageSize: 20,
                total: props.total,
                onCurrentChange: (val: number) => emit('page-change', val)
              })
            ])
          ]
    })
  ])
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
  if (pity >= 74) return '#f56c6c' // Danger
  if (pity >= 60) return '#e6a23c' // Warning
  return '#409eff' // Primary
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
      page_size: 20
    })
    records.value = data.records || []
    recordTotal.value = data.total || 0
  } finally {
    recordsLoading.value = false
  }
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
.gacha-page { width: 100%; display: flex; flex-direction: column; gap: 20px; }
.section-header { display: flex; align-items: center; justify-content: space-between; gap: 16px; }
.section-title { font-size: 16px; font-weight: 700; color: var(--text-primary); }
.section-desc { margin-top: 4px; font-size: 13px; color: var(--text-secondary); }

.global-filters { display: flex; gap: 16px; align-items: center; flex-wrap: wrap; margin-bottom: 10px; }
.filter-item { width: 220px; }

.data-management-card { margin-top: 20px; }
.data-actions-row { display: flex; gap: 12px; align-items: stretch; flex-wrap: wrap; margin-bottom: 16px; }
.inline-link-input { flex: 1; min-width: 300px; }
.inline-link-input :deep(.el-input-group__append) { background-color: var(--el-color-primary); color: white; border-color: var(--el-color-primary); }
.inline-link-input :deep(.el-input-group__append:hover) { opacity: 0.9; }
.inline-link-input :deep(.el-button) { margin: -10px -20px; padding: 10px 20px; border-radius: 0; color: white; }

.backup-actions { display: flex; flex-wrap: wrap; gap: 12px; margin-top: 16px; }
.hidden-file-input { display: none; }
.game-scope-hint { margin-top: 12px; font-size: 12px; line-height: 1.7; color: var(--text-secondary); }

.gacha-tabs { margin-top: 0; }
.gacha-tabs :deep(.el-tabs__item) { font-size: 15px; padding: 0 24px; height: 50px; }

.stats-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 16px; margin-bottom: 20px; }
.stat-card {
  padding: 20px; border-radius: var(--radius-md); border: 1px solid var(--border-soft);
  background: var(--bg-elevated); backdrop-filter: blur(10px);
}
.stat-card-primary { background: radial-gradient(circle at top right, rgba(99, 102, 241, 0.1), transparent 40%), var(--bg-elevated); border-color: rgba(99, 102, 241, 0.2); }
.stat-label { font-size: 13px; color: var(--text-secondary); }
.stat-value { margin-top: 8px; font-size: 28px; font-weight: 800; color: var(--text-primary); }
.stat-value-compact { font-size: 20px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.stat-note { margin-top: 8px; font-size: 12px; color: var(--text-tertiary); }

.content-grid { display: grid; grid-template-columns: 300px 1fr; gap: 20px; align-items: start; }
.pool-list { display: flex; flex-direction: column; gap: 12px; }
.pool-item { padding: 12px; border-radius: 12px; background: var(--bg-surface-muted); }
.pool-head { display: flex; justify-content: space-between; margin-bottom: 8px; }
.pool-name { font-size: 13px; font-weight: 600; }
.pool-count { font-size: 12px; color: var(--text-secondary); }
.pool-bar { height: 6px; background: var(--border-soft); border-radius: 3px; overflow: hidden; }
.pool-bar-fill { display: block; height: 100%; background: var(--bg-primary); border-radius: 3px; }

.pool-detail-layout { display: flex; flex-direction: column; gap: 24px; padding-top: 10px; }
.pool-stats-row { display: grid; grid-template-columns: repeat(4, 1fr); gap: 16px; }
.pool-metric-card {
  padding: 20px; border-radius: 16px; background: var(--bg-soft); border: 1px solid var(--border-soft);
  display: flex; flex-direction: column; align-items: center; text-align: center;
}
.pity-value-group { margin: 12px 0; }
.pity-number { font-size: 36px; font-weight: 900; }
.pity-number.is-hard { color: var(--danger-color); }
.pity-number.is-lucky { color: var(--success-color); }
.pity-number.is-normal { color: var(--brand-primary); }
.pity-total { font-size: 16px; color: var(--text-tertiary); margin-left: 4px; }
.pity-progress { width: 100%; margin-bottom: 12px; }
.metric-label { font-size: 13px; font-weight: 600; color: var(--text-secondary); }
.metric-value { font-size: 28px; font-weight: 800; margin: 12px 0; }
.metric-note { font-size: 12px; color: var(--text-tertiary); }

.history-section { margin-bottom: 10px; }
.five-star-timeline {
  display: flex; flex-wrap: wrap; gap: 12px; margin-top: 16px;
}
.history-item {
  display: flex; align-items: center; gap: 12px; padding: 12px 16px;
  background: var(--bg-elevated); border: 1px solid var(--border-soft); border-radius: 12px;
  min-width: 200px;
}
.history-pity {
  width: 40px; height: 40px; border-radius: 50%; display: flex; align-items: center; justify-content: center;
  font-weight: 800; font-size: 16px; color: #fff;
}
.history-pity.is-hard { background: var(--danger-color); }
.history-pity.is-lucky { background: var(--success-color); }
.history-pity.is-normal { background: var(--brand-primary); }
.history-name { font-size: 14px; font-weight: 700; color: var(--text-primary); }
.history-time { font-size: 11px; color: var(--text-tertiary); margin-top: 2px; }

.record-footer { margin-top: 20px; display: flex; justify-content: space-between; align-items: center; }
.record-total { font-size: 13px; color: var(--text-secondary); }

@media (max-width: 1200px) {
  .global-filters { flex-direction: column; align-items: stretch; }
  .filter-item { width: 100%; }
  .stats-grid, .pool-stats-row { grid-template-columns: repeat(2, 1fr); }
  .content-grid { grid-template-columns: 1fr; }
}
@media (max-width: 768px) {
  .stats-grid, .pool-stats-row { grid-template-columns: 1fr; }
  .data-actions-row { flex-direction: column; }
}
</style>
