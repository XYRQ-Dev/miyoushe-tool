export function getNoteStatusText(statusText: string) {
  if (statusText === 'available') return '可用'
  if (statusText === 'invalid_cookie') return '登录失效'
  if (statusText === 'verification_required') return '需验证'
  if (statusText === 'unsupported') return '未接入'
  return '查询失败'
}

export function getNoteStatusType(statusText: string) {
  if (statusText === 'available') return 'success'
  if (statusText === 'invalid_cookie') return 'warning'
  if (statusText === 'verification_required') return 'warning'
  return 'danger'
}

export function getNoteNoticeTone(statusText: string) {
  // 需验证不是“系统错误”，而是需要用户继续完成一次上游确认动作。
  // 如果这里误返回 error，首页会把可恢复场景渲染成红色故障块，用户会误以为链路已经不可用。
  if (statusText === 'verification_required') return 'warning'
  return 'error'
}
