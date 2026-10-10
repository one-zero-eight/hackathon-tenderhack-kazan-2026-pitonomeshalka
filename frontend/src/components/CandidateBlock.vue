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

const MISSING_CHIP =
  'inline-flex rounded-lg border border-danger-200 bg-danger-50 px-2 py-1 text-xs text-danger-700'
</script>

<template>
  <article class="space-y-3 rounded-2xl border border-ink-200 bg-white p-4">
    <div class="flex flex-wrap items-start gap-3">
      <div class="min-w-0">
        <p class="font-medium text-ink-900">{{ candidate.name }}</p>
        <p class="font-mono text-xs break-all text-ink-500">
          {{ candidate.code }}@{{ candidate.version }}
        </p>
      </div>
      <StatusChip class="ml-auto" :status="candidate.status" />
    </div>

    <ul class="space-y-1 text-sm text-ink-700" v-if="candidate.reasons.length">
      <li class="flex gap-2" v-for="reason in candidate.reasons" :key="reason">
        <span class="text-ink-300">—</span>
        {{ reason }}
      </li>
    </ul>

    <div class="space-y-1" v-if="candidate.missing_required.length">
      <p class="text-xs font-medium text-danger-700">
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

    <div class="space-y-1" v-if="candidate.unmatched_properties.length">
      <p class="text-xs font-medium text-ink-500">Не сопоставлено со схемой позиции</p>
      <div class="flex flex-wrap gap-1.5">
        <span
          class="rounded-lg bg-ink-100 px-2 py-1 text-xs text-ink-700"
          v-for="unmatched in candidate.unmatched_properties"
          :key="unmatched"
        >
          {{ unmatched }}
        </span>
      </div>
    </div>

    <div class="space-y-1" v-if="candidate.extra_characteristics.length">
      <p class="text-xs font-medium text-ink-500">Дополнительные характеристики</p>
      <ul class="space-y-1 text-xs text-ink-700">
        <li v-for="extra in candidate.extra_characteristics" :key="`${extra.name}:${extra.value}`">
          {{ extra.name }}: {{ extra.value }} —
          <span class="text-ink-500">{{ ACTIONS[extra.action] }}</span>
        </li>
      </ul>
    </div>
  </article>
</template>
