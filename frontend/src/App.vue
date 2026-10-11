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

const TAB_CLASS =
  '-mb-px border-b-[3px] px-1 pt-1 pb-3 text-[13px] font-bold tracking-[0.06em] ' +
  'uppercase transition'
</script>

<template>
  <div class="flex min-h-screen flex-col">
    <div class="h-1 bg-primary-600"></div>
    <header class="border-b border-ink-200 bg-white shadow-card">
      <div class="mx-auto flex max-w-5xl flex-wrap items-center gap-3 px-6 pt-5">
        <span
          class="grid h-11 w-11 place-items-center bg-primary-600 shadow-card"
          aria-hidden="true"
        >
          <svg class="h-6 w-6 text-white" fill="none" viewBox="0 0 24 24">
            <rect
              height="11"
              rx="2"
              stroke="currentColor"
              stroke-width="1.8"
              width="14"
              x="5"
              y="8"
            />
            <circle cx="10" cy="13" fill="currentColor" r="1.4" />
            <circle cx="14" cy="13" fill="currentColor" r="1.4" />
            <path d="M12 8V4.5" stroke="currentColor" stroke-linecap="round" stroke-width="1.8" />
            <circle cx="12" cy="3.5" fill="#db2b21" r="1.6" />
          </svg>
        </span>
        <div>
          <h1 class="text-xl font-bold text-ink-900">КТРУ Ассистент</h1>
          <p class="text-[13px] text-ink-500">Подбор кода КТРУ по описанию товара</p>
        </div>
        <div class="ml-auto">
          <HealthBadge />
        </div>
      </div>
      <nav class="mx-auto mt-4 flex max-w-5xl gap-6 px-6" data-test="tabs">
        <button
          v-for="item in TABS"
          :class="[
            TAB_CLASS,
            tab === item.id
              ? 'border-primary-600 text-primary-700'
              : 'border-transparent text-ink-500 hover:text-ink-900',
          ]"
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
  </div>
</template>
