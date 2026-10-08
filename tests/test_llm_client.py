"""Тесты клиента LLM (app/llm/client.py) без сети и без Ollama.

HTTP-запросы перехватывает httpx.MockTransport, провайдер stub в сеть не ходит.
Фикстура no_network роняет тест, если клиент всё же попробует открыть
настоящее соединение.
"""

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import pytest
from dotenv import dotenv_values

from app.llm.client import (
    DEFAULT_MODEL,
    OLLAMA_API_KEY,
    OLLAMA_BASE_URL,
    STUB_REPLY,
    LLMClient,
    LLMError,
    LLMSettings,
    is_loopback_url,
)

ROOT = Path(__file__).resolve().parents[1]
LLM_VARIABLES = (
    "LLM_PROVIDER",
    "LLM_BASE_URL",
    "LLM_MODEL",
    "LLM_API_KEY",
    "LLM_TEMPERATURE",
    "LLM_TIMEOUT_SECONDS",
)
MESSAGES = [
    {"role": "system", "content": "Отвечай по-русски, только по приведённым рефератам."},
    {"role": "user", "content": "Чем похожи найденные патенты на мою идею?"},
]
LM_STUDIO = LLMSettings(
    provider="openai_compatible",
    base_url="http://localhost:1234/v1",
    model="qwen2.5-7b-instruct",
    api_key="lm-studio",
    temperature=0.5,
    timeout_seconds=30,
)
MODEL_NOT_FOUND = {"error": {"message": 'model "qwen2.5:7b" not found'}}

Handler = Callable[[httpx.Request], httpx.Response]


@pytest.fixture(autouse=True)
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Запрещает настоящие HTTP-соединения: тесты обязаны обходиться без сети."""

    def refuse(_transport: httpx.HTTPTransport, request: httpx.Request) -> httpx.Response:
        raise AssertionError(f"Тест попытался выйти в сеть: {request.method} {request.url}")

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", refuse)


@pytest.fixture
def clean_env(monkeypatch: pytest.MonkeyPatch) -> pytest.MonkeyPatch:
    """Убирает переменные LLM_*, в том числе загруженные из локального .env."""
    for name in LLM_VARIABLES:
        monkeypatch.delenv(name, raising=False)
    return monkeypatch


def mock_client(handler: Handler, settings: LLMSettings | None = None) -> LLMClient:
    """Клиент, у которого все HTTP-запросы обрабатывает функция handler."""
    return LLMClient(settings or LLMSettings(), transport=httpx.MockTransport(handler))


def completion(content: Any) -> dict[str, Any]:
    """Ответ /chat/completions в формате OpenAI с заданным текстом."""
    return {
        "id": "chatcmpl-test",
        "object": "chat.completion",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
    }


def respond(status_code: int, **kwargs: Any) -> Handler:
    """Обработчик MockTransport, который на любой запрос отвечает одинаково."""

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, **kwargs)

    return handler


def raise_connect_error(request: httpx.Request) -> httpx.Response:
    """Сервер не запущен: соединение отклонено."""
    raise httpx.ConnectError("Connection refused", request=request)


def raise_timeout(request: httpx.Request) -> httpx.Response:
    """Сервер не ответил вовремя."""
    raise httpx.ReadTimeout("timed out", request=request)


# --- Настройки и переключатель провайдера -------------------------------------------


@pytest.mark.usefixtures("clean_env")
def test_defaults_without_environment() -> None:
    settings = LLMSettings.from_env()
    assert settings == LLMSettings()
    assert settings.provider == "ollama"
    assert settings.base_url == OLLAMA_BASE_URL == "http://localhost:11434/v1"
    assert settings.model == DEFAULT_MODEL == "qwen2.5:7b"
    assert settings.api_key == OLLAMA_API_KEY == "ollama"
    assert settings.temperature == 0.2
    assert settings.timeout_seconds == 60


def test_env_example_matches_defaults() -> None:
    """.env.example содержит ровно переменные LLM_* и задаёт значения по умолчанию."""
    env_example = ROOT / ".env.example"
    if not env_example.is_file():
        pytest.skip("нет .env.example в корне репозитория")
    values = dotenv_values(env_example)
    assert set(values) == set(LLM_VARIABLES)
    assert LLMSettings.from_env(values) == LLMSettings()


def test_provider_switch_via_environment(clean_env: pytest.MonkeyPatch) -> None:
    clean_env.setenv("LLM_PROVIDER", "openai_compatible")
    clean_env.setenv("LLM_BASE_URL", "http://localhost:1234/v1/")
    clean_env.setenv("LLM_API_KEY", "lm-studio")
    clean_env.setenv("LLM_MODEL", "qwen2.5-7b-instruct")
    clean_env.setenv("LLM_TEMPERATURE", "0.5")
    clean_env.setenv("LLM_TIMEOUT_SECONDS", "30")
    assert LLMSettings.from_env() == LM_STUDIO

    clean_env.setenv("LLM_PROVIDER", "stub")
    assert LLMSettings.from_env().provider == "stub"

    clean_env.setenv("LLM_PROVIDER", "  Ollama ")
    assert LLMSettings.from_env().provider == "ollama"


def test_ollama_allows_custom_address(clean_env: pytest.MonkeyPatch) -> None:
    clean_env.setenv("LLM_BASE_URL", "http://127.0.0.1:11500/v1")
    clean_env.setenv("LLM_MODEL", "qwen2.5:3b")
    settings = LLMSettings.from_env()
    assert settings.provider == "ollama"
    assert settings.base_url == "http://127.0.0.1:11500/v1"
    assert settings.model == "qwen2.5:3b"
    assert settings.api_key == "ollama"


def test_empty_values_fall_back_to_defaults() -> None:
    environ = {name: "" for name in LLM_VARIABLES}
    assert LLMSettings.from_env(environ) == LLMSettings()


@pytest.mark.parametrize("missing", ["LLM_BASE_URL", "LLM_API_KEY"])
def test_openai_compatible_requires_url_and_key(missing: str) -> None:
    environ = {
        "LLM_PROVIDER": "openai_compatible",
        "LLM_BASE_URL": "http://localhost:1234/v1",
        "LLM_API_KEY": "lm-studio",
    }
    del environ[missing]
    with pytest.raises(ValueError, match=missing):
        LLMSettings.from_env(environ)


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("LLM_PROVIDER", "openai"),
        ("LLM_BASE_URL", "localhost:11434/v1"),
        ("LLM_TEMPERATURE", "горячо"),
        ("LLM_TEMPERATURE", "-0.1"),
        ("LLM_TEMPERATURE", "2.5"),
        ("LLM_TIMEOUT_SECONDS", "0"),
        ("LLM_TIMEOUT_SECONDS", "минута"),
        ("LLM_TIMEOUT_SECONDS", "nan"),
    ],
)
def test_invalid_settings_are_rejected(name: str, value: str) -> None:
    with pytest.raises(ValueError, match=name):
        LLMSettings.from_env({name: value})


def test_api_key_is_hidden_in_repr() -> None:
    settings = LLMSettings(provider="openai_compatible", api_key="secret-key")
    assert "secret-key" not in repr(settings)


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("http://localhost:11434/v1", True),
        ("http://127.0.0.1:1234/v1", True),
        ("http://127.0.0.2:1234/v1", True),
        ("http://[::1]:11434/v1", True),
        ("http://[0:0:0:0:0:0:0:1]:11434/v1", True),
        ("http://192.168.1.10:11434/v1", False),
        ("http://127.evil.example/v1", False),
        ("https://llm.example.com/v1", False),
    ],
)
def test_is_loopback_url(url: str, expected: bool) -> None:
    assert is_loopback_url(url) is expected


@pytest.mark.parametrize(
    ("base_url", "trust_env"),
    [
        ("http://localhost:11434/v1", False),
        ("http://127.0.0.1:1234/v1", False),
        ("http://[::1]:11434/v1", False),
        ("http://192.168.1.10:11434/v1", True),
    ],
)
def test_env_proxy_only_for_other_computers(
    monkeypatch: pytest.MonkeyPatch, base_url: str, trust_env: bool
) -> None:
    """К адресам этого компьютера клиент идёт без прокси из окружения (trust_env=False).

    С MockTransport httpx прокси из окружения не использует при любом trust_env,
    поэтому тест проверяет сам аргумент: обёртка над httpx.Client.__init__
    запоминает его и вызывает настоящий конструктор.
    """
    original_init = httpx.Client.__init__
    seen: list[bool] = []

    def spy_init(self: httpx.Client, *args: Any, **kwargs: Any) -> None:
        seen.append(kwargs.get("trust_env", True))
        original_init(self, *args, **kwargs)

    monkeypatch.setattr(httpx.Client, "__init__", spy_init)
    client = mock_client(respond(200, json=completion("Ответ.")), LLMSettings(base_url=base_url))
    assert client.chat(MESSAGES) == "Ответ."
    assert client.is_available()
    assert seen == [trust_env, trust_env]


# --- Провайдер stub ------------------------------------------------------------------


def test_stub_provider_works_without_network() -> None:
    client = LLMClient(LLMSettings(provider="stub"))
    assert client.chat(MESSAGES) == STUB_REPLY
    assert client.is_available()


# --- Формат запроса /chat/completions -------------------------------------------------


def test_chat_request_format_for_ollama() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=completion("  [DEMO-001] Похож принцип работы.\n"))

    reply = mock_client(handler).chat(MESSAGES)

    assert reply == "[DEMO-001] Похож принцип работы."
    [request] = requests
    assert request.method == "POST"
    assert str(request.url) == "http://localhost:11434/v1/chat/completions"
    assert request.headers["Authorization"] == "Bearer ollama"
    assert request.headers["Content-Type"] == "application/json"
    assert json.loads(request.content) == {
        "model": "qwen2.5:7b",
        "messages": MESSAGES,
        "temperature": 0.2,
        "stream": False,
    }


def test_chat_uses_openai_compatible_settings() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=completion("Ответ."))

    assert mock_client(handler, LM_STUDIO).chat(MESSAGES) == "Ответ."
    [request] = requests
    assert str(request.url) == "http://localhost:1234/v1/chat/completions"
    assert request.headers["Authorization"] == "Bearer lm-studio"
    body = json.loads(request.content)
    assert body["model"] == "qwen2.5-7b-instruct"
    assert body["temperature"] == 0.5
    assert body["stream"] is False


def test_chat_requires_messages() -> None:
    client = mock_client(respond(200, json=completion("Ответ.")))
    with pytest.raises(ValueError, match="сообщение"):
        client.chat([])


# --- Ошибки → LLMError ------------------------------------------------------------------


@pytest.mark.parametrize(
    "handler",
    [
        pytest.param(raise_connect_error, id="server-is-down"),
        pytest.param(raise_timeout, id="timeout"),
        pytest.param(respond(500, text="boom"), id="http-500"),
        pytest.param(respond(404, json=MODEL_NOT_FOUND), id="model-not-found"),
        pytest.param(respond(200, text="<html></html>"), id="not-json"),
        pytest.param(respond(200, json={}), id="no-choices"),
        pytest.param(respond(200, json={"choices": []}), id="empty-choices"),
        pytest.param(respond(200, json=completion(None)), id="null-content"),
        pytest.param(respond(200, json=completion("  ")), id="blank-content"),
    ],
)
def test_chat_errors_raise_llm_error(handler: Handler) -> None:
    with pytest.raises(LLMError):
        mock_client(handler).chat(MESSAGES)


def test_llm_error_explains_http_status() -> None:
    with pytest.raises(LLMError, match="404") as error:
        mock_client(respond(404, json=MODEL_NOT_FOUND)).chat(MESSAGES)
    assert "not found" in str(error.value)


# --- Проверка доступности -----------------------------------------------------------------


def test_is_available_requests_models() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"object": "list", "data": [{"id": "qwen2.5:7b"}]})

    assert mock_client(handler).is_available()
    [request] = requests
    assert request.method == "GET"
    assert str(request.url) == "http://localhost:11434/v1/models"
    assert request.headers["Authorization"] == "Bearer ollama"


@pytest.mark.parametrize(
    "handler",
    [
        pytest.param(raise_connect_error, id="server-is-down"),
        pytest.param(raise_timeout, id="timeout"),
        pytest.param(respond(503, text="loading"), id="http-503"),
    ],
)
def test_is_available_false_on_errors(handler: Handler) -> None:
    assert mock_client(handler).is_available() is False
