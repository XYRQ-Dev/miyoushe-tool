<template>
  <div class="app-page gacha-page">
    <section class="page-toolbar">
      <div class="page-title-group">
        <div class="page-kicker">Asset Archive</div>
        <h2 class="page-title">抽卡记录中心</h2>
        <p class="page-desc">选择账号、游戏和角色 UID 后，可手贴完整抽卡链接；原神还支持从账号自动导入，也可导入或导出 UIGF 备份。</p>
      </div>
      <div class="page-actions">
        <div class="soft-chip">{{ latestImportMessage }}</div>
      </div>
    </section>

    <el-card class="import-card panel-card" shadow="never">
      <template #header>
        <div class="section-header">
          <div>
            <div class="section-title">导入抽卡记录</div>
            <div class="section-desc">{{ importSectionDescription }}</div>
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

          <el-form-item label="角色 UID" class="field-block">
            <el-select
              v-model="selectedGameUid"
              placeholder="请选择角色 UID"
              :disabled="availableRoles.length === 0"
              @change="handleRoleChange"
            >
              <el-option
                v-for="role in availableRoles"
                :key="role.game_uid"
                :label="formatRoleLabel(role)"
                :value="role.game_uid"
              />
            </el-select>
            <div v-if="currentRole?.region" class="field-hint">
              当前角色所在区服：{{ currentRole.region }}
            </div>
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
            开始导入链接
          </el-button>
          <el-button
            v-if="showImportFromAccount"
            :loading="accountImporting"
            :disabled="!canImportFromAccount"
            @click="handleImportFromAccount"
          >
            从账号自动导入
          </el-button>
          <el-button :icon="Refresh" @click="loadPageData">刷新数据</el-button>
        </div>

        <div v-if="selectedGame" class="game-scope-hint">
          {{ gameScopeHint }}
        </div>

        <div class="backup-actions">
          <input
            ref="uigfFileInput"
            type="file"
            accept="application/json,.json"
            class="hidden-file-input"
            @change="handleUigfFileChange"
          />
          <el-button
            plain
            :disabled="!selectedAccountId || !selectedGame || !selectedGameUid || isImportBusy"
            :loading="uigfImporting"
            @click="openUigfFilePicker"
          >
            导入 UIGF
          </el-button>
          <el-button
            plain
            :disabled="!selectedAccountId || !selectedGame || !selectedGameUid || exporting"
            :loading="exporting"
            @click="handleExportUigf"
          >
            导出 UIGF
          </el-button>
          <el-button
            type="danger"
            plain
            :disabled="!selectedAccountId || !selectedGame || !selectedGameUid || resetting"
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
        <div class="stat-note">当前账号在所选游戏下已保存的总抽数</div>
      </div>

      <div class="stat-card">
        <div class="stat-label">五星次数</div>
        <div class="stat-value">{{ summary.five_star_count || 0 }}</div>
        <div class="stat-note">用于快速感知高价值出货数量</div>
      </div>

      <div class="stat-card">
        <div class="stat-label">四星次数</div>
        <div class="stat-value">{{ summary.four_star_count || 0 }}</div>
        <div class="stat-note">显示已记录的四星次数</div>
      </div>

      <div class="stat-card">
        <div class="stat-label">最近五星</div>
        <div class="stat-value stat-value-compact">{{ summary.latest_five_star_name || '暂无' }}</div>
        <div class="stat-note">{{ summary.latest_five_star_time || '导入后会显示最近出货时间' }}</div>
      </div>
    </div>

    <div class="content-grid">
      <el-card class="pool-card panel-card" shadow="never">
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

      <el-card class="record-card panel-card" shadow="never">
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
              :description="emptyRecordsDescription"
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
import { formatGachaRoleLabel, resolveRouteGameUidPrefill } from '../utils/gameUidRoutePrefill'

type GameOption = { value: string; label: string }
type GachaRole = {
  game: string
  game_uid: string
  nickname?: string | null
  region?: string | null
}

type GachaAccount = {
  id: number
  nickname?: string
  mihoyo_uid?: string
  supported_games: string[]
  gacha_roles: GachaRole[]
}

const GAME_OPTIONS: Record<string, GameOption> = {
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
const summary = ref<any>({ pool_summaries: [] })
const records = ref<any[]>([])
const recordTotal = ref(0)
const currentPage = ref(1)
const pageSize = 20
const poolFilter = ref<string | undefined>()
const latestImportMessage = ref('尚未执行导入')
const uigfFileInput = useTemplateRef<HTMLInputElement>('uigfFileInput')
const route = useRoute()
const routeAccountPrefillConsumed = ref(false)
const routeGamePrefillConsumed = ref(false)
const routeGameUidPrefillConsumed = ref(false)

const currentAccount = computed(() => (
  accounts.value.find((account) => account.id === selectedAccountId.value) || null
))

const availableGames = computed(() => {
  if (!currentAccount.value) return []
  return currentAccount.value.supported_games
    .map((game) => GAME_OPTIONS[game])
    .filter(Boolean)
})

const availableRoles = computed(() => {
  if (!currentAccount.value || !selectedGame.value) return []

  const roleMap = new Map<string, GachaRole>()
  currentAccount.value.gacha_roles.forEach((role) => {
    const normalizedGameUid = String(role.game_uid || '').trim()
    if (!normalizedGameUid || role.game !== selectedGame.value || roleMap.has(normalizedGameUid)) {
      return
    }
    roleMap.set(normalizedGameUid, {
      ...role,
      game_uid: normalizedGameUid,
    })
  })
  return Array.from(roleMap.values())
})

const currentRole = computed(() => (
  availableRoles.value.find((role) => role.game_uid === selectedGameUid.value) || null
))

// 当前后端只支持原神通过账号根凭据生成 authkey 自动导入。
// 星铁仍然只有“手贴链接 / UIGF 文件交换”两种入口；如果前端把按钮也放出来，
// 用户会误以为后端已经支持星铁账号直连导入，排障时会被错误入口带偏。
const showImportFromAccount = computed(() => selectedGame.value === 'genshin')
const isImportBusy = computed(() => importing.value || accountImporting.value || uigfImporting.value)
const canImportFromAccount = computed(() => Boolean(
  selectedAccountId.value &&
  showImportFromAccount.value &&
  selectedGameUid.value &&
  !isImportBusy.value
))
const importSectionDescription = computed(() => (
  showImportFromAccount.value
    ? '原神可直接从账号自动导入，也支持手贴完整链接或导入 UIGF 备份。所有操作都会绑定到当前 UID。'
    : '当前游戏支持手贴完整链接导入，以及导入或导出 UIGF 备份。所有操作都会绑定到当前 UID。'
))
const gameScopeHint = computed(() => (
  currentRole.value
    ? `${showImportFromAccount.value ? '原神支持三种入口：手贴链接、从账号自动导入、导入 UIGF。' : '星穹铁道当前只提供手贴链接导入、导入 UIGF、导出 UIGF。'} 当前角色：${formatRoleLabel(currentRole.value)}。`
    : '当前账号游戏下还没有可用角色 UID，暂时无法请求抽卡数据。'
))
const emptyRecordsDescription = computed(() => (
  !selectedGameUid.value
    ? '请先选择角色 UID，再查看该角色的抽卡记录'
    :
  showImportFromAccount.value
    ? '暂无抽卡记录，先在上方导入完整链接、账号数据或 UIGF 备份'
    : '暂无抽卡记录，先在上方导入完整链接或 UIGF 备份'
))

const canImport = computed(() => Boolean(
  selectedAccountId.value && selectedGame.value && selectedGameUid.value && importUrl.value.trim() && !isImportBusy.value
))

function formatAccountLabel(account: GachaAccount) {
  return account.nickname
    ? `${account.nickname}${account.mihoyo_uid ? ` (${account.mihoyo_uid})` : ''}`
    : account.mihoyo_uid || `账号 ${account.id}`
}

function formatRoleLabel(role: GachaRole) {
  return formatGachaRoleLabel(role)
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

function applyPreferredGameSelection() {
  const account = currentAccount.value
  if (!account) {
    selectedGame.value = ''
    return
  }

  const prefilledGame = resolveRouteGamePrefill(route.query.game, {
    consumed: routeGamePrefillConsumed.value,
    availableGames: account.supported_games || [],
  })
  routeGamePrefillConsumed.value = prefilledGame.consumed

  if (prefilledGame.preferredGame !== null) {
    // 角色资产页会同时带上账号和游戏上下文，抽卡页应优先落到该账号的对应游戏档案。
    selectedGame.value = prefilledGame.preferredGame
  } else if (!selectedGame.value || !account.supported_games.includes(selectedGame.value)) {
    selectedGame.value = account.supported_games[0] || ''
  }
}

function applyPreferredRoleSelection() {
  const availableGameUids = availableRoles.value.map((role) => role.game_uid)
  const prefilledRole = resolveRouteGameUidPrefill(route.query.game_uid, {
    consumed: routeGameUidPrefillConsumed.value,
    availableGameUids,
  })
  routeGameUidPrefillConsumed.value = prefilledRole.consumed

  if (prefilledRole.preferredGameUid !== null) {
    // query 中显式带入了 game_uid 时，抽卡页要优先消费这份上下文，
    // 这样从角色资产页进入后才能直接落到目标角色，而不是落到同账号同游戏下的其他 UID。
    selectedGameUid.value = prefilledRole.preferredGameUid
    return
  }

  if (!availableGameUids.includes(selectedGameUid.value)) {
    // 如果 query 中的 game_uid 不属于当前账号游戏角色，或账号 / 游戏切换后旧 UID 已失效，
    // 必须回退到当前账号游戏下的第一个合法 UID。
    // 这里不能继续保留失效 UID，更不能把请求偷偷放大成“按账号 + 游戏聚合”，
    // 否则 summary / records / export / reset / import 都可能落到错误角色，排障时还很难看出真正的错位来源。
    selectedGameUid.value = availableGameUids[0] || ''
  }
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

  applyPreferredGameSelection()
  applyPreferredRoleSelection()
}

async function loadSummary() {
  if (!selectedAccountId.value || !selectedGame.value || !selectedGameUid.value) {
    summary.value = { pool_summaries: [] }
    return
  }
  const { data } = await gachaApi.getSummary({
    account_id: selectedAccountId.value,
    game: selectedGame.value,
    game_uid: selectedGameUid.value,
  })
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

async function loadScopedData() {
  await Promise.all([loadSummary(), loadRecords()])
}

async function loadPageData() {
  await loadAccounts()
  await loadScopedData()
}

async function refreshAfterImport(message: string, successMessage: string) {
  latestImportMessage.value = message
  ElMessage.success(successMessage)
  currentPage.value = 1
  poolFilter.value = undefined
  await loadScopedData()
}

async function handleImport() {
  if (!canImport.value) return
  importing.value = true
  try {
    const { data } = await gachaApi.import({
      account_id: selectedAccountId.value,
      game: selectedGame.value,
      game_uid: selectedGameUid.value,
      import_url: importUrl.value.trim(),
    })
    importUrl.value = ''
    await refreshAfterImport(
      `链接导入新增 ${data.inserted_count} 条，跳过重复 ${data.duplicate_count} 条`,
      data.message || '抽卡记录导入完成'
    )
  } finally {
    importing.value = false
  }
}

async function handleImportFromAccount() {
  if (!selectedAccountId.value || !selectedGameUid.value || selectedGame.value !== 'genshin') return

  accountImporting.value = true
  try {
    const { data } = await gachaApi.importFromAccount({
      account_id: selectedAccountId.value,
      game: selectedGame.value,
      game_uid: selectedGameUid.value,
    })
    await refreshAfterImport(
      `账号自动导入新增 ${data.inserted_count} 条，跳过重复 ${data.duplicate_count} 条`,
      data.message || '已从账号自动导入抽卡记录'
    )
  } finally {
    accountImporting.value = false
  }
}

function openUigfFilePicker() {
  uigfFileInput.value?.click()
}

async function handleUigfFileChange(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  if (!file || !selectedAccountId.value || !selectedGame.value || !selectedGameUid.value) {
    input.value = ''
    return
  }

  uigfImporting.value = true
  try {
    const text = await file.text()
    // 正式文件交换协议已经统一为 UIGF，前端不再把文件解析成私有 `records` 数组。
    // 兼容版本、字段归一化与错误语义都以后端 UIGF 适配层为单一事实来源；
    // 如果这里继续做前端自定义转换，最容易出现“页面能导，导出的备份却无法标准互通”的双协议回归。
    const { data } = await gachaApi.importUigf({
      account_id: selectedAccountId.value,
      game: selectedGame.value,
      game_uid: selectedGameUid.value,
      source_name: file.name,
      uigf_json: text,
    })
    await refreshAfterImport(
      `UIGF 导入新增 ${data.inserted_count} 条，跳过重复 ${data.duplicate_count} 条`,
      data.message || 'UIGF 导入完成'
    )
  } catch (error: any) {
    if (!error?.response) {
      ElMessage.error(error instanceof Error ? error.message : '读取 UIGF 文件失败，请稍后重试')
    }
  } finally {
    input.value = ''
    uigfImporting.value = false
  }
}

async function handleExportUigf() {
  if (!selectedAccountId.value || !selectedGame.value || !selectedGameUid.value) return

  exporting.value = true
  try {
    const { data } = await gachaApi.exportUigf({
      account_id: selectedAccountId.value,
      game: selectedGame.value,
      game_uid: selectedGameUid.value,
    })

    const blob = new Blob([JSON.stringify(data.uigf, null, 2)], { type: 'application/json;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = `uigf-${selectedGame.value}-uid-${selectedGameUid.value}-account-${selectedAccountId.value}.json`
    document.body.appendChild(link)
    link.click()
    document.body.removeChild(link)
    URL.revokeObjectURL(url)
    ElMessage.success(`已导出 ${data.total || 0} 条 UIGF 抽卡记录`)
  } finally {
    exporting.value = false
  }
}

async function handleReset() {
  if (!selectedAccountId.value || !selectedGame.value || !selectedGameUid.value) return

  const accountLabel = currentAccount.value
    ? formatAccountLabel(currentAccount.value as GachaAccount)
    : `账号 ${selectedAccountId.value}`
  const roleLabel = currentRole.value ? formatRoleLabel(currentRole.value) : `UID ${selectedGameUid.value}`
  try {
    await ElMessageBox.confirm(
      `将删除账号“${accountLabel}”在当前角色“${roleLabel}”下的全部抽卡记录和导入历史，且不可恢复。`,
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
      game_uid: selectedGameUid.value,
    })
    latestImportMessage.value = '当前抽卡数据已重置'
    ElMessage.success(data.message || '抽卡记录已重置')
    currentPage.value = 1
    poolFilter.value = undefined
    await loadScopedData()
  } finally {
    resetting.value = false
  }
}

function handleAccountChange() {
  currentPage.value = 1
  poolFilter.value = undefined
  applyPreferredGameSelection()
  applyPreferredRoleSelection()
  loadScopedData()
}

function handleGameChange() {
  currentPage.value = 1
  poolFilter.value = undefined
  applyPreferredRoleSelection()
  loadScopedData()
}

function handleRoleChange() {
  currentPage.value = 1
  poolFilter.value = undefined
  loadScopedData()
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
  width: 100%;
}

.import-card,
.pool-card,
.record-card {
  overflow: hidden;
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
  flex-wrap: wrap;
  gap: 12px;
}

.game-scope-hint {
  margin-top: 12px;
  font-size: 12px;
  line-height: 1.7;
  color: var(--text-secondary);
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

  .backup-actions,
  .import-actions {
    flex-direction: column;
    align-items: stretch;
  }
}
</style>
