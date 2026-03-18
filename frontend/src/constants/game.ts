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
