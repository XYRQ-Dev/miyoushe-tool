/**
 * 角色 UID query 预填也必须只消费一次。
 *
 * 抽卡页现在是“账号 -> 游戏 -> UID”三级联动，`game_uid` 只应用于首次落地，不能在后续刷新或用户手动切换角色时反复重放。
 * 否则旧 query 会把用户当前正在查看的角色强行切回 URL 里的 UID，造成“页面看起来选不住角色”的长期回归。
 */
type RouteGameUidPrefillOptions = {
  consumed: boolean
  availableGameUids: string[]
}

type GachaRoleLabelInput = {
  nickname?: string | null
  game_uid: string
}

export function resolveRouteGameUidPrefill(
  rawGameUid: unknown,
  options: RouteGameUidPrefillOptions,
) {
  const { consumed, availableGameUids } = options

  if (consumed) {
    return { preferredGameUid: null, consumed }
  }

  const parsedGameUid = String(rawGameUid || '').trim()
  if (!parsedGameUid) {
    return { preferredGameUid: null, consumed: true }
  }

  // 这里即使当前还没有候选 UID，也要把 query 记为已消费。
  // 否则账号列表稍后刷新出来时，旧 URL 里的 UID 会再次覆盖用户后续主动选择的角色，
  // 让“首次落地预填”退化成“持续强制回放”。
  if (availableGameUids.length === 0) {
    return { preferredGameUid: null, consumed: true }
  }

  if (!availableGameUids.includes(parsedGameUid)) {
    return { preferredGameUid: null, consumed: true }
  }

  return { preferredGameUid: parsedGameUid, consumed: true }
}

export function formatGachaRoleLabel(role: GachaRoleLabelInput) {
  const normalizedNickname = String(role.nickname || '').trim()
  const normalizedGameUid = String(role.game_uid || '').trim()
  return `${normalizedNickname || normalizedGameUid} (${normalizedGameUid})`
}
