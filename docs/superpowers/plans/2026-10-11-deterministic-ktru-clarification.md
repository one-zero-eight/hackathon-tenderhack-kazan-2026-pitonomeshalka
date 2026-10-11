# Deterministic KTRU Clarification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Превратить неоднозначный результат анализа в ограниченный цикл выбора из данных КТРУ и выдать полную карточку одного конечного кода без LLM и повторных модельных вызовов.

**Architecture:** Первичный `/analyze` остаётся неизменным и сохраняет evidence. Новый чистый модуль строит вопрос по `detected_families` или оставшимся кандидатам; `POST /clarify` хранит только суженное множество кодов и ответы в `run_artifacts`, а финальную карточку читает из реляционного каталога. Frontend отображает чипы вариантов и карточку результата.

**Tech Stack:** Python 3.13, FastAPI, Pydantic v2, SQLAlchemy/PostgreSQL, Vue 3, TypeScript, PrimeVue 4, pytest, Vitest.

**Spec:** `docs/superpowers/specs/2026-10-11-deterministic-ktru-clarification-design.md`

## Global Constraints

- LLM, router и новые внешние вызовы не используются.
- После первичного `/analyze` embedding и classifier повторно не вызываются.
- Максимум 3 раунда уточнения.
- Варианты вопросов берутся только из `detected_families` и `candidates` исходного результата.
- Исходный `analysis_runs.result` не изменяется; состояние хранится в `run_artifacts`.
- Ответ с неизвестным `question_id` или `option_id` отклоняется, состояние не меняется.
- Финальная карточка содержит полную схему характеристик позиции и `requires_review=true`.
- Production code пишется только после наблюдаемого RED-теста.

## Review Focus

- Повторный или устаревший ответ не должен сужать множество по другому вопросу — Task 3 тестирует точное совпадение `question_id`.
- Опция, не пересекающая текущее множество кодов, должна отклоняться — Task 1 и Task 3.
- Одинаковая характеристика у всех кандидатов не должна порождать пустой вопрос — Task 1.
- После трёх раундов всегда должен включаться ручной выбор, а не четвёртый вопрос — Task 1.
- Несуществующий/непринадлежащий прогону код не должен попасть в финальную карточку — Task 2 и Task 3.

---

### Task 1: Чистый движок уточнений

**Files:**
- Create: `backend/src/clarify.py`
- Test: `backend/tests/test_clarify.py`

**Interfaces:**
- Produces: `build_clarification(result: dict, candidate_codes: list[str], round_number: int) -> dict`; `apply_option(clarification: dict, option_id: str, candidate_codes: list[str]) -> list[str]`.

- [ ] **Step 1:** Написать RED-тесты: неразрешённая family-характеристика выбирается раньше вопроса о товаре; её опции содержат пересечение `children` с текущими кодами; неделящая характеристика пропускается; fallback-вопрос содержит по одной опции на candidate; `round_number >= 3` возвращает `manual_choice=true`; неизвестная/пустая опция вызывает `ValueError`.
- [ ] **Step 2:** Запустить `PYTHONPATH=. uv run --with pytest pytest backend/tests/test_clarify.py -v`; ожидается ImportError/FAIL из-за отсутствующего модуля.
- [ ] **Step 3:** Реализовать минимальные чистые функции. Стабильные ID строить через `experiments.classifier_experiments.identity`; вариант `none` имеет `candidate_codes=[]` и `suggest_expand=true`.
- [ ] **Step 4:** Повторить тест; ожидается PASS. Затем прогнать non-stale backend suite.
- [ ] **Step 5:** Commit: `feat(backend): add deterministic clarification engine`.

### Task 2: Сериализация карточки КТРУ и хранение состояния

**Files:**
- Modify: `backend/src/storage.py`
- Create: `backend/src/final_card.py`
- Test: `backend/tests/test_clarification_storage.py`
- Test: `backend/tests/test_final_card.py`

**Interfaces:**
- Consumes: `PostgresEvidenceStore.get_run(run_id)` и ORM `KtruPosition`.
- Produces: `get_artifact(run_id, name) -> dict | None`; `build_final_card(position: KtruPosition, answers: list[dict]) -> dict`.

- [ ] **Step 1:** RED-тест `get_artifact` возвращает payload или `None` на fake engine; RED-тест карточки проверяет code/version/name/status, каждую actual characteristic и все её values/spans, requires_review=true, детерминированное обоснование из answers.
- [ ] **Step 2:** Запустить два тестовых файла; ожидается FAIL по отсутствующим интерфейсам.
- [ ] **Step 3:** Реализовать минимально, переиспользуя `pipeline.position_reference`/`value_snapshot` вместо дублирования.
- [ ] **Step 4:** PASS + non-stale backend suite.
- [ ] **Step 5:** Commit: `feat(backend): persist clarification state and render KTRU cards`.

### Task 3: API-контракты и `POST /clarify`

**Files:**
- Modify: `backend/src/schemas.py`
- Modify: `backend/src/service.py`
- Modify: `backend/src/presentation.py`
- Modify: `backend/src/routes.py`
- Modify: `backend/src/app.py` only if dependency wiring is needed
- Test: `backend/tests/test_clarify_api.py`

**Interfaces:**
- Consumes: Task 1 engine, Task 2 storage/card.
- Produces: `ClarifyRequest{run_id,question_id,option_id}`; response extensions `clarification`, `final_card`, `suggest_expand`, `manual_choice`; `PipelineService.clarify(request) -> AnalysisResponse`; `POST /clarify`.

- [ ] **Step 1:** RED-тесты на fake store: completed run → question; valid answer narrows and saves `clarification_state.json`; one code → final_card; stale question/unknown option → 409/422 and no write; `none` → suggest_expand; three rounds → manual_choice.
- [ ] **Step 2:** Запустить `backend/tests/test_clarify_api.py -v`; ожидается FAIL.
- [ ] **Step 3:** Реализовать схемы и endpoint. `PipelineService.analyze` после обычного result добавляет первичный clarification, но сохранённый исходный result остаётся совместимым; clarify никогда не захватывает `model_lock`.
- [ ] **Step 4:** PASS + non-stale backend suite.
- [ ] **Step 5:** Commit: `feat(api): add bounded clarification endpoint and final KTRU result`.

### Task 4: Восстановить отсутствующие frontend helpers

**Files:**
- Add existing files from current main working tree: `frontend/src/lib/corrections.ts`, `corrections.test.ts`, `csv.ts`, `csv.test.ts`, `fetch-like.ts`, `languagetool.ts`, `languagetool.test.ts`, `sessionId.ts`
- Modify: `.gitignore` to unignore `frontend/src/lib/`

**Interfaces:**
- Produces tracked helper modules already imported by frontend.

- [ ] **Step 1:** RED уже наблюдался на baseline: четыре suites не резолвят `../lib/*`.
- [ ] **Step 2:** Скопировать фактические helper-файлы текущего main и добавить исключение gitignore.
- [ ] **Step 3:** Запустить `pnpm --dir frontend test -- --run`; ожидается PASS базовых suites.
- [ ] **Step 4:** Commit: `fix(frontend): track shared helper modules`.

### Task 5: Frontend API и состояние уточнения

**Files:**
- Modify: `frontend/src/api/types.ts`
- Modify: `frontend/src/api/client.ts`
- Modify: `frontend/src/api/normalize.ts`
- Modify: `frontend/src/composables/useTextSearch.ts`
- Test: `frontend/src/api/client.test.ts`
- Test: `frontend/src/composables/useTextSearch.test.ts`

**Interfaces:**
- Produces TS-модели Clarification/FinalCard; `KtruApiClient.clarify`; `TextSearchClient.clarify`; `useTextSearch.clarify(optionId)`.

- [ ] **Step 1:** RED-тест клиента проверяет POST `/clarify`; RED-тест composable — phase searching→done, обновление результата, сохранение partial result при ошибке.
- [ ] **Step 2:** Запустить два тестовых файла; ожидается FAIL.
- [ ] **Step 3:** Реализовать минимально, сохранить обратную совместимость normalize defaults.
- [ ] **Step 4:** PASS + frontend suite.
- [ ] **Step 5:** Commit: `feat(frontend): add clarification API state`.

### Task 6: UI вопроса и финальной карточки

**Files:**
- Create: `frontend/src/components/ClarificationPanel.vue`
- Create: `frontend/src/components/ClarificationPanel.test.ts`
- Create: `frontend/src/components/FinalKtruCard.vue`
- Create: `frontend/src/components/FinalKtruCard.test.ts`
- Modify: `frontend/src/components/AnalysisResult.vue`
- Modify: `frontend/src/components/AnalysisResult.test.ts`
- Modify: `frontend/src/components/TextSearchPanel.vue`
- Modify: `frontend/src/components/TextSearchPanel.test.ts`

**Interfaces:**
- Consumes Task 5 types/composable.
- Produces `select(optionId)` event; видимая карточка кода/характеристик; кнопка расширенного поиска для `suggest_expand`.

- [ ] **Step 1:** RED component-тесты: рендер вопроса/чипов/счётчика; emit option id; disabled во время запроса; final card показывает code/name и values; TextSearchPanel прокидывает выбор в composable; manual choice использует те же options.
- [ ] **Step 2:** Запустить новые/изменённые тесты; ожидается FAIL.
- [ ] **Step 3:** Реализовать компоненты в текущем стиле `card-registry`; длинные характеристики сворачивать `<details>`.
- [ ] **Step 4:** PASS + frontend suite + `pnpm --dir frontend lint` + `pnpm --dir frontend type-check` (или фактические script names из package.json).
- [ ] **Step 5:** Commit: `feat(frontend): guide users to a final KTRU card`.

### Task 7: Интеграция и кейс аккумуляторной отвёртки

**Files:**
- Create/Modify: `backend/tests/test_clarification_flow.py`
- Modify relevant frontend flow test if needed.

**Interfaces:**
- Consumes all previous tasks.

- [ ] **Step 1:** RED-flow test: сохранённый результат с восемью uncertain-кандидатами → product question → выбрать «Шуруповерт» → единственный код → final_card; ни embedding, ни classifier fake не вызваны. Второй тест: family split → два раунда → final; третий: none → suggest_expand.
- [ ] **Step 2:** Запустить flow tests; ожидается FAIL до фикса интеграционных зазоров.
- [ ] **Step 3:** Исправить только интеграционные зазоры, не расширяя scope.
- [ ] **Step 4:** Полный прогон: non-stale backend tests; frontend tests/lint/type-check. Отдельно перечислить известные stale backend collection errors, если они остаются.
- [ ] **Step 5:** Commit: `test: cover deterministic KTRU clarification flow`.
