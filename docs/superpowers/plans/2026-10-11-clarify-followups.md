# Clarification Follow-ups Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Починить дубли истории поиска, убрать сортировку кандидатов и добавить вопросы по обязательным характеристикам перед выдачей финальной карточки.

**Architecture:** Фронтенд пишет историю только при новом run анализа (watch по run_id, а не по фазе). Презентация отдаёт кандидатов в порядке бэкенда без пересортировки. Когда после уточнений остаётся один код, сервис задаёт вопросы по его обязательным actual-характеристикам (чипы из значений каталога + свободный ввод через LLM-роутер), подтверждённые значения попадают в финальную карточку.

**Tech Stack:** Vue 3 + TS, FastAPI, Pydantic v2, pytest, Vitest.

**Spec:** `docs/superpowers/specs/2026-10-11-deterministic-ktru-clarification-design.md` (+ аддендум LLM).

## Global Constraints

- LLM только мапит свободный ответ на option_id текущего вопроса; коды и значения не придумывает.
- Ответы на обязательные характеристики не сужают множество кодов и не учитываются в лимите 3 уточняющих раундов.
- Порядок кандидатов: группировка по статусу (✓ compatible → ! uncertain → ✕ rejected), внутри группы — по числу несопоставленных свойств по убыванию; полные связи — порядок анализа (стабильная сортировка).
- История поиска пишется один раз на новый анализ (новый run_id).
- Обратная совместимость: старые сохранённые результаты и артефакты читаются.

## Review Focus

- Ответ на обязательную характеристику не должен менять candidate_codes — Task 2.
- Пропуск («Оставить незаполненным») и unknown-значения не блокируют финал — Task 2.
- Clarify-раунд не пишет историю; расширенный поиск (новый run) — пишет — Task 1.
- Порядок кандидатов в API-тестах фиксируется как порядок retrieval — Task 3.

---

### Task 1: История только для новых прогонов + без сортировки кандидатов

**Files:**
- Modify: `frontend/src/components/TextSearchPanel.vue` (watch(searchPhase) → watch по `searchResult?.run_id`)
- Test: `frontend/src/components/TextSearchPanel.test.ts`
- Modify: `backend/src/presentation.py` (сортировка по статусу, затем по числу несопоставленных свойств по убыванию)
- Test: `backend/tests/test_clarify_api.py` (тесты порядка кандидатов)

**Interfaces:**
- Produces: история пишется ровно при появлении/смене `run_id` результата; `AnalysisResponse.candidates` в порядке `report.candidates` (порядок retrieval).

- [ ] **Step 1:** Фронт: заменить watch фазы на watch run_id; уточнение (тот же run_id) историю не пишет. Тест: после search — addHistory 1 раз; после clarify — число вызовов не растёт; после expand-поиска (новый run) — растёт. Мок history api учитывает, что панель берёт `api` из `../services` (vi.mock при необходимости).
- [ ] **Step 2:** Бэкенд: удалить `priority`/`candidates.sort` из `analysis_response`; тест порядка: вход в порядке retrieval → выход тот же; зафиксировать в докстринге `/analyze`, что порядок совпадает с порядком кандидатов анализа.
- [ ] **Step 3:** `pnpm --dir frontend test -- --run && pnpm --dir frontend lint && pnpm --dir frontend type-check`; backend non-stale suite.
- [ ] **Step 4:** Commit: `fix: write search history once per analysis run and keep backend candidate order` (допустимы два коммита: frontend/backend).

### Task 2: Вопросы по обязательным характеристикам перед финальной карточкой

**Files:**
- Modify: `backend/src/clarify.py` (билдер вопроса по характеристике позиции)
- Modify: `backend/src/service.py` (фаза fill после сужения до 1 кода)
- Modify: `backend/src/final_card.py` (подтверждённые значения в карточке)
- Modify: `backend/src/schemas.py` (kind `required`; `FinalCard.confirmed`)
- Test: `backend/tests/test_clarify_api.py`, `backend/tests/test_final_card.py`
- Modify: `frontend/src/api/types.ts` (ClarificationKind + `required`; `FinalCard.confirmed?`)
- Modify: `frontend/src/components/FinalKtruCard.vue` (+ блок подтверждённых значений) и тест

**Interfaces:**
- Consumes: `build_clarification`/`apply_option` (Task prior), `RouterClient.map_option` (LLM-аддендум), `build_final_card(position, answers)`.
- Produces: `build_required_question(position_code, characteristic) -> dict` (kind `required`, options из текстовых значений + skip-опция «Оставить незаполненным», allow_text=True, question_id = `clarification_req_` + identity(code, char.code)); state расширяется `confirmed: [{characteristic_code, name, value}]` и `fill_code`; `final_card.confirmed: [{name, value}]`.

- [ ] **Step 1:** Движок: `build_required_question` — только required+actual характеристики позиции; choice=fixed с единственным значением не спрашивается (авто-подтверждение); числовые характеристики без текстовых значений не спрашиваются (остаются `missing_required` карточки).
- [ ] **Step 2:** Сервис: при `len(narrowed)==1` — загрузить позицию, вычислить неотвеченные required (по state.confirmed), задать вопрос kind=required; ответ (чип/текст через LLM) пишет confirmed и ведёт к следующему вопросу или к финальной карточке; skip-опция фиксирует пропуск; ограничение 3 раунда на fill НЕ действует (это не сужение). Stale question_id → 409 как раньше.
- [ ] **Step 3:** Карточка: `final_card.confirmed` + строка в rationale; фронт рендерит блок «Подтверждённые характеристики».
- [ ] **Step 4:** Тесты: fill-флоу (вопрос → ответ чипом → следующий вопрос → финал с confirmed), ответ текстом через fake-LLM, skip, ответ не сужает коды,_backward-совместимость старых артефактов (без confirmed) — финал работает.
- [ ] **Step 5:** Полные прогоны: backend non-stale suite; frontend test/lint/type-check. Commit: `feat: ask required characteristics before issuing the final KTRU card`.
