<script lang="ts" setup>
import { computed, onMounted, onUnmounted, ref, withDefaults } from 'vue'
import type { HealthPayload } from '../api/types'
import { api } from '../services'

const props = withDefaults(
  defineProps<{
    client?: { health: () => Promise<HealthPayload> }
  }>(),
  {
    client: undefined,
  },
)

const POLL_MS = 30000
const healthClient = props.client ?? api
const state = ref<'loading' | 'ok' | 'busy' | 'down'>('loading')
let timer: ReturnType<typeof setInterval> | undefined

async function poll() {
  try {
    const payload = await healthClient.health()
    state.value = payload.model_busy ? 'busy' : 'ok'
  } catch {
    state.value = 'down'
  }
}

onMounted(() => {
  void poll()
  timer = setInterval(() => void poll(), POLL_MS)
})

onUnmounted(() => clearInterval(timer))

const label = computed(
  () =>
    ({
      loading: 'Проверяем…',
      ok: 'Сервис доступен',
      busy: 'Модель занята',
      down: 'Нет связи',
    })[state.value],
)

const TONES = {
  loading: 'text-ink-400',
  ok: 'text-success-700',
  busy: 'text-warning-700',
  down: 'text-danger-700',
} as const

const DOTS = {
  loading: 'bg-ink-300',
  ok: 'bg-success-500',
  busy: 'bg-warning-500',
  down: 'bg-danger-500',
} as const

const BADGE =
  'inline-flex items-center gap-2 rounded-full border border-ink-200 bg-white ' +
  'px-3 py-1.5 text-xs font-medium'
</script>

<template>
  <span :class="[BADGE, TONES[state]]" data-test="health">
    <span class="h-2 w-2 rounded-full" :class="DOTS[state]" />
    {{ label }}
  </span>
</template>
