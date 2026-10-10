<script lang="ts" setup>
import { computed } from 'vue'
import type { AnalysisResponse } from '../api/types'
import CandidateBlock from './CandidateBlock.vue'
import PropertiesTable from './PropertiesTable.vue'
import StatusChip from './ui/StatusChip.vue'

const props = defineProps<{ result: AnalysisResponse }>()

const recommended = computed(() => {
  const code = props.result.recommended_candidate
  if (!code) return null
  const found = props.result.candidates.find(
    (candidate) => `${candidate.code}@${candidate.version}` === code,
  )
  return { code, name: found?.name ?? null }
})
</script>

<template>
  <section class="space-y-4" data-test="result">
    <div class="flex flex-wrap items-center gap-3">
      <h2 class="text-lg font-semibold text-ink-900">Результат анализа</h2>
      <StatusChip :status="result.status" />
      <span class="text-xs text-warning-700" v-if="!result.complete_inference">
        модель ответила не полностью
      </span>
    </div>

    <div
      class="rounded-2xl border border-primary-200 bg-primary-50 p-5"
      v-if="recommended"
      data-test="recommended"
    >
      <p class="text-xs font-medium tracking-wide text-primary-700 uppercase">
        Предварительная рекомендация
      </p>
      <p class="mt-1 font-mono text-xl font-semibold break-all text-primary-800">
        {{ recommended.code }}
      </p>
      <p class="mt-1 text-sm text-ink-700" v-if="recommended.name">{{ recommended.name }}</p>
      <p class="mt-2 text-xs text-ink-500">Код требует финальной проверки специалистом</p>
    </div>

    <div
      class="rounded-2xl border border-ink-200 bg-white p-4 text-sm text-ink-700"
      v-if="result.clarifying_question"
    >
      <span class="font-medium text-primary-700">Уточнение: </span>
      {{ result.clarifying_question }}
    </div>

    <div class="space-y-3 rounded-2xl border border-ink-200 bg-white p-5">
      <h3 class="text-sm font-semibold text-ink-700">Характеристики из запроса</h3>
      <PropertiesTable :properties="result.properties" />
      <p class="text-sm text-ink-400" v-if="result.properties.length === 0">
        Характеристики не распознаны
      </p>
    </div>

    <div
      class="rounded-2xl border border-warning-200 bg-warning-50 p-4 text-sm text-warning-700"
      v-if="result.warnings.length"
    >
      <p class="font-medium">Предупреждения</p>
      <ul class="mt-1 list-disc space-y-1 pl-5">
        <li v-for="warning in result.warnings" :key="warning">{{ warning }}</li>
      </ul>
    </div>

    <div class="space-y-3">
      <h3 class="text-sm font-semibold text-ink-700">
        Кандидаты КТРУ ({{ result.candidates.length }})
      </h3>
      <CandidateBlock
        v-for="candidate in result.candidates"
        :candidate="candidate"
        :key="`${candidate.code}@${candidate.version}`"
      />
      <p class="text-sm text-ink-400" v-if="result.candidates.length === 0">Кандидаты не найдены</p>
    </div>
  </section>
</template>
