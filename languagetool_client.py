"""Клиент для HTTP API LanguageTool (https://languagetool.org/http-api/).

Пример:
    from languagetool_client import check, correct

    print(correct("Я пошол в магазен"))  # -> "Я пошёл в магазин"

    result = check("Я пошол в магазен")
    for m in result.matches:
        print(m.rule_id, m.message, m.error_text, "->", m.replacements[:3])

Адрес сервера берётся из переменной окружения LANGUAGETOOL_URL
(по умолчанию http://localhost:8010 — см. docker-compose.yml).
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

DEFAULT_URL = os.environ.get("LANGUAGETOOL_URL", "http://localhost:8010")
DEFAULT_LANGUAGE = "ru-RU"


class LanguageToolError(Exception):
    """Сервер недоступен или вернул ошибку."""


@dataclass(frozen=True)
class Match:
    """Одна найденная ошибка."""

    rule_id: str
    rule_description: str
    category_id: str
    category_name: str
    issue_type: str  # misspelling, grammar, typographical, style, ...
    message: str
    short_message: str
    offset: int  # индекс в Python-строке (сервер считает в UTF-16, мы пересчитываем)
    length: int
    error_text: str
    replacements: tuple[str, ...]
    sentence: str

    @property
    def best_replacement(self) -> str | None:
        return self.replacements[0] if self.replacements else None


@dataclass(frozen=True)
class CheckResult:
    """Результат проверки текста."""

    text: str
    corrected: str
    language: str
    detected_language: str | None
    matches: tuple[Match, ...]

    @property
    def has_errors(self) -> bool:
        return bool(self.matches)


def apply_corrections(text: str, matches: Iterable[Match]) -> str:
    """Подставляет первый вариант замены для каждой ошибки.

    Ошибки без вариантов и пересекающиеся с уже исправленными пропускаются.
    """
    result = text
    boundary = len(text)
    # Идём с конца, чтобы offset'ы ещё не обработанных ошибок не съезжали
    for m in sorted(matches, key=lambda m: m.offset, reverse=True):
        end = m.offset + m.length
        if m.best_replacement is None or end > boundary:
            continue
        result = result[: m.offset] + m.best_replacement + result[end:]
        boundary = m.offset
    return result


def _utf16_index_map(text: str) -> list[int] | None:
    """Таблица «индекс UTF-16 -> индекс Python»; None, если они совпадают."""
    if len(text.encode("utf-16-le")) // 2 == len(text):
        return None
    mapping = []
    for i, ch in enumerate(text):
        mapping.append(i)
        if ord(ch) > 0xFFFF:  # эмодзи и т.п. занимают в UTF-16 две позиции
            mapping.append(i)
    mapping.append(len(text))
    return mapping


def _parse_match(raw: dict[str, Any], text: str, index_map: list[int] | None) -> Match:
    start = raw["offset"]
    end = start + raw["length"]
    if index_map is not None:
        start, end = index_map[start], index_map[end]
    rule = raw.get("rule", {})
    category = rule.get("category", {})
    return Match(
        rule_id=rule.get("id", ""),
        rule_description=rule.get("description", ""),
        category_id=category.get("id", ""),
        category_name=category.get("name", ""),
        issue_type=rule.get("issueType", ""),
        message=raw.get("message", ""),
        short_message=raw.get("shortMessage", ""),
        offset=start,
        length=end - start,
        error_text=text[start:end],
        replacements=tuple(r["value"] for r in raw.get("replacements", [])),
        sentence=raw.get("sentence", ""),
    )


class LanguageToolClient:
    """Клиент к серверу LanguageTool.

    language может быть кодом вроде "ru-RU", "en-US" или "auto" (автоопределение).
    level="picky" включает более строгие (стилистические) правила.
    """

    def __init__(
        self,
        url: str = DEFAULT_URL,
        language: str = DEFAULT_LANGUAGE,
        *,
        mother_tongue: str | None = None,
        enabled_rules: Iterable[str] = (),
        disabled_rules: Iterable[str] = (),
        enabled_categories: Iterable[str] = (),
        disabled_categories: Iterable[str] = (),
        enabled_only: bool = False,
        level: str = "default",
        timeout: float = 30.0,
    ) -> None:
        self.url = url.rstrip("/")
        self.language = language
        self.mother_tongue = mother_tongue
        self.enabled_rules = set(enabled_rules)
        self.disabled_rules = set(disabled_rules)
        self.enabled_categories = set(enabled_categories)
        self.disabled_categories = set(disabled_categories)
        self.enabled_only = enabled_only
        self.level = level
        self.timeout = timeout

    def check(self, text: str, language: str | None = None) -> CheckResult:
        """Проверяет текст и возвращает ошибки вместе с исправленным текстом."""
        language = language or self.language
        if not text.strip():
            return CheckResult(text, text, language, None, ())

        response = self._request("check", self._check_params(text, language))
        index_map = _utf16_index_map(text)
        matches = tuple(_parse_match(raw, text, index_map) for raw in response.get("matches", []))
        lang_info = response.get("language", {})
        return CheckResult(
            text=text,
            corrected=apply_corrections(text, matches),
            language=lang_info.get("code", language),
            detected_language=lang_info.get("detectedLanguage", {}).get("code"),
            matches=matches,
        )

    def correct(self, text: str, language: str | None = None) -> str:
        """Возвращает исправленный текст."""
        return self.check(text, language).corrected

    def languages(self) -> list[dict[str, str]]:
        """Список поддерживаемых языков: [{"name": ..., "code": ..., "longCode": ...}]."""
        return self._request("languages")

    def is_alive(self) -> bool:
        """Отвечает ли сервер."""
        try:
            self.languages()
        except LanguageToolError:
            return False
        return True

    def _check_params(self, text: str, language: str) -> dict[str, str]:
        params = {"text": text, "language": language, "level": self.level}
        if self.mother_tongue:
            params["motherTongue"] = self.mother_tongue
        for key, values in (
            ("enabledRules", self.enabled_rules),
            ("disabledRules", self.disabled_rules),
            ("enabledCategories", self.enabled_categories),
            ("disabledCategories", self.disabled_categories),
        ):
            if values:
                params[key] = ",".join(sorted(values))
        if self.enabled_only:
            params["enabledOnly"] = "true"
        return params

    def _request(self, path: str, params: dict[str, str] | None = None) -> Any:
        url = f"{self.url}/v2/{path}"
        data = urllib.parse.urlencode(params).encode() if params is not None else None
        try:
            with urllib.request.urlopen(url, data=data, timeout=self.timeout) as resp:
                return json.load(resp)
        except urllib.error.HTTPError as e:
            body = e.read().decode(errors="replace").strip()
            raise LanguageToolError(f"HTTP {e.code} от {url}: {body}") from e
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            raise LanguageToolError(f"LanguageTool недоступен по адресу {self.url}: {e}") from e


_default_client: LanguageToolClient | None = None


def _client() -> LanguageToolClient:
    global _default_client
    if _default_client is None:
        _default_client = LanguageToolClient()
    return _default_client


def check(text: str, language: str | None = None) -> CheckResult:
    """Проверяет текст клиентом по умолчанию."""
    return _client().check(text, language)


def correct(text: str, language: str | None = None) -> str:
    """Исправляет текст клиентом по умолчанию."""
    return _client().correct(text, language)
