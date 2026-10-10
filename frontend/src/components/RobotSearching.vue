<script lang="ts" setup>
import { onMounted, onUnmounted, ref, withDefaults } from 'vue'

const props = withDefaults(defineProps<{ phrases?: string[] }>(), {
  phrases: () => [
    'Листаю каталог КТРУ в поисках нужной страницы…',
    'Сверяю характеристики с шаблоном позиции…',
    'Спрашиваю у нейросети, что вы имели в виду…',
    'Проверяю единицы измерения и допустимые значения…',
    'Перебираю похожие позиции из закупок…',
    'Почти готово: навожу порядок в кодах…',
  ],
})

const PHRASE_MS = 2200
const index = ref(0)
let timer: ReturnType<typeof setInterval> | undefined

onMounted(() => {
  timer = setInterval(() => {
    index.value = (index.value + 1) % props.phrases.length
  }, PHRASE_MS)
})

onUnmounted(() => clearInterval(timer))

const CHIP_BASE = 'robot-chip absolute rounded-full border border-primary-200 bg-white'
const CHIP_TEXT = 'px-2.5 py-1 text-[11px] font-medium text-primary-700'
</script>

<template>
  <div
    class="flex flex-col items-center gap-5 py-8 select-none"
    aria-live="polite"
    data-test="robot"
    role="status"
  >
    <div class="relative h-56 w-56">
      <div class="robot-ring absolute inset-4 rounded-full border-2 border-primary-200"></div>
      <div class="robot-ring absolute inset-10 rounded-full border border-primary-100"></div>
      <span class="top-4 left-0" :class="[CHIP_BASE, CHIP_TEXT]"> 26.02.10 </span>
      <span class="top-10 right-0" :class="[CHIP_BASE, CHIP_TEXT]" style="animation-delay: -1.1s">
        КТРУ
      </span>
      <span class="bottom-14 left-2" :class="[CHIP_BASE, CHIP_TEXT]" style="animation-delay: -2.2s">
        21.03.14
      </span>
      <svg class="robot-float relative h-full w-full" viewBox="0 0 200 200">
        <line
          stroke="#0d4cd3"
          stroke-linecap="round"
          stroke-width="4"
          x1="100"
          x2="100"
          y1="34"
          y2="52"
        />
        <circle class="robot-antenna" cx="100" cy="27" fill="#f04438" r="7" />
        <rect
          fill="#ffffff"
          height="56"
          rx="18"
          stroke="#c5d8ff"
          stroke-width="3"
          width="84"
          x="58"
          y="50"
        />
        <rect fill="#0e2a66" height="36" rx="10" width="64" x="68" y="60" />
        <g class="robot-eyes">
          <circle cx="88" cy="77" fill="#7dd3fc" r="6" />
          <circle cx="112" cy="77" fill="#7dd3fc" r="6" />
        </g>
        <path
          d="M92 88 Q100 95 108 88"
          fill="none"
          stroke="#7dd3fc"
          stroke-linecap="round"
          stroke-width="3"
        />
        <rect
          fill="#ffffff"
          height="52"
          rx="16"
          stroke="#c5d8ff"
          stroke-width="3"
          width="72"
          x="64"
          y="112"
        />
        <circle cx="100" cy="134" fill="#dfe9ff" r="9" />
        <path
          d="M96 134 L99 137 L105 130"
          fill="none"
          stroke="#0d4cd3"
          stroke-linecap="round"
          stroke-linejoin="round"
          stroke-width="2.5"
        />
        <rect fill="#eef4ff" height="7" rx="3.5" width="44" x="78" y="150" />
        <rect class="robot-arm-l" fill="#dfe9ff" height="34" rx="9" width="18" x="40" y="120" />
        <rect class="robot-arm-r" fill="#dfe9ff" height="34" rx="9" width="18" x="142" y="120" />
        <rect fill="#dfe9ff" height="18" rx="8" width="16" x="80" y="168" />
        <rect fill="#dfe9ff" height="18" rx="8" width="16" x="104" y="168" />
      </svg>
    </div>
    <p class="max-w-md text-center text-sm font-medium text-ink-700" data-test="phrase">
      {{ phrases[index] }}
    </p>
  </div>
</template>

<style scoped>
.robot-float {
  animation: robot-float 3s ease-in-out infinite;
}

.robot-eyes {
  animation: robot-scan 2.6s ease-in-out infinite;
}

.robot-antenna {
  animation: robot-blink 1.4s ease-in-out infinite;
}

.robot-ring {
  animation: robot-ring 2.4s linear infinite;
}

.robot-chip {
  animation: robot-rise 3.2s linear infinite;
}

.robot-arm-l {
  transform-origin: 58px 126px;
  animation: robot-wave 2.2s ease-in-out infinite;
}

.robot-arm-r {
  transform-origin: 142px 126px;
  animation: robot-wave 2.2s ease-in-out infinite reverse;
}

@keyframes robot-float {
  0%,
  100% {
    transform: translateY(0);
  }

  50% {
    transform: translateY(-10px);
  }
}

@keyframes robot-scan {
  0%,
  100% {
    transform: translateX(-4px);
  }

  50% {
    transform: translateX(4px);
  }
}

@keyframes robot-blink {
  0%,
  100% {
    opacity: 1;
  }

  50% {
    opacity: 0.25;
  }
}

@keyframes robot-ring {
  0% {
    transform: scale(0.7);
    opacity: 0.5;
  }

  100% {
    transform: scale(1.15);
    opacity: 0;
  }
}

@keyframes robot-rise {
  0% {
    transform: translateY(6px);
    opacity: 0;
  }

  25% {
    opacity: 1;
  }

  100% {
    transform: translateY(-46px);
    opacity: 0;
  }
}

@keyframes robot-wave {
  0%,
  100% {
    transform: rotate(0deg);
  }

  50% {
    transform: rotate(-12deg);
  }
}

@media (prefers-reduced-motion: reduce) {
  .robot-float,
  .robot-eyes,
  .robot-antenna,
  .robot-ring,
  .robot-chip,
  .robot-arm-l,
  .robot-arm-r {
    animation: none;
  }
}
</style>
