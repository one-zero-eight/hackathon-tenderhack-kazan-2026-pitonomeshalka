<script lang="ts" setup>
import Button from 'primevue/button'

const props = defineProps<{
  queries: string[]
}>()

const emit = defineEmits<{
  (e: 'select', query: string): void
}>()

const BUTTON_MAX_CHARS = 50
const TOOLTIP_MAX_CHARS = 150

function truncate(text: string, max: number): string {
  return text.length > max ? text.slice(0, max) + '…' : text
}

function displayText(query: string): string {
  return truncate(query, BUTTON_MAX_CHARS)
}

function tooltipText(query: string): string {
  if (query.length <= BUTTON_MAX_CHARS) return ''
  return truncate(query, TOOLTIP_MAX_CHARS)
}
</script>

<template>
  <div class="flex flex-wrap items-center gap-2" v-if="props.queries.length > 0">
    <span class="mr-1 text-xs text-ink-500">Ранее:</span>
    <Button
      class="hist-chip"
      v-for="(query, i) in props.queries"
      v-tooltip.top="tooltipText(query) || undefined"
      :key="`${query}-${i}`"
      :label="displayText(query)"
      @click="emit('select', query)"
      size="small"
    />
  </div>
</template>
