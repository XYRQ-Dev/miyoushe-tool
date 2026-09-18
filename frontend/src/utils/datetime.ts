const SHANGHAI = 'Asia/Shanghai'

type ShanghaiParts = {
  year: number
  month: number
  day: number
  hour: number
  minute: number
  second: number
}

function pad(value: number): string {
  return String(value).padStart(2, '0')
}

function toShanghaiParts(value: string): ShanghaiParts | null {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return null

  const parts = new Intl.DateTimeFormat('en-US', {
    timeZone: SHANGHAI,
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hourCycle: 'h23',
  }).formatToParts(date)

  const pick = (type: Intl.DateTimeFormatPartTypes) =>
    Number(parts.find((part) => part.type === type)?.value)

  return {
    year: pick('year'),
    month: pick('month'),
    day: pick('day'),
    hour: pick('hour') % 24,
    minute: pick('minute'),
    second: pick('second'),
  }
}

export function formatDateTime(value?: string | null, fallback = ''): string {
  if (!value) return fallback
  const parts = toShanghaiParts(value)
  if (!parts) return value
  return `${parts.year}/${pad(parts.month)}/${pad(parts.day)} ${pad(parts.hour)}:${pad(parts.minute)}:${pad(parts.second)}`
}

export function formatDateTimeShort(value?: string | null, fallback = ''): string {
  if (!value) return fallback
  const parts = toShanghaiParts(value)
  if (!parts) return value
  return `${pad(parts.month)}/${pad(parts.day)} ${pad(parts.hour)}:${pad(parts.minute)}`
}

export function formatMonthDay(dateStr: string): string {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(dateStr)
  if (!match) return dateStr
  return `${Number(match[2])}/${Number(match[3])}`
}
