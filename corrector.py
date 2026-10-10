import sys

from languagetool_client import LanguageToolError, check

if __name__ == "__main__":
    text = " ".join(sys.argv[1:]) or "Я пошол в магазен и купил хлеп."
    try:
        result = check(text)
    except LanguageToolError as e:
        sys.exit(f"Ошибка: {e}\nСервер запущен? Проверьте: docker compose ps")

    print("Было: ", result.text)
    print("Стало:", result.corrected)
    for m in result.matches:
        print(f"\n[{m.rule_id}] «{m.error_text}» (позиция {m.offset}) — {m.message}")
        if m.replacements:
            print("  Варианты:", ", ".join(m.replacements[:5]))
