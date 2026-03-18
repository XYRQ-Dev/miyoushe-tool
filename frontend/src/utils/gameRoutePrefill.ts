/**
 * 游戏 query 预填同样只允许消费一次。
 *
 * 角色资产页会把 `game` 一并带到抽卡/兑换页，目的是让用户落地后直接看到目标游戏。
 * 如果后续刷新仍重放旧 query，用户手动切换游戏会被强行改回去，页面就会再次出现“看起来选不住”的错误体验。
 */
type RouteGamePrefillOptions = {
  consumed: boolean
  availableGames: string[]
}

export function resolveRouteGamePrefill(
  rawGame: unknown,
  options: RouteGamePrefillOptions,
) {
  const { consumed, availableGames } = options

  if (consumed) {
    return { preferredGame: null, consumed }
  }

  const parsedGame = String(rawGame || '').trim()
  if (!parsedGame) {
    return { preferredGame: null, consumed: true }
  }

  // “只消费一次”针对的是路由上下文本身，而不是当前账号列表是否已经完成加载。
  // 如果这里在空游戏列表时不消费 query，那么账号数据稍后刷新出来后，
  // 旧 game 会再次覆盖用户已手动切换的游戏选择。
  if (availableGames.length === 0) {
    return { preferredGame: null, consumed: true }
  }

  if (!availableGames.includes(parsedGame)) {
    return { preferredGame: null, consumed: true }
  }

  return { preferredGame: parsedGame, consumed: true }
}
