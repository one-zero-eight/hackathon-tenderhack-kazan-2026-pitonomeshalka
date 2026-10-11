# Task 2 report: сериализация карточки КТРУ и чтение clarification artifact

## Изменённые файлы

- `backend/src/storage.py` — добавлен `PostgresStore.get_artifact(run_id, name) -> dict | None`: читает `payload` из `run_artifacts` по `(run_id, name)` в стиле существующего `get_run`; возвращает `None`, если записи нет. Класс в коде называется `PostgresStore` (в брифе упомянут как `PostgresEvidenceStore`) — интерфейс добавлен именно туда, где живут `save_artifact`/`get_run`.
- `backend/src/final_card.py` — новый модуль с `build_final_card(position: KtruPosition, answers: list[dict]) -> dict`. Переиспользует `pipeline.position_reference` (код/версия/имя/статус/период действия/единицы и пр.) и `pipeline.value_snapshot` (все значения со spans) — сериализация не дублируется. Карточка содержит только `actual`-характеристики, отсортированные по коду (детерминизм), с кодом/названием, обязательностью, типом выбора, числовым признаком, единицами и всеми значениями/диапазонами; `requires_review=true`; детерминированное обоснование строится из `answers` (`question_id`/`option_id` каждого раунда + код позиции), без ветвлений и генерации.
- `backend/tests/test_clarification_storage.py` — RED-тесты `get_artifact` на fake engine (payload и `None`), включая проверку текста запроса и параметров.
- `backend/tests/test_final_card.py` — RED-тесты карточки на ORM-объектах `KtruPosition`/`KtruCharacteristic`/`KtruValue` без базы: identity/status/период/units/`requires_review`, каждая actual-характеристика со всеми values/spans (исключение не-actual), детерминизм и зависимость обоснования от answers.
- `.superpowers/sdd/2026-10-11-deterministic-ktru-clarification/task-2-report.md` — этот отчёт.

## RED

Обе команды запускались до реализации.

```bash
PYTHONPATH=. uv run --with pytest pytest backend/tests/test_clarification_storage.py backend/tests/test_final_card.py -v
```

Фактический вывод:

```
ERROR collecting backend/tests/test_final_card.py
backend/tests/test_final_card.py:8: in <module>
    from backend.src.final_card import build_final_card
E   ModuleNotFoundError: No module named 'backend.src.final_card'
!!!!!!!!!!!!!!!!!!!! Interrupted: 1 error during collection !!!!!!!!!!!!!!!!!!!!
```

```bash
PYTHONPATH=. uv run --with pytest pytest backend/tests/test_clarification_storage.py -v
```

Фактический вывод:

```
backend/tests/test_clarification_storage.py::test_get_artifact_returns_saved_payload FAILED
backend/tests/test_clarification_storage.py::test_get_artifact_returns_none_for_missing_run_or_name FAILED
E       AttributeError: 'PostgresStore' object has no attribute 'get_artifact'. Did you mean: 'save_artifact'?
============================== 2 failed in 0.23s ===============================
```

## GREEN

```bash
PYTHONPATH=. uv run --with pytest pytest backend/tests/test_clarification_storage.py backend/tests/test_final_card.py -v
```

Результат: `5 passed in 0.28s`.

Non-stale backend suite:

```bash
PYTHONPATH=. uv run --with pytest pytest backend/tests/test_clarification_storage.py backend/tests/test_final_card.py backend/tests/test_clarify.py backend/tests/test_settings.py -v
```

Результат: `18 passed, 22 subtests passed in 0.35s`.

Дополнительно с холодным кэшем:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. uv run --with pytest pytest --cache-clear -q backend/tests/test_clarification_storage.py backend/tests/test_final_card.py backend/tests/test_clarify.py backend/tests/test_settings.py
```

Результат: `18 passed, 22 subtests passed in 0.34s`.

Известные вне-задачи collection errors (`backend/tests/test_api.py`, `backend/tests/test_storage.py`) не затронуты и в suite не входят.

## Self-review

- Интерфейс Task 1 (`backend/src/clarify.py`) не изменялся; API/schemas/routes/frontend не тронуты.
- `get_artifact` — 6 строк, зеркалит стиль `get_run` (`exec_driver_sql` + `mappings().first()`); psycopg возвращает JSONB как dict, поэтому payload приходит готовым словарём; отсутствующая запись — `None`, а не ошибка.
- Тест store не контактирует с БД: реальный `PostgresStore.__init__` создаёт engine лениво (без соединения), затем engine подменяется fake (фиксируются statement и параметры).
- Карточка полностью детерминирована: `position_reference` + `value_snapshot` без дублирования сериализации; характеристики фильтруются по `actual` и сортируются по коду; порядок значений задаётся отношением `order_by ordinal`; обоснование — конкатенация `question_id`/`option_id` из answers и кода позиции, ничего не генерируется моделью.
- Тесты карточки работают на ORM-объектах без сессии/базы (инструментированные списки relationship).
- `git diff --check` чист; `git status` содержит только 4 целевых файла + отчёт.
- Оговорка: единица характеристики выводится как отсортированный набор `okei` её значений (`units`); требование брифа «каждую actual characteristic и все её values/spans» покрыто тестами.
- Commit hash: см. финальный ответ координатору (запись в отчёт добавляется до commit по конвенции Task 1).
