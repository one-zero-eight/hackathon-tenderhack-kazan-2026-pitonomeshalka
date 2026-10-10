<script lang="ts" setup>
import Button from 'primevue/button'
import type { SpellMatch } from '../lib/corrections'

defineProps<{ matches: SpellMatch[] }>()

defineEmits<{
  apply: [index: number, replacement: string]
  applyAll: []
}>()

const MAX_SUGGESTIONS = 3
</script>

<template>
  <div
    class="space-y-3 rounded-2xl border border-warning-200 bg-warning-50 p-4"
    v-if="matches.length"
    data-test="panel"
  >
    <div class="flex items-center gap-3">
      <p class="text-sm font-medium text-warning-700">
        Похоже, есть опечатки — проверьте перед поиском
      </p>
      <Button
        class="ml-auto"
        @click="$emit('applyAll')"
        data-test="apply-all"
        label="Исправить всё"
        severity="secondary"
        size="small"
      />
    </div>
    <ul class="space-y-2">
      <li
        class="text-sm"
        v-for="(match, index) in matches"
        :key="`${match.ruleId}-${match.offset}`"
      >
        <span class="font-medium text-ink-900">«{{ match.errorText }}»</span>
        <span class="text-ink-500"> — {{ match.shortMessage || match.message }}</span>
        <div class="mt-1 flex flex-wrap gap-1.5">
          <Button
            v-for="replacement in match.replacements.slice(0, MAX_SUGGESTIONS)"
            :key="replacement"
            :label="replacement"
            @click="$emit('apply', index, replacement)"
            data-test="replacement"
            severity="secondary"
            size="small"
          />
        </div>
      </li>
    </ul>
  </div>
</template>
