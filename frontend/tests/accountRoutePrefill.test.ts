import assert from 'node:assert/strict'

import { resolveRouteAccountPrefill } from '../src/utils/accountRoutePrefill.ts'

const firstLoad = resolveRouteAccountPrefill('12', {
  consumed: false,
  availableAccountIds: [7, 12, 18],
})
assert.equal(firstLoad.preferredAccountId, 12)
assert.equal(firstLoad.consumed, true)

const consumedAgain = resolveRouteAccountPrefill('12', {
  consumed: true,
  availableAccountIds: [7, 12, 18],
})
assert.equal(consumedAgain.preferredAccountId, null)
assert.equal(consumedAgain.consumed, true)

const invalid = resolveRouteAccountPrefill('abc', {
  consumed: false,
  availableAccountIds: [7, 12, 18],
})
const missing = resolveRouteAccountPrefill('99', {
  consumed: false,
  availableAccountIds: [7, 12, 18],
})
assert.deepEqual(invalid, { preferredAccountId: null, consumed: true })
assert.deepEqual(missing, { preferredAccountId: null, consumed: true })

const emptyOnFirstLoad = resolveRouteAccountPrefill('12', {
  consumed: false,
  availableAccountIds: [],
})
assert.deepEqual(emptyOnFirstLoad, { preferredAccountId: null, consumed: true })

const shouldNotReplayAfterEmptyLoad = resolveRouteAccountPrefill('12', {
  consumed: emptyOnFirstLoad.consumed,
  availableAccountIds: [7, 12, 18],
})
assert.deepEqual(shouldNotReplayAfterEmptyLoad, { preferredAccountId: null, consumed: true })

console.log('accountRoutePrefill tests passed')
