// 游戏名称映射只负责前端展示文案，不参与任何签到能力判断。
// 如果把“这里有中文名”误理解成“这里已接入签到”，会让未适配的游戏在界面上看起来像已支持，
// 从而误导用户和排障人员把问题归因到后端或登录态，而不是前端展示配置。
export const GAME_NAME_MAP: Record<string, string> = {
  genshin: '原神',
  starrail: '星穹铁道',
  hk4e_cn: '原神',
  hk4e_bilibili: '原神(B服)',
  hkrpg_cn: '星穹铁道',
  hkrpg_bilibili: '星铁(B服)',
  honkai3rd: '崩坏3',
  zenless: '绝区零',
  nap_cn: '绝区零',
  bh3_cn: '崩坏3',
  bh2_cn: '崩坏学园2',
}

export function getGameName(gameBiz?: string | null) {
  if (!gameBiz) return '-'
  return GAME_NAME_MAP[gameBiz] || gameBiz
}

// 签到日志筛选只暴露产品层的 4 个游戏。
// B 服 biz 不是独立筛选项，后端会把 hk4e_bilibili / hkrpg_bilibili 并进对应游戏。
export const CHECKIN_GAME_FILTER_OPTIONS = [
  { label: '原神', value: 'hk4e' },
  { label: '星穹铁道', value: 'hkrpg' },
  { label: '崩坏3', value: 'bh3' },
  { label: '绝区零', value: 'nap' },
] as const

export const GAME_FAMILY_BY_BIZ: Record<string, string> = {
  hk4e_cn: 'hk4e',
  hk4e_bilibili: 'hk4e',
  hkrpg_cn: 'hkrpg',
  hkrpg_bilibili: 'hkrpg',
  bh3_cn: 'bh3',
  nap_cn: 'nap',
}

export function getGameFamily(gameBiz?: string | null) {
  if (!gameBiz) return ''
  return GAME_FAMILY_BY_BIZ[gameBiz] || ''
}

export const CHECKIN_GAME_FILTER_LABELS: Record<string, string> = Object.fromEntries(
  CHECKIN_GAME_FILTER_OPTIONS.map((option) => [option.value, option.label]),
)
