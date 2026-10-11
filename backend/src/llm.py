"""OpenAI-compatible router client that maps free-text answers onto catalog options."""

from json import JSONDecodeError, dumps, loads
from time import perf_counter
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class LLMUnavailable(RuntimeError):
    """The router is not configured, unreachable or answered an unusable payload."""


class LLMMappingError(ValueError):
    """The router answer did not match any option of the current question."""


SYSTEM_PROMPT = (
    "Ты помогаешь подобрать код КТРУ. Даны вопрос, варианты ответов из каталога и свободный "
    "ответ пользователя. Выбери единственный вариант, лучше всего соответствующий ответу. "
    'Ответь строго JSON без пояснений: {"option_id": "<id>"}. '
    'Если ни один вариант не подходит, верни {"option_id": null}.'
)


def parse_option_id(content: str) -> str | None:
    """Extract option_id from a router message; markdown fences are tolerated."""
    text = (content or "").strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:]
        text = text.strip()
    try:
        parsed = loads(text)
    except JSONDecodeError:
        return None
    if isinstance(parsed, dict):
        value = parsed.get("option_id")
        return value.strip() if isinstance(value, str) and value.strip() else None
    return None


class RouterClient:
    def __init__(self, base_url: str = "", api_key: str = "", model: str = "", timeout: float = 15.0):
        self.base_url = (base_url or "").rstrip("/")
        self.api_key = api_key or ""
        self.model = model
        self.timeout = float(timeout)

    @property
    def enabled(self) -> bool:
        return bool(self.base_url and self.model)

    def _post(self, payload: dict) -> dict:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = "Bearer " + self.api_key
        request = Request(self.base_url + "/chat/completions",
                          data=dumps(payload, ensure_ascii=False).encode("utf-8"), headers=headers)
        try:
            with urlopen(request, timeout=self.timeout) as response:
                return loads(response.read().decode("utf-8"))
        except HTTPError as error:
            detail = error.read().decode(errors="replace")[:200]
            raise LLMUnavailable(f"LLM router HTTP {error.code}: {detail}") from error
        except (URLError, TimeoutError, OSError) as error:
            raise LLMUnavailable(f"LLM router unavailable at {self.base_url}: {error}") from error
        except (JSONDecodeError, UnicodeDecodeError) as error:
            raise LLMUnavailable(f"LLM router returned malformed JSON: {error}") from error

    def map_option(self, question: str, options: list[dict], text: str) -> str:
        """Return exactly one option id of this question for the user's free-text answer."""
        if not self.enabled:
            raise LLMUnavailable("LLM-роутер не настроен; выберите один из предложенных вариантов")
        allowed = {option["id"] for option in options}
        listing = "\n".join(f"- {option['id']}: {option['text']}" for option in options)
        payload = {"model": self.model, "temperature": 0, "max_tokens": 120, "stream": False,
                   "messages": [
                       {"role": "system", "content": SYSTEM_PROMPT},
                       {"role": "user", "content": (f"Вопрос: {question}\nВарианты:\n{listing}"
                                                    f"\n\nСвободный ответ пользователя: {text}")},
                   ]}
        started = perf_counter()
        data = self._post(payload)
        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as error:
            raise LLMUnavailable("LLM router returned an unexpected payload") from error
        option_id = parse_option_id(content)
        if option_id not in allowed:
            raise LLMMappingError("Не удалось сопоставить ответ с вариантами; выберите вариант из списка")
        return option_id
