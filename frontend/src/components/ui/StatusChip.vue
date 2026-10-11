<script lang="ts" setup>
import { computed } from 'vue'
import type { AnalysisStatus, CandidateStatus } from '../../api/types'

type ChipStatus = CandidateStatus | AnalysisStatus

interface ChipMeta {
  label: string
  tone: string
  icon: string
}

const LABELS: Record<ChipStatus, ChipMeta> = {
  compatible: { label: 'Подходит', tone: 'stamp-success', icon: '✓' },
  uncertain: { label: 'Требует проверки', tone: 'stamp-warning', icon: '!' },
  rejected: { label: 'Отклонён', tone: 'stamp-danger', icon: '✕' },
  ready_for_review: { label: 'Готов к проверке', tone: 'stamp-info', icon: '✓' },
  needs_clarification: { label: 'Нужны уточнения', tone: 'stamp-warning', icon: '!' },
  retrieval_miss: { label: 'Ничего не найдено', tone: 'stamp-gray', icon: '—' },
  incomplete_inference: { label: 'Анализ не завершён', tone: 'stamp-warning', icon: '!' },
  no_compatible_shortlist_candidate: {
    label: 'Нет совместимых позиций',
    tone: 'stamp-danger',
    icon: '✕',
  },
}

const props = defineProps<{ status: ChipStatus }>()

const meta = computed<ChipMeta>(
  () =>
    LABELS[props.status] ?? {
      label: props.status,
      tone: 'stamp-gray',
      icon: '—',
    },
)
</script>

<template>
  <span :class="['stamp', meta.tone]" data-test="chip">
    <span class="stamp-icon" aria-hidden="true">{{ meta.icon }}</span>
    {{ meta.label }}
  </span>
</template>
