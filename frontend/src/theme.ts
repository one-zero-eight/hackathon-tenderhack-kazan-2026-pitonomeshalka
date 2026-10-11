import { definePreset } from '@primeuix/themes'
import Aura from '@primeuix/themes/aura'

/** Палитра «Портала поставщиков»: реестровый синий #264B82 как primary. */
export const PortalPreset = definePreset(Aura, {
  semantic: {
    primary: {
      50: '#f4f7fb',
      100: '#e7eef7',
      200: '#c9d8ea',
      300: '#a3bbda',
      400: '#47699e',
      500: '#264b82',
      600: '#1f3e6c',
      700: '#183154',
      800: '#122541',
      900: '#0c1930',
      950: '#081020',
    },
  },
})
