<script lang="ts" setup>
import Button from 'primevue/button'
import { computed, ref } from 'vue'
import type { SpellMatch } from '../lib/corrections'

const props = defineProps<{ matches: SpellMatch[] }>()

defineEmits<{
  apply: [index: number, replacement: string]
  applyAll: []
}>()

const MAX_SUGGESTIONS = 3
const FIX_ALL_HINT = 'Применяет первое предложенное исправление для каждой опечатки'
const expanded = ref(true)

/**
 * «Исправить всё» is shown only when at least one match has a non-empty first
 * variant — exactly what applyAllCorrections would actually apply.
 */
const hasSuggestions = computed(() => props.matches.some((m) => !!m.replacements[0]))

const PANEL_CLASS =
  'card-registry animate-rise-in space-y-3 border-l-4 border-l-warning-500 ' + 'bg-warning-50 p-4'

const BODY_CLASS =
  'grid transition-[grid-template-rows,opacity] duration-300 ease-out ' +
  'motion-reduce:transition-none'

const TOGGLE_CLASS =
  'grid h-8 w-8 place-items-center border-2 border-warning-500 bg-white ' +
  'text-warning-700 transition-transform duration-300 hover:bg-warning-50 ' +
  'motion-reduce:transition-none'
</script>

<template>
  <div v-if="matches.length" :class="PANEL_CLASS" data-test="panel">
    <div class="flex items-center gap-3">
      <p class="text-sm font-semibold text-warning-700">
        Похоже, есть опечатки — проверьте перед поиском
      </p>
      <div class="ml-auto flex items-center gap-3">
        <Button
          class="hover:bg-warning-100"
          v-if="hasSuggestions"
          v-tooltip.top="FIX_ALL_HINT"
          @click="$emit('applyAll')"
          data-test="apply-all"
          label="Исправить всё"
          severity="secondary"
          size="small"
        />
        <button
          id="corrections-toggle"
          :aria-expanded="expanded"
          :class="TOGGLE_CLASS"
          :title="expanded ? 'Скрыть исправления' : 'Показать исправления'"
          @click="expanded = !expanded"
          aria-controls="corrections-issues"
          data-test="toggle"
          type="button"
        >
          <svg
            class="h-4 w-4 transition-transform duration-300 motion-reduce:transition-none"
            :class="expanded ? 'rotate-180' : ''"
            aria-hidden="true"
            fill="none"
            viewBox="0 0 20 20"
          >
            <path
              d="m6 8 4 4 4-4"
              stroke="currentColor"
              stroke-linecap="round"
              stroke-linejoin="round"
              stroke-width="1.8"
            />
          </svg>
        </button>
      </div>
    </div>
    <div
      id="corrections-issues"
      :aria-hidden="!expanded"
      :class="[BODY_CLASS, expanded ? 'grid-rows-[1fr] opacity-100' : 'grid-rows-[0fr] opacity-0']"
      data-test="issues"
    >
      <ul class="space-y-2 overflow-hidden">
        <li
          class="text-sm"
          v-for="(match, index) in matches"
          :key="`${match.ruleId}-${match.offset}`"
        >
          <span class="font-medium text-ink-900">«{{ match.errorText }}»</span>
          <span class="text-ink-500"> — {{ match.shortMessage || match.message }}</span>
          <div class="mt-1 flex flex-wrap gap-1.5">
            <Button
              v-for="replacement in match.replacements.slice(0, MAX_SUGGESTIONS)"
              :key="replacement"
              :label="replacement"
              @click="$emit('apply', index, replacement)"
              data-test="replacement"
              severity="secondary"
              size="small"
            />
          </div>
        </li>
      </ul>
    </div>
  </div>
</template>
