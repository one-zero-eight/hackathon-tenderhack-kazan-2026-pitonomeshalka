<script lang="ts" setup>
import type { Property } from '../api/types'

defineProps<{ properties: Property[] }>()
</script>

<template>
  <table class="w-full text-sm" v-if="properties.length">
    <tbody>
      <tr
        class="border-b border-ink-200 last:border-0"
        v-for="(property, index) in properties"
        :key="`${property.name}-${index}`"
      >
        <td class="w-2/5 py-2.5 pr-4 align-top text-[13px] text-ink-500">{{ property.name }}</td>
        <td class="py-2.5 font-semibold text-ink-900">{{ property.value }}</td>
      </tr>
    </tbody>
  </table>
</template>
