import PrimeVue from 'primevue/config'
import { mount } from '@vue/test-utils'
import type { MountingOptions } from '@vue/test-utils'
import { PortalPreset } from '../theme'

type AnyMountOptions = MountingOptions<Record<string, unknown>>

/** mount() with the PrimeVue plugin registered, mirroring main.ts setup. */
export function mountWithPrime(component: unknown, options: AnyMountOptions = {}) {
  const plugins = options.global?.plugins ?? []
  const merged = {
    ...options,
    global: {
      ...options.global,
      plugins: [
        ...plugins,
        [
          PrimeVue,
          { theme: { preset: PortalPreset, options: { darkModeSelector: '.app-dark' } } },
        ],
      ],
    },
  }
  return mount(component as never, merged as never)
}
