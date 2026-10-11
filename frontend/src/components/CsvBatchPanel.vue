<script lang="ts" setup>
import Button from 'primevue/button'
import ProgressBar from 'primevue/progressbar'
import { computed, ref } from 'vue'
import type { AnalysisResponse } from '../api/types'
import { useCsvBatch, type BatchRow } from '../composables/useCsvBatch'
import { guessQueryColumn, parseTable, rowToQuery, type CsvTable } from '../lib/csv'
import { api, spellCorrect } from '../services'
import CsvResultItem from './CsvResultItem.vue'

const props = withDefaults(
  defineProps<{
    analyze?: (text: string, signal: AbortSignal) => Promise<AnalysisResponse>
    correct?: (text: string) => Promise<string | null>
  }>(),
  {
    analyze: undefined,
    correct: undefined,
  },
)

const ltFailed = ref(false)
const analyzeFn =
  props.analyze ?? ((text: string, signal: AbortSignal) => api.analyze({ text }, signal))
const correctFn =
  props.correct ??
  (async (text: string) => {
    try {
      return await spellCorrect(text)
    } catch {
      ltFailed.value = true
      return null
    }
  })

const batch = useCsvBatch(
  { analyze: analyzeFn, correct: correctFn },
  { retryCount: 1, retryDelayMs: 1500 },
)

const fileName = ref('')
const table = ref<CsvTable | null>(null)
const queryColumn = ref(0)
const dragging = ref(false)
const fileError = ref('')
const fileInput = ref<HTMLInputElement | null>(null)

const DROPZONE =
  'flex cursor-pointer flex-col items-center gap-3 border-2 border-dashed ' +
  'px-6 py-10 text-center transition'
const SELECT_CLASS = 'field-base px-3 py-2 text-sm'

const rowsCount = computed(() => table.value?.rows.length ?? 0)
const dropzoneTone = computed(() =>
  dragging.value ? 'border-primary-500 bg-primary-50' : 'border-ink-300 bg-white',
)
const progressPercent = computed(() =>
  batch.progress.value.total === 0
    ? 0
    : Math.round((batch.progress.value.done / batch.progress.value.total) * 100),
)

async function onFile(file: File | null | undefined) {
  if (!file) return
  fileError.value = ''
  let parsed: CsvTable
  try {
    parsed = parseTable(await file.text())
  } catch {
    fileError.value = 'Не удалось прочитать файл'
    return
  }
  if (parsed.rows.length === 0) {
    table.value = null
    fileName.value = ''
    fileError.value = 'В файле нет строк данных — нужна шапка и хотя бы одна строка'
    return
  }
  fileName.value = file.name
  table.value = parsed
  queryColumn.value = guessQueryColumn(parsed.headers, parsed.rows)
}

function onInputChange(event: Event) {
  const input = event.target as HTMLInputElement
  void onFile(input.files?.[0])
}

function onDrop(event: DragEvent) {
  dragging.value = false
  void onFile(event.dataTransfer?.files?.[0])
}

function pickFile() {
  fileInput.value?.click()
}

function startBatch() {
  if (!table.value) return
  const rows: BatchRow[] = table.value.rows
    .map((row, index) => ({ id: index, query: rowToQuery(row, queryColumn.value) }))
    .filter((row) => row.query.length > 0)
  if (rows.length === 0) {
    fileError.value = 'В выбранном столбце нет ни одной непустой ячейки — выберите другой столбец'
    return
  }
  fileError.value = ''
  ltFailed.value = false
  batch.start(rows)
}

function reset() {
  table.value = null
  fileName.value = ''
  fileError.value = ''
  batch.items.value = []
}
</script>

<template>
  <section class="space-y-4">
    <div class="card-registry animate-rise-in space-y-4 p-6" v-if="batch.items.value.length === 0">
      <div class="border-b border-ink-200 pb-3">
        <h2 class="eyebrow">Пакетная проверка из CSV</h2>
        <p class="mt-1 text-sm text-ink-500">
          Загрузите таблицу: одна строка — одно описание товара. Результаты появляются по мере
          проверки.
        </p>
      </div>

      <div
        :class="[DROPZONE, dropzoneTone]"
        @click="pickFile"
        @dragleave="dragging = false"
        @dragover.prevent="dragging = true"
        @drop.prevent="onDrop"
      >
        <input
          class="hidden"
          @change="onInputChange"
          accept=".csv,text/csv"
          data-test="file-input"
          ref="fileInput"
          type="file"
        />
        <svg class="h-10 w-10 text-primary-500" fill="none" viewBox="0 0 24 24">
          <path
            d="M12 16V4m0 0L8 8m4-4 4 4M4 16v2a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-2"
            stroke="currentColor"
            stroke-linecap="round"
            stroke-linejoin="round"
            stroke-width="1.8"
          />
        </svg>
        <p class="text-[15px] font-semibold text-ink-900">
          Перетащите CSV-файл сюда или выберите на диске
        </p>
        <p class="text-xs text-ink-500">Поддерживаются разделители «;», «,» и табуляция</p>
        <Button @click.stop="pickFile" label="Выбрать файл" severity="secondary" size="small" />
      </div>

      <p class="text-sm font-semibold text-accent-700" v-if="fileError" data-test="file-error">
        {{ fileError }}
      </p>

      <div class="card-registry space-y-3 bg-primary-50 p-4" v-if="table">
        <p class="text-sm font-semibold text-ink-900">{{ fileName }} — строк: {{ rowsCount }}</p>
        <label class="flex items-center gap-2 text-sm text-ink-500">
          Столбец с описанием
          <select v-model.number="queryColumn" :class="SELECT_CLASS" data-test="column">
            <option v-for="(header, index) in table.headers" :key="index" :value="index">
              {{ header || `Столбец ${index + 1}` }}
            </option>
          </select>
        </label>
        <div class="overflow-x-auto bg-white">
          <table class="w-full text-xs">
            <tbody>
              <tr
                class="border-b border-ink-200 last:border-0"
                v-for="(row, index) in table.rows.slice(0, 2)"
                :key="index"
              >
                <td
                  class="max-w-64 truncate py-1.5 pr-3 font-mono text-ink-700"
                  v-for="(cell, cellIndex) in row"
                  :key="cellIndex"
                >
                  {{ cell || '—' }}
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <Button
          :disabled="rowsCount === 0"
          @click="startBatch"
          data-test="start"
          label="Проверить строки"
        />
      </div>
    </div>

    <template v-else>
      <div class="card-registry animate-rise-in space-y-3 p-6">
        <div class="flex flex-wrap items-center gap-3 border-b border-ink-200 pb-3">
          <h2 class="eyebrow">
            Проверено {{ batch.progress.value.done }} из {{ batch.progress.value.total }}
          </h2>
          <span
            class="text-xs font-semibold text-warning-700"
            v-if="ltFailed"
            data-test="lt-warning"
          >
            Сервис орфографии недоступен — строки отправлены как есть
          </span>
          <Button
            class="ml-auto"
            v-if="batch.running.value"
            @click="batch.cancel()"
            data-test="cancel"
            label="Остановить"
            severity="danger"
            size="small"
          />
          <Button
            class="ml-auto"
            v-else
            @click="reset"
            data-test="reset"
            label="Новый файл"
            severity="secondary"
            size="small"
          />
        </div>
        <ProgressBar :value="progressPercent" />
      </div>
      <div class="space-y-2">
        <CsvResultItem
          v-for="(item, index) in batch.items.value"
          :index="index"
          :item="item"
          :key="item.id"
        />
      </div>
    </template>
  </section>
</template>
