/**
 * 账号 query 预填只允许消费一次。
 *
 * 健康中心等聚合页会把 `account_id` 通过 query 带到目标页，但该上下文只应该影响首次落地。
 * 如果后续每次刷新都继续重放旧 query，用户在页面内手动切换账号会被强行改回去。
 */
type RouteAccountPrefillOptions = {
  consumed: boolean
  availableAccountIds: number[]
}

export function resolveRouteAccountPrefill(
  rawAccountId: unknown,
  options: RouteAccountPrefillOptions,
) {
  const { consumed, availableAccountIds } = options

  // 前端最小回归测试直接由 Node 的 strip-types 解释执行，不能使用仅部分运行时支持的参数分隔语法。
  // 这里统一退回普通 options 对象，避免测试层先于业务逻辑报语法错误，导致真正的回归点被掩盖。
  if (consumed) {
    return { preferredAccountId: null, consumed }
  }

  const parsedAccountId = Number(rawAccountId)
  if (!Number.isInteger(parsedAccountId) || parsedAccountId <= 0) {
    return { preferredAccountId: null, consumed: true }
  }

  // “只消费一次”针对的是路由上下文本身，而不是账号列表是否刚好已经加载完成。
  // 如果首屏没有账号却不把 query 标记为已消费，用户后续在同页导入账号或刷新数据时，
  // 旧 query 会再次强行覆盖当前选择，回到本次修复前的错误行为。
  if (availableAccountIds.length === 0) {
    return { preferredAccountId: null, consumed: true }
  }

  if (!availableAccountIds.includes(parsedAccountId)) {
    return { preferredAccountId: null, consumed: true }
  }

  return { preferredAccountId: parsedAccountId, consumed: true }
}
