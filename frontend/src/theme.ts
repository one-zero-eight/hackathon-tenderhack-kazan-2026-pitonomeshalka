import { definePreset } from '@primeuix/themes'
import Aura from '@primeuix/themes/aura'

/** Portal Postavshchikov blue as the PrimeVue primary palette. */
export const PortalPreset = definePreset(Aura, {
  semantic: {
    primary: {
      50: '{blue.50}',
      100: '{blue.100}',
      200: '{blue.200}',
      300: '{blue.300}',
      400: '{blue.400}',
      500: '{blue.500}',
      600: '#0d4cd3',
      700: '#0c3fae',
      800: '#0e3589',
      900: '#12306b',
      950: '{blue.950}',
    },
  },
})
