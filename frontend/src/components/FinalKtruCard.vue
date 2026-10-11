<script lang="ts" setup>
import { computed } from 'vue'
import type { FinalCard, FinalCardCharacteristic } from '../api/types'

interface ValueSpan {
  lower?: unknown
  upper?: unknown
  bounds?: unknown
}

const props = defineProps<{ card: FinalCard }>()

/** Value lists longer than this fold into a <details> block. */
const FOLD_AFTER = 6

const CHOICE_LABELS: Record<string, string> = {
  one_of: 'выбор одного значения',
  many_of: 'выбор нескольких значений',
}

const unitsLabel = computed(() => props.card.units.join(', '))

function choiceLabel(choice: string): string {
  return CHOICE_LABELS[choice] ?? choice
}

function folds(characteristic: FinalCardCharacteristic): boolean {
  return characteristic.values.length > FOLD_AFTER
}

function asText(raw: unknown): string | null {
  return typeof raw === 'string' && raw.length > 0 ? raw : null
}

/** Bounds are two chars: lower ('[' inclusive / '(' exclusive), upper (']' / ')'). */
function formatSpan(span: ValueSpan): string {
  const lower = asText(span.lower)
  const upper = asText(span.upper)
  const bounds = asText(span.bounds) ?? '[]'
  const lowerIncluded = bounds.charAt(0) !== '('
  const upperIncluded = bounds.charAt(1) !== ')'
  if (lower !== null && upper !== null) {
    if (lower === upper) return lower
    const lowerPart = lowerIncluded ? `от ${lower} (включительно)` : `более ${lower}`
    const upperPart = upperIncluded ? `до ${upper} (включительно)` : `до ${upper} (не включая)`
    return `${lowerPart} ${upperPart}`
  }
  if (lower !== null) return lowerIncluded ? `не менее ${lower}` : `более ${lower}`
  if (upper !== null) return upperIncluded ? `не более ${upper}` : `менее ${upper}`
  return '—'
}

function valueText(value: Record<string, unknown>): string {
  const spans = Array.isArray(value.spans) ? (value.spans as ValueSpan[]) : []
  if (spans.length > 0) return spans.map(formatSpan).join(' или ')
  return asText(value.text) ?? '—'
}
</script>

<template>
  <article
    class="card-registry animate-rise-in space-y-4 border-l-4 border-l-primary-600 p-5"
    data-test="final-card"
  >
    <div class="flex flex-wrap items-center gap-3">
      <p class="eyebrow text-primary-600">Итоговый код КТРУ</p>
      <span class="stamp stamp-warning ml-auto" data-test="review-badge">
        <span class="stamp-icon" aria-hidden="true">!</span>
        Требует финальной проверки специалистом
      </span>
    </div>

    <div class="space-y-1">
      <p
        class="font-mono text-2xl font-bold tracking-tight break-all text-primary-700"
        data-test="card-code"
      >
        {{ card.code }}
      </p>
      <p class="text-[15px] font-semibold text-ink-900">{{ card.name }}</p>
      <p class="text-xs text-ink-500">
        Версия {{ card.version }} · Статус: {{ card.status }} · Единицы измерения:
        {{ unitsLabel }}
      </p>
    </div>

    <div class="space-y-3 border-t border-ink-200 pt-3" v-if="card.characteristics.length">
      <h3 class="eyebrow border-b border-ink-200 pb-2">Характеристики позиции</h3>
      <div
        class="space-y-1"
        v-for="characteristic in card.characteristics"
        :key="characteristic.code"
      >
        <p class="text-sm font-semibold text-ink-900">
          {{ characteristic.name }}
          <span class="font-normal text-ink-500">
            — {{ choiceLabel(characteristic.choice)
            }}{{ characteristic.required ? ', обязательная' : '' }}
          </span>
        </p>
        <ul class="list-disc space-y-0.5 pl-5 text-sm text-ink-700" v-if="!folds(characteristic)">
          <li v-for="(value, index) in characteristic.values" :key="index">
            {{ valueText(value) }}
          </li>
        </ul>
        <details v-else>
          <summary class="cursor-pointer text-sm font-semibold text-primary-700">
            Все значения ({{ characteristic.values.length }})
          </summary>
          <ul class="list-disc space-y-0.5 pt-1 pl-5 text-sm text-ink-700">
            <li v-for="(value, index) in characteristic.values" :key="index">
              {{ valueText(value) }}
            </li>
          </ul>
        </details>
      </div>
    </div>

    <p class="border-t border-ink-200 pt-2 text-xs text-ink-500">Основание: {{ card.rationale }}</p>
  </article>
</template>
