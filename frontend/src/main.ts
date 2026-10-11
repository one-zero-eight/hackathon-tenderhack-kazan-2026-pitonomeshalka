import PrimeVue from 'primevue/config'
import { createApp } from 'vue'
import App from './App.vue'
import './style.css'
import { PortalPreset } from './theme'

createApp(App)
  .use(PrimeVue, {
    theme: {
      preset: PortalPreset,
      options: { darkModeSelector: '.app-dark', cssLayer: { name: 'primevue' } },
    },
  })
  .mount('#app')
