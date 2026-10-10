<script lang="ts" setup>
import Tag from 'primevue/tag'
import { computed } from 'vue'
import type { AnalysisStatus, CandidateStatus } from '../../api/types'

type ChipStatus = CandidateStatus | AnalysisStatus

interface ChipMeta {
  label: string
  tone: string
  severity: 'success' | 'warn' | 'danger' | 'info' | 'secondary'
}

const LABELS: Record<ChipStatus, ChipMeta> = {
  supported: { label: 'Подтверждён', tone: 'tone-success', severity: 'success' },
  uncertain: { label: 'Требует проверки', tone: 'tone-warning', severity: 'warn' },
  rejected: { label: 'Отклонён', tone: 'tone-danger', severity: 'danger' },
  ready_for_review: { label: 'Готов к проверке', tone: 'tone-primary', severity: 'info' },
  needs_clarification: { label: 'Нужны уточнения', tone: 'tone-warning', severity: 'warn' },
  retrieval_miss: { label: 'Ничего не найдено', tone: 'tone-gray', severity: 'secondary' },
  incomplete_inference: { label: 'Анализ не завершён', tone: 'tone-warning', severity: 'warn' },
  no_compatible_shortlist_candidate: {
    label: 'Нет совместимых позиций',
    tone: 'tone-danger',
    severity: 'danger',
  },
}

const props = defineProps<{ status: ChipStatus }>()

const meta = computed<ChipMeta>(
  () =>
    LABELS[props.status] ?? {
      label: props.status,
      tone: 'tone-gray',
      severity: 'secondary',
    },
)
</script>

<template>
  <span class="inline-flex" :class="meta.tone" data-test="chip">
    <Tag :severity="meta.severity" :value="meta.label" rounded />
  </span>
</template>
