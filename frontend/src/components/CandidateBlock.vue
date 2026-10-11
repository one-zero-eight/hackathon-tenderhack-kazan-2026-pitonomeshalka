<script lang="ts" setup>
import type { Candidate, ExtraAction } from '../api/types'
import StatusChip from './ui/StatusChip.vue'

defineProps<{ candidate: Candidate }>()

const ACTIONS: Record<ExtraAction, string> = {
  map_and_validate: 'добавлено и проверено',
  do_not_add: 'не добавлять',
  review_before_add: 'проверить перед добавлением',
  additional_field_policy_unknown: 'правило неизвестно',
}

const MISSING_CHIP = 'chip border border-accent-200 bg-accent-50 text-accent-700'

const CODE_CHIP =
  'mt-1 inline-block bg-primary-50 px-1.5 py-0.5 font-mono text-xs break-all text-primary-600'
</script>

<template>
  <article class="card-registry animate-rise-in space-y-3 border-l-4 border-l-ink-300 p-4">
    <div class="flex flex-wrap items-start gap-3">
      <div class="min-w-0">
        <p class="text-[15px] font-semibold text-ink-900">{{ candidate.name }}</p>
        <p :class="CODE_CHIP">{{ candidate.code }}@{{ candidate.version }}</p>
      </div>
      <StatusChip class="ml-auto" :status="candidate.status" />
    </div>

    <ul class="space-y-1 text-sm text-ink-700" v-if="candidate.reasons.length">
      <li class="flex gap-2" v-for="reason in candidate.reasons" :key="reason">
        <span class="text-primary-300">—</span>
        {{ reason }}
      </li>
    </ul>

    <div class="space-y-1" v-if="candidate.missing_required?.length">
      <p class="text-xs font-semibold text-accent-700">
        Обязательные характеристики, которых нет в запросе
      </p>
      <div class="flex flex-wrap gap-1.5">
        <span
          v-for="missing in candidate.missing_required"
          :class="MISSING_CHIP"
          :key="missing"
          :title="`«${missing}» есть в КТРУ, но не найдено в вашем запросе`"
        >
          {{ missing }} · Нет в запросе
        </span>
      </div>
    </div>

    <div class="space-y-1" v-if="candidate.unmatched_properties?.length">
      <p class="text-xs font-semibold text-ink-500">Не сопоставлено со схемой позиции</p>
      <div class="flex flex-wrap gap-1.5">
        <span
          class="chip bg-ink-100 text-ink-700"
          v-for="unmatched in candidate.unmatched_properties"
          :key="unmatched"
        >
          {{ unmatched }}
        </span>
      </div>
    </div>

    <div class="space-y-1" v-if="candidate.extra_characteristics?.length">
      <p class="text-xs font-semibold text-ink-500">Дополнительные характеристики</p>
      <ul class="space-y-1 text-xs text-ink-700">
        <li v-for="extra in candidate.extra_characteristics" :key="`${extra.name}:${extra.value}`">
          {{ extra.name }}: {{ extra.value }} —
          <span class="text-ink-500">{{ ACTIONS[extra.action] }}</span>
        </li>
      </ul>
    </div>
  </article>
</template>
