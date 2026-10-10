<script lang="ts" setup>
import type { Property } from '../api/types'

defineProps<{ properties: Property[] }>()
</script>

<template>
  <table class="w-full text-sm" v-if="properties.length">
    <tbody>
      <tr
        class="border-b border-ink-100 last:border-0"
        v-for="(property, index) in properties"
        :key="`${property.name}-${index}`"
      >
        <td class="w-2/5 py-2 pr-4 align-top text-ink-500">{{ property.name }}</td>
        <td class="py-2 font-medium text-ink-900">{{ property.value }}</td>
      </tr>
    </tbody>
  </table>
</template>
