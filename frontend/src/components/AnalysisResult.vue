<script lang="ts" setup>
import Button from 'primevue/button'
import { computed } from 'vue'
import type { AnalysisResponse } from '../api/types'
import CandidateBlock from './CandidateBlock.vue'
import ClarificationPanel from './ClarificationPanel.vue'
import FinalKtruCard from './FinalKtruCard.vue'
import PropertiesTable from './PropertiesTable.vue'
import StatusChip from './ui/StatusChip.vue'

const props = defineProps<{
  result: AnalysisResponse
  /** The last clarification answer failed; shown inside the clarification panel. */
  clarificationError?: string | null
}>()

const emit = defineEmits<{ expand: []; select: [optionId: string]; submitText: [text: string] }>()

const recommended = computed(() => {
  const code = props.result.recommended_candidate
  if (!code) return null
  const found = props.result.candidates.find(
    (candidate) => `${candidate.code}@${candidate.version}` === code,
  )
  return { code, name: found?.name ?? null }
})

const WARNINGS_CLASS =
  'card-registry border-l-4 border-l-warning-500 bg-warning-50 p-4 text-warning-700'

const EXPAND_HINT =
  'Подходящей позиции в коротком списке не нашлось. Запустите расширенный поиск — система проверит больше кандидатов КТРУ.'
</script>

<template>
  <section class="animate-rise-in space-y-4" data-test="result">
    <div class="flex flex-wrap items-center gap-3">
      <h2 class="eyebrow">Результат анализа</h2>
      <StatusChip :status="result.status" />
      <span class="text-xs font-semibold text-warning-700" v-if="!result.complete_inference">
        модель ответила не полностью
      </span>
    </div>

    <div
      class="card-registry border-l-4 border-l-primary-600 p-5"
      v-if="recommended"
      data-test="recommended"
    >
      <p class="eyebrow text-primary-600">Предварительная рекомендация</p>
      <p class="mt-2 font-mono text-2xl font-bold tracking-tight break-all text-primary-700">
        {{ recommended.code }}
      </p>
      <p class="mt-1 text-[15px] font-semibold text-ink-900" v-if="recommended.name">
        {{ recommended.name }}
      </p>
      <p class="mt-3 border-t border-ink-200 pt-2 text-xs text-ink-500">
        Код требует финальной проверки специалистом
      </p>
    </div>

    <div
      class="card-registry border-l-4 border-l-primary-400 bg-primary-50 p-4 text-sm"
      v-if="result.clarifying_question"
    >
      <span class="font-semibold text-primary-700">Уточнение: </span>
      <span class="text-ink-700">{{ result.clarifying_question }}</span>
    </div>

    <div class="card-registry space-y-3 p-5">
      <h3 class="eyebrow border-b border-ink-200 pb-2">Характеристики из запроса</h3>
      <PropertiesTable :properties="result.properties" />
      <p class="text-sm text-ink-500" v-if="result.properties.length === 0">
        Характеристики не распознаны
      </p>
    </div>

    <div v-if="result.warnings.length" :class="WARNINGS_CLASS">
      <p class="font-semibold">Предупреждения</p>
      <ul class="mt-1 list-disc space-y-1 pl-5">
        <li v-for="warning in result.warnings" :key="warning">{{ warning }}</li>
      </ul>
    </div>

    <ClarificationPanel
      v-if="result.clarification"
      :clarification="result.clarification"
      :error="clarificationError"
      :suggest-expand="result.suggest_expand"
      @select="emit('select', $event)"
      @submit-text="emit('submitText', $event)"
    />

    <div
      class="card-registry space-y-2 border-warning-200 bg-warning-50 p-4 text-sm text-warning-700"
      v-else-if="result.suggest_expand"
      data-test="expand-hint"
    >
      <p>{{ EXPAND_HINT }}</p>
      <Button
        @click="emit('expand')"
        data-test="expand"
        label="Расширенный поиск"
        severity="secondary"
        size="small"
      />
    </div>

    <FinalKtruCard v-if="result.final_card" :card="result.final_card" />

    <div class="space-y-3">
      <h3 class="eyebrow border-b border-ink-200 pb-2">
        Кандидаты КТРУ ({{ result.candidates.length }})
      </h3>
      <CandidateBlock
        v-for="candidate in result.candidates"
        :candidate="candidate"
        :key="`${candidate.code}@${candidate.version}`"
      />
      <p class="text-sm text-ink-500" v-if="result.candidates.length === 0">Кандидаты не найдены</p>
    </div>
  </section>
</template>
