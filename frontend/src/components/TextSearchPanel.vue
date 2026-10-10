<script lang="ts" setup>
import Button from 'primevue/button'
import { computed, ref, watch } from 'vue'
import type { AnalysisScope } from '../api/types'
import { useSpellcheck, type SpellcheckClient } from '../composables/useSpellcheck'
import { useTextSearch, type TextSearchClient } from '../composables/useTextSearch'
import { api, lt } from '../services'
import AnalysisResult from './AnalysisResult.vue'
import CorrectionsPanel from './CorrectionsPanel.vue'
import RobotSearching from './RobotSearching.vue'

const props = withDefaults(
  defineProps<{
    spellcheck?: SpellcheckClient
    search?: TextSearchClient
  }>(),
  {
    spellcheck: undefined,
    search: undefined,
  },
)

const MAX_LENGTH = 10000

const SELECT_CLASS =
  'rounded-lg border border-ink-300 bg-white px-3 py-2 text-sm focus:border-primary-500'
const TEXTAREA_CLASS =
  'w-full resize-y rounded-xl border border-ink-300 bg-white px-4 py-3 text-[15px] ' +
  'leading-relaxed transition placeholder:text-ink-400 focus:border-primary-500 ' +
  'focus:ring-4 focus:ring-primary-100'
const ERROR_CARD =
  'space-y-2 rounded-2xl border border-danger-200 bg-danger-50 p-4 text-sm text-danger-700'

const text = ref('')
const scope = ref<AnalysisScope>('all')
const spell = useSpellcheck(props.spellcheck ?? lt, { debounceMs: 300 })
const searchState = useTextSearch(props.search ?? api)
const { matches, checkedText, checking, error: spellError } = spell
const { phase: searchPhase, result: searchResult, error: searchError } = searchState

watch(text, (value) => spell.scheduleCheck(value))

const correctionsVisible = computed(
  () => checkedText.value === text.value && matches.value.length > 0,
)

function applyAll() {
  text.value = spell.applyAll()
}

function applyOne(index: number, replacement: string) {
  text.value = spell.applyOne(index, replacement)
}

function run() {
  void searchState.search(text.value, scope.value)
}
</script>

<template>
  <section class="space-y-4">
    <div class="space-y-4 rounded-2xl border border-ink-200 bg-white p-5 shadow-sm">
      <div class="flex flex-wrap items-baseline gap-3">
        <h2 class="text-base font-semibold text-ink-900">Описание товара</h2>
        <span class="ml-auto text-xs text-ink-400 tabular-nums">
          {{ text.length }} / {{ MAX_LENGTH }}
        </span>
      </div>
      <textarea
        id="query"
        v-model="text"
        :class="TEXTAREA_CLASS"
        :maxlength="MAX_LENGTH"
        data-test="query"
        placeholder="Например: аккумуляторная дрель 18 В с реверсом и двумя батареями"
        rows="4"
      ></textarea>
      <div class="flex flex-wrap items-center gap-3">
        <label class="flex items-center gap-2 text-sm text-ink-500" for="scope">
          Раздел
          <select id="scope" v-model="scope" :class="SELECT_CLASS" data-test="scope">
            <option disabled value="all">Все разделы</option>
            <option value="clothing">Одежда</option>
            <option value="tools">Инструменты</option>
            <option value="furniture">Мебель</option>
          </select>
        </label>
        <Button
          class="ml-auto"
          :disabled="!text.trim() || searchPhase === 'searching'"
          :loading="searchPhase === 'searching'"
          @click="run"
          data-test="search"
          label="Найти в КТРУ"
          size="large"
        />
      </div>
      <p class="text-sm text-ink-500" v-if="checking">Проверяем орфографию…</p>
      <p class="text-sm text-warning-700" v-else-if="spellError" data-test="lt-warning">
        Проверка орфографии недоступна — отправим текст как есть
      </p>
    </div>

    <CorrectionsPanel
      v-if="correctionsVisible"
      :matches="matches"
      @apply="applyOne"
      @apply-all="applyAll"
    />

    <RobotSearching v-if="searchPhase === 'searching'" />

    <div v-else-if="searchPhase === 'error'" :class="ERROR_CARD" data-test="error">
      <p class="font-medium">Не удалось выполнить анализ</p>
      <p>{{ searchError }}</p>
      <Button @click="run" label="Повторить" severity="secondary" size="small" />
    </div>

    <AnalysisResult v-else-if="searchResult" :result="searchResult" />
  </section>
</template>
