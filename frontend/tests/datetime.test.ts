import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'

import { formatDateTime, formatDateTimeShort, formatMonthDay } from '../src/utils/datetime.ts'

const utcInstant = '2026-03-16T16:30:00.000Z'
const shanghaiInstant = '2026-03-17T00:30:00+08:00'

assert.equal(formatDateTime(utcInstant), '2026/03/17 00:30:00')
assert.equal(formatDateTime(shanghaiInstant), '2026/03/17 00:30:00')
assert.equal(formatDateTime(null, '未知时间'), '未知时间')
assert.equal(formatDateTimeShort(utcInstant), '03/17 00:30')
assert.equal(formatMonthDay('2026-03-17'), '3/17')
console.log('datetime tests passed')

const vueFiles = [
  'src/components/LogTable.vue',
  'src/components/AccountCard.vue',
  'src/views/TaskLogs.vue',
  'src/views/Settings.vue',
  'src/views/Accounts.vue',
  'src/views/AdminUsers.vue',
  'src/views/Dashboard.vue',
]

for (const relativePath of vueFiles) {
  const source = fs.readFileSync(path.resolve(relativePath), 'utf8')
  assert.doesNotMatch(
    source,
    /toLocaleString\(/,
    `${relativePath} 不应再用浏览器时区 toLocaleString 格式化时间`,
  )
}
