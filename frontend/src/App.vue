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

const TAB_CLASS = 'tab-folder'
const TAB_ACTIVE = 'is-active'
</script>

<template>
  <div class="flex min-h-screen flex-col">
    <header class="border-b border-ink-200 bg-white">
      <div class="mx-auto max-w-5xl px-6">
        <div class="flex items-end pt-6">
          <div>
            <h1 class="flex items-baseline">
              <span class="text-[27px] font-extrabold tracking-[-0.015em] text-primary-600">
                КТРУ
              </span>
              <span
                class="mx-[9px] mb-[5px] h-[7px] w-[7px] bg-accent-500"
                aria-hidden="true"
              ></span>
              <span class="text-[27px] font-semibold tracking-[-0.015em] text-ink-900">
                Ассистент
              </span>
            </h1>
            <p class="mt-1 text-[13px] text-ink-500">Подбор кода КТРУ по описанию товара</p>
          </div>
          <div class="ml-auto pb-1">
            <HealthBadge />
          </div>
        </div>
        <nav class="mt-5 -mb-px flex gap-2" data-test="tabs">
          <button
            v-for="item in TABS"
            :class="[TAB_CLASS, tab === item.id ? TAB_ACTIVE : '']"
            :key="item.id"
            @click="tab = item.id"
            type="button"
          >
            {{ item.label }}
          </button>
        </nav>
      </div>
    </header>

    <main class="mx-auto w-full max-w-5xl flex-1 space-y-6 px-6 py-8">
      <TextSearchPanel v-show="tab === 'text'" />
      <CsvBatchPanel v-show="tab === 'csv'" />
    </main>
  </div>
</template>
