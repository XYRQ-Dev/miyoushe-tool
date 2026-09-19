export function formatReward(name?: string | null, cnt?: number | null) {
  if (!name) return ''
  if (cnt == null) return name
  return `${name} ×${cnt}`
}
