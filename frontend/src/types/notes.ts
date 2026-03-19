export type NoteStatus =
  | 'available'
  | 'invalid_cookie'
  | 'verification_required'
  | 'upstream_error'
  | 'unsupported'

export type NoteDetailKind = 'genshin' | 'starrail' | 'zzz'

export type NoteMetric = {
  key: string
  label: string
  value: string
  detail?: string | null
  tone: string
}

export type NoteAccount = {
  id: number
  nickname?: string
  mihoyo_uid?: string
  supported_games: string[]
}

export type GenshinNoteDetail = {
  current_resin: number
  max_resin: number
  remaining_resin_recovery_seconds: number
  current_realm_currency: number
  max_realm_currency: number
  remaining_realm_currency_recovery_seconds: number
  completed_commissions: number
  max_commissions: number
  claimed_commission_reward: boolean
  remaining_weekly_discounts: number
  max_weekly_discounts: number
  expeditions_finished: number
  expeditions_total: number
}

export type StarrailNoteDetail = {
  current_stamina: number
  max_stamina: number
  remaining_stamina_recovery_seconds: number
  current_reserve_stamina: number
  is_reserve_stamina_full: boolean
  current_train_score: number
  max_train_score: number
  accepted_expedition_num: number
  total_expedition_num: number
  finished_expeditions: number
  current_rogue_score: number
  max_rogue_score: number
  current_bonus_synchronicity_points: number
  max_bonus_synchronicity_points: number
  have_bonus_synchronicity_points: boolean
  remaining_weekly_discounts: number
  max_weekly_discounts: number
}

export type ZzzNoteDetail = {
  battery_charge: {
    current: number
    max: number
    seconds_till_full: number
  }
  engagement: {
    current: number
    max: number
  }
  scratch_card_completed: boolean
  video_store_state: string | null
  hollow_zero: {
    bounty_commission: Record<string, unknown> | null
    investigation_point: Record<string, unknown> | null
  }
  card_sign: string | null
  member_card: {
    is_open: boolean
    member_card_state: string | null
    seconds_until_expire: number
  }
  temple_running: {
    bench_state: string | null
    current_currency: number
    currency_next_refresh_seconds: number
    expedition_state: string | null
    level: number
    shelve_state: string | null
    weekly_currency_max: number
  }
  weekly_task: {
    cur_point: number
    max_point: number
    refresh_seconds: number
  } | null
}

type NoteCardBase = {
  role_id: number
  game: string
  game_name: string
  game_biz: string
  role_uid: string
  role_nickname?: string | null
  region?: string | null
  level?: number | null
  status: NoteStatus
  message?: string | null
  updated_at?: string | null
  metrics: NoteMetric[]
}

export type GenshinNoteCard = NoteCardBase & {
  detail_kind: 'genshin'
  detail: GenshinNoteDetail
}

export type StarrailNoteCard = NoteCardBase & {
  detail_kind: 'starrail'
  detail: StarrailNoteDetail
}

export type ZzzNoteCard = NoteCardBase & {
  detail_kind: 'zzz'
  detail: ZzzNoteDetail
}

export type NoteCard =
  | GenshinNoteCard
  | StarrailNoteCard
  | ZzzNoteCard
  | (NoteCardBase & {
      detail_kind?: NoteDetailKind | null
      detail?: Record<string, unknown> | null
    })

export type NoteSummaryResponse = {
  schema_version: 2
  provider: 'genshin.py'
  account_id: number
  account_name: string
  total_cards: number
  available_cards: number
  failed_cards: number
  cards: NoteCard[]
}
