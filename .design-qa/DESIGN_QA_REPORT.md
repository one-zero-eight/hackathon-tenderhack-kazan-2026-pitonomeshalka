# Design QA Verdict: FAIL

Дата: 2026-10-11. Ревью всех компонентов «КТРУ Ассистент», фокус — кнопки и мелкие составляющие.
Проверялось: dev (127.0.0.1:5173) и prod-build (`vite build` + preview, 4173) — поведение идентично.

## Summary

Интуиция «выглядит ужато» подтверждается измерениями и имеет одну конкретную техническую причину:
после сборки Tailwind v4 порядок cascade-слоёв не соответствует заявленному в `style.css:1`, и
префлайт-ресет слоя `base` (`* { padding: 0; background: transparent }`) перебивает стили
PrimeVue из слоя `primevue`. Как следствие — все кнопки PrimeVue теряют вертикальные отступы
(высота 22–24px вместо 32–46px), а статус-чипы `.p-tag` теряют заливки и цвет текста
(рендерятся чёрным текстом без фона). Статусы «Подходит» / «Отклонён» визуально неотличимы,
кнопка «Остановить» выглядит как ссылка-текст. Кастомный слой `components` (`.btn-cta`,
`.field-base`, `.card-registry`) при этом работает — сломано именно то, что отдано на дефолты PrimeVue.

## Evidence Reviewed

- Design contract: токены «Портал поставщиков» в `frontend/src/style.css` (@theme), скин PrimeVue в `frontend/src/theme.ts`; Figma-борд — canvas, программно недоступен (см. memory), источник истины — живой zakupki.mos.ru.
- Rendered implementation: Playwright, viewport 1440×900, computed styles + геометрия всех мелких компонентов; скриншоты в `.design-qa/actual/`.
- Состояния сняты: initial, с текстом + панель орфографии (LT на 8010), error-карточка поиска, CSV-таб, prod-build.
- Диагностика правил: у `.btn-cta` конкурируют `* { padding: 0 }` (layer **base**) и `.p-button { padding: var(--p-button-padding-y) … }` (layer **primevue**); вычисленный паддинг — `0px`, т.е. `base` фактически стоит позже `primevue` в каскаде. Токены `--p-button-padding-y: 0.5rem` при этом определены — PrimeVue настроен корректно, проигрывает именно порядок слоёв.

## Blockers

### B1. Все PrimeVue-кнопки схлопнуты по высоте (22–24px)
- Severity: blocker
- Evidence: `.design-qa/actual/01..05`; measured: CTA «Найти в КТРУ» 139×22, pad `0px 24px`; «Исправить всё» (small) 102×24, pad `0px`; кнопки-замены опечаток 113×22; «Повторить» 76×22; «Выбрать файл» 100×24.
- Expected: CTA ≥44px, обычные 40px, small 28–32px (WCAG 2.5.5 target size; модификаторы `size="large"/"small"` PrimeVue обязаны менять размер — сейчас не меняют).
- Impact: главный CTA и вторичные действия выглядят сплющенными («ужато»), зона клика меньше минимальной, hover-механика едва читается.
- Fix: закрепить паддинги/высоты кнопок в собственном скине (`@layer components`, он в фактическом порядке позже `base` — проверено: `.btn-cta` bg работает), либо восстановить порядок слоёв после сборки. Не полагаться на дефолты PrimeVue.

### B2. Статус-чипы `.p-tag` без заливок — статусы неотличимы
- Severity: blocker
- Evidence: сэмплы `p-tag-success/warn/danger/info/secondary`: у всех `background: rgba(0,0,0,0)`, `color: rgb(26,26,26)`, высота 19px, pad 0. Severity-цвета PrimeVue убиты тем же ресетом (`background: transparent` из base).
- Expected: мягкие заливки из токенов кита (success-50/200/700 и т.д.), высота 22–24px.
- Impact: ключевой смысловой элемент результата (Подходит/Отклонён/Требует проверки) не читается; «чёрный текст на пустоте» выглядит случайным.
- Fix: с `.p-tag` severity в components-слое; одновременно удалить мёртвый `tone-*` из `StatusChip.vue:15-24` (классов нет в CSS).

### B3. Danger-кнопка «Остановить» рендерится прозрачным текстом
- Severity: blocker
- Evidence: сэмпл `p-button-danger`: bg transparent, border 0, высота 22px (`CsvBatchPanel.vue:217-225`).
- Impact: критичное действие прерывания пакетной проверки выглядит как обычный текст; кликают мимо.
- Fix: явный скин danger (заливка accent-500 или контур accent-500) в components-слое.

## Major Issues

### M1. Нет вертикального ритма контролов
- select 39px, textarea 124px, CTA 22px, вторичные 22–24px, тумблер 28px. Высоты не согласованы ни с сеткой 4px, ни между собой.
- Fix: линейка высот 44/40/32 (large/normal/small) для всех контролов.

### M2. История поиска: дрейф от кита
- `SearchHistory.vue:46-63`: `opacity: .55` (контраст ниже порога), hover-фон `--p-surface-200` — токен PrimeVue, не кита; radius `9999px` (pill) против 6px у `.chip`; собственный `<style scoped>` в обход общего слоя.
- Fix: чипы истории на токенах кита (primary-50/primary-700, radius 6–8px), без opacity.

### M3. Мёртвый код тонировки чипов
- `StatusChip.vue` обёртка `tone-*` не существует в CSS — двойная система цветов, из которой работает только PrimeVue (и та сломана, см. B2).

### M4. Тултипы вне кита и без отступов (найден 2026-10-11, исправлен)
- До: `.p-tooltip-text` — фон Aura-slate `#334155` (нет в палитре кита), padding `0` (текст прилипал к краям пузыря), стрелка 0×0 (невидима — её размеры тоже обнулял префлайт). Замер: 200×67, radius 6px.
- После: квадратный «штамп» — ink-900 `#1A1A1A`, белый текст 13px/600, padding 8px 12px, max-width 300px, shadow-lift, стрелка скрыта. Контраст 17.4:1. Замер: 200×91. Скриншоты: `13-tooltip-before.png`, `14-tooltip-after.png`.

## Minor Issues

- Счётчик `0 / 10000` — ink-400 (#9AA1AB) на белом, контраст ≈2.6:1 (WCAG AA для текста 4.5:1). Заменить на ink-500.
- Табы: `px-[2px]` — зона клика равна ширине текста; `text-[13.5px]` — нестандартный размер вне шкалы.
- Чип «Характеристика · Нет в запросе» несёт два сообщения сразу (длина до 189px); суффикс вынести в title/подпись строки.
- `RobotSearching.vue` — цвета дублируются hex-литералами в SVG (допустимо для атрибутов, но при смене токенов разъедется).

## Design Debt

- Смешение источников стилей: PrimeVue-дефолты + кастом components-слой + scoped-стили (`SearchHistory`) + inline-классы с magic numbers (`px-[2px]`, `mx-[9px]`, `text-[13.5px]`, `h-[7px] w-[7px]`).
- Скинированы не все PrimeVue-компоненты: button/tag/danger — на дефолтах (и сломаны), progressbar/accordion — заскинированы.

## Acceptable Differences

- Карточки `.card-registry`, dropzone, robot-лоадер, таблицы свойств, фокус-ринги (3px) — соответствуют киту.
- Прямые углы контролов — это язык кита, не баг («ужатость» не от них, а от потерянных отступов).

## Verification Checklist

- [x] Сняты computed styles всех мелких компонентов в dev и prod
- [x] Диагностирована причина (конфликт cascade-слоёв base/primevue)
- [x] Внедрён вариант C (2026-10-11): скин PrimeVue перенесён в `@layer components`, штампы-статусы, табы-папки, code-stamp, hist-chip, health-badge
- [x] Замеры после фикса (prod, 1440×900): CTA 181×46 (700/15px, hover #C1251C), primary 40px залит #264B82, secondary 32px контур, danger 32px залит #961D16, штампы 26px с цветной рамкой (success-700/accent-600), chip-missing с планкой 3px, code-stamp на #1F3E6C, hist-chip 28px, select 40px, табы-папки (активная — белая, планка 3px accent), health-badge с цветной планкой; 375px — без горизонтального переполнения
- [x] vitest 102/102, vue-tsc, eslint — зелёные; prod-сборка 359.61 kB (−3.65 kB, убран PrimeVue Tag)
- [ ] Result-state скриншот: не снят — LLM-бэкенд `model_busy: true`, поиск >60s; стили штампов проверены синтетическими сэмплами с точными классами компонентов
- Примечание: Chrome округляет border-width 1.5px → 1px; превью `variants.html` рендерилось так же, расхождения с согласованным вариантом нет.

## Automation Artifacts

- Скриншоты «до»: `.design-qa/actual/01–05*.png`
- Скриншоты «после»: `.design-qa/actual/07-after-text.png`, `08-after-corrections.png`, `09-after-csv.png`, `10-after-searching.png`, `11-after-mobile.png`, `12-after-searching.png`
- Превью вариантов: `.design-qa/variants.html`
