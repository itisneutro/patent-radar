"""Клиент языковой модели через OpenAI-совместимый API (заготовка КТ1).

Один клиент работает с любым сервером, который реализует OpenAI-совместимый
API: Ollama, LM Studio, llama.cpp server, vLLM. Провайдер и параметры задаются
переменными окружения (файл .env в корне репозитория, образец — .env.example):

    LLM_PROVIDER         ollama | openai_compatible | stub; по умолчанию ollama
    LLM_BASE_URL         адрес API; для ollama по умолчанию http://localhost:11434/v1
    LLM_MODEL            имя модели; по умолчанию qwen2.5:7b
    LLM_API_KEY          ключ для заголовка Authorization; для ollama по умолчанию ollama
    LLM_TEMPERATURE      температура генерации от 0 до 2; по умолчанию 0.2
    LLM_TIMEOUT_SECONDS  таймаут ответа в секундах; по умолчанию 60

Запрос к модели: POST {LLM_BASE_URL}/chat/completions с полями model, messages,
temperature и stream=false, заголовок Authorization: Bearer {LLM_API_KEY}.
Проверка доступности: GET {LLM_BASE_URL}/models.

На КТ1 эндпоинт /search этот клиент не вызывает. На КТ2 API передаст в chat()
сообщения из app/llm/prompts.py, а при LLMError вернёт выдачу без пояснения
модели: ошибка LLM не превращается в ответ 5xx.

Пример:

    client = LLMClient.from_env()
    if client.is_available():
        text = client.chat([{"role": "user", "content": "Чем похожи эти патенты?"}])
"""

import ipaddress
import math
import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Final, Literal, Self, cast, get_args

import httpx

#: Провайдеры LLM: локальный Ollama, любой OpenAI-совместимый сервер, заглушка без сети.
Provider = Literal["ollama", "openai_compatible", "stub"]
PROVIDERS: Final[tuple[str, ...]] = get_args(Provider)

DEFAULT_PROVIDER: Final[Provider] = "ollama"
OLLAMA_BASE_URL: Final = "http://localhost:11434/v1"
OLLAMA_API_KEY: Final = "ollama"
DEFAULT_MODEL: Final = "qwen2.5:7b"
DEFAULT_TEMPERATURE: Final = 0.2
DEFAULT_TIMEOUT_SECONDS: Final = 60.0

#: Таймаут проверки доступности: /models отвечает быстро, ждать 60 с незачем.
AVAILABILITY_TIMEOUT_SECONDS: Final = 5.0

#: Фиксированный ответ провайдера stub.
STUB_REPLY: Final = "Пояснение-заглушка (LLM_PROVIDER=stub): языковая модель не вызывалась."


class LLMError(Exception):
    """Языковая модель недоступна или ответила не по формату OpenAI-совместимого API."""


@dataclass(frozen=True, slots=True)
class LLMSettings:
    """Настройки подключения к LLM. Значения по умолчанию — локальный Ollama."""

    provider: Provider = DEFAULT_PROVIDER
    base_url: str = OLLAMA_BASE_URL
    model: str = DEFAULT_MODEL
    api_key: str = field(default=OLLAMA_API_KEY, repr=False)
    temperature: float = DEFAULT_TEMPERATURE
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS

    @classmethod
    def from_env(cls, environ: Mapping[str, str | None] | None = None) -> Self:
        """Читает настройки из переменных LLM_*; пустое значение равно отсутствующему.

        Args:
            environ: источник переменных; по умолчанию os.environ, куда
                load_dotenv() в app/api/main.py загружает файл .env.

        Raises:
            ValueError: неизвестный провайдер; LLM_BASE_URL без http:// или https://;
                для openai_compatible не заданы LLM_BASE_URL или LLM_API_KEY;
                температура или таймаут — не число либо вне допустимого диапазона.
        """
        env: Mapping[str, str | None] = os.environ if environ is None else environ

        def read(name: str) -> str:
            return (env.get(name) or "").strip()

        provider = read("LLM_PROVIDER").lower() or DEFAULT_PROVIDER
        if provider not in PROVIDERS:
            raise ValueError(
                f"LLM_PROVIDER={provider!r} не поддерживается; "
                f"допустимые значения: {', '.join(PROVIDERS)}"
            )

        base_url = read("LLM_BASE_URL")
        if base_url and not base_url.startswith(("http://", "https://")):
            raise ValueError(
                "Значение LLM_BASE_URL должно начинаться с http:// или https://, "
                f"получено {base_url!r}"
            )
        api_key = read("LLM_API_KEY")
        if provider == "openai_compatible":
            missing = [
                name
                for name, value in (("LLM_BASE_URL", base_url), ("LLM_API_KEY", api_key))
                if not value
            ]
            if missing:
                raise ValueError(
                    f"Для LLM_PROVIDER=openai_compatible задайте {' и '.join(missing)}"
                )

        temperature = _read_number(env, "LLM_TEMPERATURE", DEFAULT_TEMPERATURE)
        if not 0 <= temperature <= 2:
            raise ValueError(
                f"Значение LLM_TEMPERATURE должно быть от 0 до 2, получено {temperature:g}"
            )
        timeout = _read_number(env, "LLM_TIMEOUT_SECONDS", DEFAULT_TIMEOUT_SECONDS)
        if timeout <= 0:
            raise ValueError(
                f"Значение LLM_TIMEOUT_SECONDS должно быть больше 0, получено {timeout:g}"
            )

        return cls(
            provider=cast(Provider, provider),
            base_url=(base_url or OLLAMA_BASE_URL).rstrip("/"),
            model=read("LLM_MODEL") or DEFAULT_MODEL,
            api_key=api_key or OLLAMA_API_KEY,
            temperature=temperature,
            timeout_seconds=timeout,
        )


class LLMClient:
    """Клиент chat completions для провайдеров ollama, openai_compatible и stub."""

    def __init__(self, settings: LLMSettings, transport: httpx.BaseTransport | None = None) -> None:
        """Создаёт клиент.

        Args:
            settings: настройки подключения, обычно LLMSettings.from_env().
            transport: транспорт httpx; в тестах — httpx.MockTransport, чтобы не ходить в сеть.
        """
        self.settings = settings
        self._transport = transport

    @classmethod
    def from_env(cls) -> Self:
        """Создаёт клиент по переменным окружения LLM_* (см. LLMSettings.from_env)."""
        return cls(LLMSettings.from_env())

    def chat(self, messages: Sequence[Mapping[str, str]]) -> str:
        """Отправляет сообщения модели и возвращает текст её ответа.

        Args:
            messages: сообщения в формате OpenAI, например
                [{"role": "system", "content": "..."}, {"role": "user", "content": "..."}].

        Returns:
            Текст ответа без пробелов по краям; для провайдера stub — STUB_REPLY.

        Raises:
            ValueError: пустой список сообщений.
            LLMError: сервер недоступен, истёк таймаут, HTTP-ошибка или ответ не по формату.
        """
        if not messages:
            raise ValueError("Нужно хотя бы одно сообщение для модели")
        if self.settings.provider == "stub":
            return STUB_REPLY
        payload = {
            "model": self.settings.model,
            "messages": [dict(message) for message in messages],
            "temperature": self.settings.temperature,
            "stream": False,
        }
        data = self._request(
            "POST", "/chat/completions", self.settings.timeout_seconds, payload=payload
        )
        return _extract_reply(data)

    def is_available(self) -> bool:
        """Проверяет, отвечает ли сервер LLM: GET {base_url}/models с коротким таймаутом.

        Наличие нужной модели не проверяется: если она не скачана, chat() вызовет LLMError.
        """
        if self.settings.provider == "stub":
            return True
        timeout = min(AVAILABILITY_TIMEOUT_SECONDS, self.settings.timeout_seconds)
        try:
            self._request("GET", "/models", timeout)
        except LLMError:
            return False
        return True

    def _request(
        self,
        method: str,
        path: str,
        timeout: float,
        payload: dict[str, Any] | None = None,
    ) -> Any:
        """Выполняет HTTP-запрос к API модели и возвращает разобранный JSON."""
        url = f"{self.settings.base_url}{path}"
        headers = {"Authorization": f"Bearer {self.settings.api_key}"}
        try:
            with httpx.Client(
                transport=self._transport,
                timeout=timeout,
                trust_env=not is_loopback_url(self.settings.base_url),
            ) as http:
                response = http.request(method, url, headers=headers, json=payload)
                response.raise_for_status()
                return response.json()
        except httpx.TimeoutException as exc:
            raise LLMError(f"LLM не ответила за {timeout:g} с: {method} {url}") from exc
        except httpx.HTTPStatusError as exc:
            body = exc.response.text.strip()[:200]
            raise LLMError(
                f"LLM вернула HTTP {exc.response.status_code}: {method} {url} {body}".rstrip()
            ) from exc
        except httpx.HTTPError as exc:
            raise LLMError(f"Не удалось обратиться к LLM: {method} {url}: {exc}") from exc
        except ValueError as exc:
            raise LLMError(f"LLM вернула не JSON: {method} {url}") from exc


def is_loopback_url(url: str) -> bool:
    """Проверяет, что адрес указывает на этот компьютер (localhost, 127.0.0.0/8, ::1).

    Для таких адресов клиент не берёт прокси из окружения и системных настроек:
    иначе запрос к локальной модели мог бы уйти через прокси или VPN — и не дойти
    либо вынести текст запроса за пределы компьютера.
    """
    try:
        host = httpx.URL(url).host
    except httpx.InvalidURL:
        return False
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:  # не IP-адрес, а имя хоста
        return host == "localhost"


def _read_number(env: Mapping[str, str | None], name: str, default: float) -> float:
    """Читает число из переменной окружения; пустое или отсутствующее — default."""
    raw = (env.get(name) or "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        raise ValueError(f"Значение {name} должно быть числом, получено {raw!r}") from None
    if not math.isfinite(value):
        raise ValueError(f"Значение {name} должно быть конечным числом, получено {raw!r}")
    return value


def _extract_reply(data: Any) -> str:
    """Достаёт текст ответа из JSON chat completions: choices[0].message.content."""
    try:
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise LLMError(
            "Ответ LLM не в формате chat completions: нет choices[0].message.content"
        ) from exc
    if not isinstance(content, str) or not content.strip():
        raise LLMError("LLM вернула пустой ответ")
    return content.strip()
