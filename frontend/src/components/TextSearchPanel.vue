<script lang="ts" setup>
import Button from 'primevue/button'
import { computed, onMounted, ref, watch } from 'vue'
import { useSpellcheck, type SpellcheckClient } from '../composables/useSpellcheck'
import { useTextSearch, type TextSearchClient } from '../composables/useTextSearch'
import { getSessionId } from '../lib/sessionId'
import { api, lt } from '../services'
import AnalysisResult from './AnalysisResult.vue'
import CorrectionsPanel from './CorrectionsPanel.vue'
import RobotSearching from './RobotSearching.vue'
import SearchHistory from './SearchHistory.vue'

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

/** Mirrors the backend .env default (PIPELINE_TOP_K) and its schema cap (le=32). */
const DEFAULT_TOP_K = 8
const EXPAND_STEP = 4
const MAX_TOP_K = 32
const TEXTAREA_CLASS = 'field-base w-full resize-y px-4 py-3 text-[15px] leading-relaxed transition'
const ERROR_CARD =
  'card-registry space-y-2 border-accent-200 bg-accent-50 p-4 text-sm text-accent-700'

const text = ref('')
const topK = ref(DEFAULT_TOP_K)
const spell = useSpellcheck(props.spellcheck ?? lt, { debounceMs: 300 })
const searchState = useTextSearch(props.search ?? api)
const { matches, checkedText, checking, error: spellError } = spell
const { phase: searchPhase, result: searchResult, error: searchError } = searchState

watch(text, (value) => spell.scheduleCheck(value))

const sessionId = getSessionId()
const historyQueries = ref<string[]>([])

async function loadHistory() {
  try {
    const response = await api.getHistory(sessionId)
    historyQueries.value = response.queries
  } catch {
    historyQueries.value = []
  }
}

onMounted(() => {
  void loadHistory()
})

watch(searchPhase, async (phase) => {
  if (phase !== 'done' && phase !== 'error') return
  const queryText = text.value.trim()
  if (!queryText) return
  try {
    await api.addHistory(sessionId, queryText)
    await loadHistory()
  } catch {
    // history is best-effort
  }
})

function selectFromHistory(query: string) {
  text.value = query
}

const correctionsVisible = computed(
  () => checkedText.value === text.value && matches.value.length > 0,
)

function applyAll() {
  text.value = spell.applyAll()
}

function applyOne(index: number, replacement: string) {
  text.value = spell.applyOne(index, replacement)
}

function run(expandedTopK?: number) {
  void searchState.search(text.value, 'all', expandedTopK)
}

function choose(optionId: string) {
  void searchState.clarify(optionId)
}

/** Repeats the search with more candidates; the backend accepts at most 32. */
function expand() {
  topK.value = Math.min(topK.value + EXPAND_STEP, MAX_TOP_K)
  run(topK.value)
}
</script>

<template>
  <section class="space-y-4">
    <div class="card-registry animate-rise-in space-y-4 p-6">
      <div class="flex flex-wrap items-baseline gap-3 border-b border-ink-200 pb-3">
        <h2 class="eyebrow">Описание товара</h2>
        <span class="ml-auto font-mono text-xs text-ink-500 tabular-nums">
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
        <SearchHistory :queries="historyQueries" @select="selectFromHistory" />

        <Button
          class="btn-cta ml-auto"
          :disabled="!text.trim() || searchPhase === 'searching'"
          :loading="searchPhase === 'searching'"
          @click="run()"
          data-test="search"
          size="large"
        >
          Найти в КТРУ <span aria-hidden="true">→</span>
        </Button>
      </div>
      <SearchHistory :queries="historyQueries" @select="selectFromHistory" />
      <p class="text-[13px] text-ink-500" v-if="checking">Проверяем орфографию…</p>
      <p class="text-[13px] text-warning-700" v-else-if="spellError" data-test="lt-warning">
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
      <Button @click="run()" label="Повторить" severity="secondary" size="small" />
    </div>

    <AnalysisResult
      v-else-if="searchResult"
      :result="searchResult"
      @expand="expand"
      @select="choose"
    />
  </section>
</template>
