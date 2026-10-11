<script lang="ts" setup>
import Button from 'primevue/button'
import { computed } from 'vue'
import type { Clarification } from '../api/types'

const props = defineProps<{
  clarification: Clarification
  /** True while the answer request is in flight; every chip becomes inert. */
  pending?: boolean
  /** The run offered no fitting position: suggest a wider search. */
  suggestExpand?: boolean
}>()

const emit = defineEmits<{ expand: []; select: [optionId: string] }>()

const heading = computed(() =>
  props.clarification.manual_choice ? 'Уточните вручную' : 'Уточняющий вопрос',
)

const EXPAND_MARK = 'показать ещё варианты'

const PANEL_CLASS =
  'card-registry animate-rise-in space-y-4 border-l-4 border-l-primary-400 bg-primary-50 p-5'

const OPTION_CLASS =
  'chip chip-option h-auto min-h-[26px] cursor-pointer py-1 transition hover:border-primary-500 hover:bg-primary-50 hover:text-primary-700 disabled:cursor-not-allowed disabled:border-ink-200 disabled:bg-ink-100 disabled:text-ink-400'

const EXPAND_NOTE =
  'В коротком списке не нашлось подходящей позиции. Запустите расширенный поиск — система проверит больше кандидатов КТРУ.'

function choose(optionId: string) {
  if (!props.pending) emit('select', optionId)
}
</script>

<template>
  <section :class="PANEL_CLASS" data-test="clarification">
    <div class="space-y-1">
      <p class="eyebrow text-primary-600">{{ heading }}</p>
      <p class="text-[15px] font-semibold text-ink-900">{{ clarification.question }}</p>
    </div>

    <div class="flex flex-wrap items-center gap-2">
      <button
        v-for="option in clarification.options"
        :class="OPTION_CLASS"
        :disabled="pending"
        :key="option.id"
        @click="choose(option.id)"
        data-test="option"
        type="button"
      >
        {{ option.text }}
        <span class="text-primary-400" v-if="option.suggest_expand">· {{ EXPAND_MARK }}</span>
      </button>
    </div>

    <div
      class="card-registry space-y-2 border-warning-200 bg-warning-50 p-4 text-sm text-warning-700"
      v-if="suggestExpand"
    >
      <p>{{ EXPAND_NOTE }}</p>
      <Button
        :disabled="pending"
        @click="emit('expand')"
        data-test="expand"
        label="Расширенный поиск"
        severity="secondary"
        size="small"
      />
    </div>
  </section>
</template>
