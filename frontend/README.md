# КТРУ Ассистент — frontend

Веб-интерфейс для сопоставления текстового описания товара со структурированной
позицией каталога КТРУ. Два режима: одиночный текстовый запрос и пакетная
проверка CSV-таблицы со стримингом результатов.

Стек: Vue 3 (`<script setup>`) + TypeScript + Vite + Tailwind CSS v4 +
PrimeVue 4 (стилизованный режим, кастомный пресет в фирменном синем Портала
поставщиков). Тесты: Vitest + `@vue/test-utils` + happy-dom.

## Запуск

Нужны два сервиса из корня репозитория:

```bash
uv run --locked -m backend.src        # FastAPI бекенд на http://127.0.0.1:8000
docker compose up -d languagetool     # LanguageTool на http://127.0.0.1:8010
```

Затем:

```bash
pnpm install
pnpm dev              # http://localhost:5173
```

Dev-сервер проксирует `/api/*` → `127.0.0.1:8000` и `/lt/*` → `127.0.0.1:8010`
(см. `vite.config.ts`), поэтому CORS не требуется. Адреса переопределяются
переменными `VITE_API_BASE` и `VITE_LANGUAGETOOL_BASE`.

Пока LanguageTool недоступен, поиск остаётся рабочим: текст уходит «как есть»,
а интерфейс показывает предупреждение. В CSV-режиме строки тоже уходят без
исправлений с баннером-предупреждением.

## Структура

```
src/
  api/        Типы контракта бекенда (schemas.py) и HTTP-клиент
  lib/        Чистая логика: исправления LanguageTool, LT-клиент, CSV-парсер
  composables/useSpellcheck, useTextSearch, useCsvBatch
  components/ Фичевые компоненты + ui/StatusChip (PrimeVue Tag)
  services.ts Клиенты-синглтоны, прокинутые в панели по умолчанию
  theme.ts    PrimeVue-пресет (Portal blue)
```

## Команды

```bash
pnpm test          # Vitest (одноразовый прогон)
pnpm test:watch    # Vitest в режиме наблюдения
pnpm lint          # ESLint
pnpm lint:fix      # ESLint с автофиксами
pnpm format        # Prettier write
pnpm format:check  # Prettier check
pnpm type-check    # vue-tsc
pnpm build         # прод-сборка (сначала type-check)
```

## Инструменты

- **Tailwind CSS v4** через `@tailwindcss/vite`; точка входа — `src/style.css`
  (`@import 'tailwindcss'`). Тема правится в CSS (`@theme`), не в JS-конфиге.
- **PrimeVue 4** (MIT; у PrimeVue 5 новая коммерческая лицензия с баннером без
  ключа — поэтому зафиксированы 4.x). Тёмная тема отключена через
  `darkModeSelector: '.app-dark'`, чтобы компоненты не уезжали в тёмные токены.
- **ESLint** (`eslint.config.mjs`): Vue + TypeScript recommended плюс лимиты из
  [finsec-train](https://github.com/projacktor/finsec-train) — цикломатическая
  сложность ≤ 15, ≤ 300 строк кода в файле, ≤ 100 символов в строке.
- **Prettier** (`.prettierrc.json`): без точек с запятой, одинарные кавычки,
  100 колонок, плагины сортировки атрибутов/CSS/импортов и Tailwind-классов.

## Git hooks

Husky живёт в `frontend/.husky`, а `.git` — в корне репозитория, поэтому
`prepare` ставит хуки командой `cd .. && husky frontend/.husky` (см. документацию
husky, «Project Not in Git Root Directory»). Pre-commit запускает lint-staged:
`eslint --fix`, затем `prettier --write`.
