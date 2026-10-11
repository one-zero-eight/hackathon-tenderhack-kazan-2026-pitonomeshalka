# Task 1 report: чистый движок уточнений

## Изменённые файлы

- `backend/src/clarify.py` — добавлены чистые функции `build_clarification(...)` и `apply_option(...)` с детерминированными ID через `experiments.classifier_experiments.identity`.
- `backend/tests/test_clarify.py` — добавлены тесты приоритета family-характеристики, пересечения `children`, пропуска неделящей характеристики, product fallback, лимита раундов, стабильных ID, `none`, неизвестных и устаревших опций.
- `.superpowers/sdd/2026-10-11-deterministic-ktru-clarification/task-1-report.md` — этот отчёт.

## RED

Команда:

```bash
PYTHONPATH=. uv run --with pytest pytest backend/tests/test_clarify.py -v
```

Ожидаемый результат: exit code 2 на collection, `ModuleNotFoundError: No module named 'backend.src.clarify'`, потому что production-модуль ещё не существовал.

Дополнительный TDD-цикл для требования review focus об опции без пересечения:

```bash
PYTHONPATH=. uv run --with pytest pytest backend/tests/test_clarify.py -v
```

Результат до минимального исправления: 1 failed, 6 passed; `test_apply_option_allows_none_but_rejects_a_stale_empty_intersection` завершился `Failed: DID NOT RAISE ValueError`.

## GREEN

Целевой тест:

```bash
PYTHONPATH=. uv run --with pytest pytest backend/tests/test_clarify.py -v
```

Результат: 7 passed in 0.03s.

Fresh non-stale backend suite:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. uv run --with pytest pytest --cache-clear backend/tests/test_clarify.py backend/tests/test_settings.py -v
```

Результат: 13 passed, 22 subtests passed in 0.12s.

Полный `backend/tests` также был проверен с `--cache-clear`, но текущая ветка содержит stale suites вне Task 1: `backend/tests/test_api.py` импортирует отсутствующий `backend.src.service.load_catalog`, а `backend/tests/test_storage.py` импортирует отсутствующий `backend.src.migrate.import_files`. Эти две collection-ошибки предшествуют Task 1 и не исправлялись согласно ограничению не трогать другие задачи. Непротухшая конфигурационная suite и новая suite Task 1 проходят.

## Self-review

- Реализация ограничена Task 1: новые production/test файлы, без изменений API, storage, схем или frontend.
- Вопрос по неразрешённой характеристике выбирается раньше product fallback только когда после пересечения есть минимум две разные непустые группы кандидатов.
- Опции сохраняют порядок текущего `candidate_codes`, содержат только пересечение с `children`; пустые/дублирующие группы пропускаются.
- При `round_number >= 3` характеристика не задаётся, возвращается прямой product choice с `manual_choice=true`.
- Все ID детерминированы через `identity`; `none` имеет `candidate_codes=[]` и `suggest_expand=true`.
- `apply_option` отклоняет пустой/неизвестный ID и ненулевую опцию, которая больше не пересекается с текущими кандидатами; `none` корректно возвращает пустой список.
- `git diff --check` проходит. Вне Task 1 изменений не внесено.

## Commit

`feat(backend): add deterministic clarification engine`

Commit hash: будет добавлен после создания commit; фактический hash также возвращён в финальном ответе.
