<script lang="ts" setup>
import { ref } from 'vue'
import CsvBatchPanel from './components/CsvBatchPanel.vue'
import HealthBadge from './components/HealthBadge.vue'
import TextSearchPanel from './components/TextSearchPanel.vue'

type Tab = 'text' | 'csv'

const TABS: ReadonlyArray<{ id: Tab; label: string }> = [
  { id: 'text', label: 'Текстовый поиск' },
  { id: 'csv', label: 'CSV-загрузка' },
]

const tab = ref<Tab>('text')
</script>

<template>
  <div class="flex min-h-screen flex-col">
    <header class="border-b border-ink-200 bg-white">
      <div class="mx-auto flex max-w-5xl flex-wrap items-center gap-3 px-6 pt-5">
        <span
          class="grid h-11 w-11 place-items-center rounded-2xl bg-primary-600 text-white shadow-sm"
        >
          <svg class="h-6 w-6" fill="none" viewBox="0 0 24 24">
            <rect
              height="11"
              rx="4"
              stroke="currentColor"
              stroke-width="1.8"
              width="14"
              x="5"
              y="8"
            />
            <circle cx="10" cy="13" fill="currentColor" r="1.4" />
            <circle cx="14" cy="13" fill="currentColor" r="1.4" />
            <path d="M12 8V4.5" stroke="currentColor" stroke-linecap="round" stroke-width="1.8" />
            <circle cx="12" cy="3.5" fill="currentColor" r="1.3" />
          </svg>
        </span>
        <div>
          <h1 class="text-lg font-semibold text-ink-900">КТРУ Ассистент</h1>
          <p class="text-sm text-ink-500">Подбор кода КТРУ по описанию товара</p>
        </div>
        <div class="ml-auto">
          <HealthBadge />
        </div>
      </div>
      <nav class="mx-auto mt-4 flex max-w-5xl gap-1 px-6" data-test="tabs">
        <button
          class="rounded-t-xl border-b-2 px-4 py-2.5 text-sm font-medium transition"
          v-for="item in TABS"
          :class="
            tab === item.id
              ? 'border-primary-600 text-primary-700'
              : 'border-transparent text-ink-500 hover:text-ink-900'
          "
          :key="item.id"
          @click="tab = item.id"
          type="button"
        >
          {{ item.label }}
        </button>
      </nav>
    </header>

    <main class="mx-auto w-full max-w-5xl flex-1 space-y-6 px-6 py-8">
      <TextSearchPanel v-show="tab === 'text'" />
      <CsvBatchPanel v-show="tab === 'csv'" />
    </main>

    <footer class="mx-auto w-full max-w-5xl px-6 pb-8 text-xs text-ink-400">
      Коды КТРУ носят предварительный характер и требуют финальной проверки специалистом. Орфография
      проверяется сервером LanguageTool, анализ выполняется моделью Nimble.
    </footer>
  </div>
</template>
