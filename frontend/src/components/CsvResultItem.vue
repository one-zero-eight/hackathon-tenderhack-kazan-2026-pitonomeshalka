<script lang="ts" setup>
import Accordion from 'primevue/accordion'
import AccordionContent from 'primevue/accordioncontent'
import AccordionHeader from 'primevue/accordionheader'
import AccordionPanel from 'primevue/accordionpanel'
import ProgressSpinner from 'primevue/progressspinner'
import type { BatchItem } from '../composables/useCsvBatch'
import AnalysisResult from './AnalysisResult.vue'
import StatusChip from './ui/StatusChip.vue'

defineProps<{ item: BatchItem; index: number }>()
</script>

<template>
  <Accordion class="card-registry overflow-hidden" :multiple="true">
    <AccordionPanel :value="String(item.id)">
      <AccordionHeader>
        <span class="flex w-full min-w-0 items-center gap-3 pr-2">
          <span class="font-mono text-xs text-ink-400 tabular-nums">{{ index + 1 }}</span>
          <span class="truncate text-sm font-semibold text-ink-900">{{ item.query }}</span>
          <span class="ml-auto flex shrink-0 items-center gap-2">
            <template v-if="item.status === 'searching'">
              <ProgressSpinner style="width: 18px; height: 18px" />
              <span class="text-xs font-semibold text-primary-600">Ищу…</span>
            </template>
            <StatusChip
              v-else-if="item.status === 'done' && item.result"
              :status="item.result.status"
            />
            <span class="text-xs font-semibold text-accent-700" v-else-if="item.status === 'error'">
              Ошибка
            </span>
            <span class="text-xs text-ink-400" v-else>В очереди</span>
          </span>
        </span>
        <template #toggleicon>
          <svg class="h-4 w-4 text-ink-400" fill="none" viewBox="0 0 20 20">
            <path
              d="m6 8 4 4 4-4"
              stroke="currentColor"
              stroke-linecap="round"
              stroke-linejoin="round"
              stroke-width="1.6"
            />
          </svg>
        </template>
      </AccordionHeader>
      <AccordionContent>
        <div class="space-y-3">
          <p class="text-xs text-ink-500" v-if="item.spellFixed">
            Исправлено: «{{ item.query }}» → «{{ item.corrected }}»
          </p>
          <AnalysisResult v-if="item.status === 'done' && item.result" :result="item.result" />
          <p class="text-sm text-accent-700" v-if="item.status === 'error'">{{ item.error }}</p>
          <p class="text-sm text-ink-400" v-else-if="item.status === 'pending'">
            Ожидает очереди проверки…
          </p>
        </div>
      </AccordionContent>
    </AccordionPanel>
  </Accordion>
</template>
