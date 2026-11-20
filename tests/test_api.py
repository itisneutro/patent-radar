"""Тесты HTTP API: GET /health и POST /search строго по контракту (КТ2).

Контракт: spec/tech/architecture.md, раздел «Контракт API»; проверка ответа модели и
деградация — раздел 8. Тесты не ходят в сеть и не требуют Ollama: TestClient вызывает
приложение внутри процесса, ответ языковой модели подменяет httpx.MockTransport или
провайдер stub, а фикстура no_network роняет тест при попытке настоящего соединения.

Поиск в тестах настоящий — BM25 с выбранной конфигурацией (app/search/config.py):
- интеграционные тесты конвейера идут на маленьком корпусе из трёх демо-записей
  data/sample/patents.jsonl (DEMO-001…DEMO-003, демонстрационные данные);
- старт приложения и согласованность API с тетрадкой benchmark проверяются на корпусе
  data/corpus/patents.jsonl. Номера патентов тесты берут из файлов data/corpus/ и
  benchmark/, в коде тестов реальных номеров нет.
"""

import json
import re
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from app import __version__
from app.api import answer as answer_module
from app.api.main import MAIN_QUERY, app, get_pipeline
from app.api.pipeline import SearchPipeline, load_corpus
from app.api.schemas import QUERY_TOO_SHORT_MESSAGE, SearchRequest
from app.llm.client import STUB_REPLY, LLMClient, LLMSettings
from app.llm.prompts import MAX_CONTEXT_DOCS, SYSTEM_PROMPT
from app.search.config import MIN_SCORE, build_engine

ROOT = Path(__file__).resolve().parents[1]
FRONTEND_MOCK = ROOT / "frontend" / "src" / "mock" / "search.json"
SAMPLE_CORPUS = ROOT / "data" / "sample" / "patents.jsonl"
CORPUS = ROOT / "data" / "corpus" / "patents.jsonl"
BENCHMARK_QUERIES = ROOT / "benchmark" / "queries.jsonl"

RESPONSE_FIELDS = {"query", "results", "answer"}
RESULT_FIELDS = {"id", "title", "abstract", "score", "ipc", "year"}
#: Ссылка на патент в answer: [ID], например [DEMO-001].
CITATION = re.compile(r"\[([^\[\]\s]+)\]")
#: Начало абзаца о патенте: «[ID] ».
PARAGRAPH_LEAD = re.compile(r"\[([^\[\]\s]+)\] ")
#: Код МПК без версии, например «A01G 25/16».
IPC_CODE = re.compile(r"[A-H]\d{2}[A-Z] \d{1,4}/\d{2,}")
DEMO_MARK = "Демонстрационные данные"

SENSOR_QUERY = (
    "Нужен беспроводной датчик влажности почвы, который работает от солнечной "
    "батареи и сам передаёт показания на контроллер полива."
)
TOO_SHORT = "Умный полив"
#: Порядок демо-записей по BM25 для MAIN_QUERY; все три совпадают с запросом по леммам.
DEMO_IDS = ["DEMO-002", "DEMO-001", "DEMO-003"]

DISCLAIMER = answer_module.ANSWER_DISCLAIMER
UNAVAILABLE = answer_module.compose(answer_module.LLM_UNAVAILABLE_ANSWER, demo=True)

Handler = Callable[[httpx.Request], httpx.Response]


# --- Фикстуры и помощники ---------------------------------------------------------------


@pytest.fixture(autouse=True)
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Запрещает настоящие HTTP-соединения: тесты обязаны обходиться без сети и Ollama."""

    def refuse(_transport: httpx.HTTPTransport, request: httpx.Request) -> httpx.Response:
        raise AssertionError(f"Тест попытался выйти в сеть: {request.method} {request.url}")

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", refuse)


@pytest.fixture(scope="module")
def client() -> Iterator[TestClient]:
    """Приложение внутри процесса; при старте оно строит индекс по data/corpus/patents.jsonl.

    LLM_PROVIDER=stub: клиент LLM при старте создаётся из окружения, а локальный .env
    не должен влиять на тесты. Конвейер для отдельных тестов подменяет use_pipeline.
    """
    if not CORPUS.is_file():
        pytest.skip("нет data/corpus/patents.jsonl: приложение строит индекс по корпусу при старте")
    with pytest.MonkeyPatch.context() as patch:
        for name in ("LLM_BASE_URL", "LLM_MODEL", "LLM_API_KEY", "LLM_TEMPERATURE", "LLM_TIMEOUT_SECONDS"):
            patch.delenv(name, raising=False)
        patch.setenv("LLM_PROVIDER", "stub")
        with TestClient(app) as test_client:
            yield test_client


def sample_records() -> list[dict[str, Any]]:
    """Демо-записи data/sample/patents.jsonl без поля source."""
    return [
        {key: value for key, value in record.items() if key != "source"}
        for record in load_corpus(SAMPLE_CORPUS)
    ]


def llm(handler: Handler | None = None, provider: str = "ollama") -> LLMClient:
    """Клиент LLM, у которого HTTP-запросы обрабатывает handler (httpx.MockTransport)."""
    transport = httpx.MockTransport(handler) if handler is not None else None
    return LLMClient(LLMSettings(provider=provider), transport=transport)  # type: ignore[arg-type]


def demo_pipeline(handler: Handler | None = None, provider: str = "ollama", min_score: float = 0.0) -> SearchPipeline:
    """Конвейер по трём демо-записям; порог 0 — в выдаче все записи, совпавшие хоть одним термином."""
    return SearchPipeline(sample_records(), llm(handler, provider), min_score=min_score)


@contextmanager
def use_pipeline(pipeline: SearchPipeline) -> Iterator[None]:
    """Подменяет конвейер POST /search на время блока with."""
    app.dependency_overrides[get_pipeline] = lambda: pipeline
    try:
        yield
    finally:
        app.dependency_overrides.pop(get_pipeline, None)


def completion(content: str, finish_reason: str = "stop", **usage: int) -> dict[str, Any]:
    """Ответ /chat/completions в формате OpenAI."""
    body: dict[str, Any] = {
        "id": "chatcmpl-test",
        "object": "chat.completion",
        "choices": [{"index": 0, "message": {"role": "assistant", "content": content}, "finish_reason": finish_reason}],
    }
    if usage:
        body["usage"] = usage
    return body


def reply_with(content: str, finish_reason: str = "stop", **usage: int) -> Handler:
    """Обработчик MockTransport: модель отвечает текстом content."""

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=completion(content, finish_reason, **usage))

    return handler


def explanation(*paragraphs: str) -> str:
    """Ожидаемый answer по демо-выдаче: пометка и вводный абзац, абзацы о патентах, дисклеймер."""
    return answer_module.compose(answer_module.ANSWER_INTRO, paragraphs, demo=True)


#: Ответ модели по формату промпта для демо-выдачи MAIN_QUERY (не реальный вывод).
GOOD_REPLY = (
    "[DEMO-002] Аналог. Полив зависит от влажности почвы и откладывается перед дождём. "
    "Отличие: используется прогноз погоды.\n\n"
    "[DEMO-001] Аналог. Клапан открывается, когда влажность почвы ниже порога. "
    "В реферате не упоминается прогноз осадков.\n\n"
    "[DEMO-003] Не аналог. Это беспроводной датчик влажности почвы без управления поливом."
)
GOOD_PARAGRAPHS = tuple(GOOD_REPLY.split("\n\n"))


def assert_search_contract(body: Any, top_k: int = 10) -> None:
    """Проверяет ответ POST /search по контракту: поля, типы, порядок, ссылки, абзацы."""
    assert isinstance(body, dict)
    assert set(body) == RESPONSE_FIELDS
    assert isinstance(body["query"], str)
    assert body["query"] == body["query"].strip()
    assert isinstance(body["answer"], str)
    assert body["answer"].strip()
    assert isinstance(body["results"], list)
    assert len(body["results"]) <= top_k

    for item in body["results"]:
        assert isinstance(item, dict)
        assert set(item) == RESULT_FIELDS
        for name in ("id", "title", "abstract"):
            assert isinstance(item[name], str)
            assert item[name].strip()
        assert isinstance(item["score"], int | float)
        assert not isinstance(item["score"], bool)
        assert item["score"] >= 0
        assert round(item["score"], 2) == item["score"]
        assert isinstance(item["ipc"], list)
        assert item["ipc"]
        assert all(isinstance(code, str) and IPC_CODE.fullmatch(code) for code in item["ipc"])
        assert isinstance(item["year"], int)
        assert not isinstance(item["year"], bool)
        assert 1900 <= item["year"] <= 2100

    ids = [item["id"] for item in body["results"]]
    assert len(set(ids)) == len(ids)
    ranking = [(-item["score"], item["id"]) for item in body["results"]]
    assert ranking == sorted(ranking)

    # answer: вводный абзац без ссылок, абзацы «[ID] ...» о патентах в порядке выдачи
    # (не больше одного на патент), последний абзац — дисклеймер.
    answer = body["answer"]
    assert set(CITATION.findall(answer)) <= set(ids)
    if not ids:
        return
    paragraphs = answer.split("\n\n")
    assert len(paragraphs) >= 2
    assert not CITATION.search(paragraphs[0])
    assert paragraphs[-1] == DISCLAIMER
    positions = []
    for paragraph in paragraphs[1:-1]:
        lead = PARAGRAPH_LEAD.match(paragraph)
        assert lead, f"абзац о патенте должен начинаться с [ID]: {paragraph[:60]}"
        positions.append(ids.index(lead.group(1)))
    assert positions == sorted(set(positions))
    if any(patent_id.startswith("DEMO-") for patent_id in ids):
        assert DEMO_MARK in paragraphs[0]


def post_search(client: TestClient, **payload: Any) -> dict[str, Any]:
    """Выполняет POST /search, ждёт 200 и проверяет ответ по контракту."""
    response = client.post("/search", json=payload)
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    assert_search_contract(body, top_k=payload.get("top_k", 10))
    assert body["query"] == payload["query"].strip()
    return body


def result_ids(body: dict[str, Any]) -> list[str]:
    """Возвращает id патентов выдачи в порядке выдачи."""
    return [item["id"] for item in body["results"]]


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    """Читает JSONL или пропускает тест, если файла нет."""
    if not path.is_file():
        pytest.skip(f"нет {path.relative_to(ROOT)}")
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def load_frontend_mock() -> dict[str, Any]:
    """Читает мок фронтенда или пропускает тест, если фронтенда нет в репозитории."""
    if not FRONTEND_MOCK.is_file():
        pytest.skip("нет frontend/src/mock/search.json: он появится вместе с фронтендом (Ника)")
    mock: dict[str, Any] = json.loads(FRONTEND_MOCK.read_text(encoding="utf-8"))
    return mock


def reject_json_constant(name: str) -> Any:
    """Для json.loads: NaN, Infinity и -Infinity в ответе — ошибка, в стандарте JSON их нет."""
    raise ValueError(f"в ответе не JSON-значение {name}")


# --- GET /health, документация и старт приложения ------------------------------------------


def test_health(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": "0.2.0", "mode": "bm25"}
    assert __version__ == "0.2.0"


def test_openapi_lists_only_contract_endpoints(client: TestClient) -> None:
    schema = client.get("/openapi.json").json()
    assert schema["info"]["title"] == "Патентный радар API"
    assert schema["info"]["version"] == __version__
    assert set(schema["paths"]) == {"/health", "/search"}
    assert client.get("/docs").status_code == 200


def test_startup_builds_index_from_corpus(client: TestClient) -> None:
    """При старте приложение читает весь корпус, строит индекс и создаёт клиент LLM из окружения."""
    pipeline: SearchPipeline = app.state.pipeline
    records = load_jsonl(CORPUS)
    assert pipeline.engine.index.n_docs == len(records) == len(pipeline.records)
    assert pipeline.min_score == MIN_SCORE
    assert pipeline.llm.settings.provider == "stub"


def test_search_on_corpus_with_stub_llm(client: TestClient) -> None:
    """Интеграция без подмены конвейера: BM25 по корпусу, порог, LLM_PROVIDER=stub."""
    body = post_search(client, query=MAIN_QUERY)
    assert len(body["results"]) == 10
    assert all(item["score"] >= MIN_SCORE for item in body["results"])
    assert all(re.fullmatch(r"RU\d+[A-Z]\d?", patent_id) for patent_id in result_ids(body))
    assert body["answer"] == answer_module.compose(STUB_REPLY)


# --- POST /search: пояснение модели ---------------------------------------------------------


def test_search_explained_answer(client: TestClient) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=completion(GOOD_REPLY, prompt_tokens=1640, completion_tokens=120))

    with use_pipeline(demo_pipeline(handler)):
        body = post_search(client, query=MAIN_QUERY)

    assert result_ids(body) == DEMO_IDS
    assert body["answer"] == explanation(*GOOD_PARAGRAPHS)
    [request] = requests
    assert str(request.url) == "http://localhost:11434/v1/chat/completions"
    sent = json.loads(request.content)
    assert sent["messages"][0] == {"role": "system", "content": SYSTEM_PROMPT}
    assert sent["messages"][1]["content"].startswith(f"Идея пользователя:\n{MAIN_QUERY}\n")
    assert sent["stream"] is False


def test_search_strips_query(client: TestClient) -> None:
    with use_pipeline(demo_pipeline(reply_with(GOOD_REPLY))):
        body = post_search(client, query=f"  \n{MAIN_QUERY}\t ")
    assert body["query"] == MAIN_QUERY


def test_prompt_gets_first_five_results(client: TestClient) -> None:
    """В промпт идут первые MAX_CONTEXT_DOCS = 5 результатов, в выдаче остаются все top_k."""
    sent: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(json.loads(request.content)["messages"][1]["content"])
        return httpx.Response(200, json=completion("Нет абзацев о патентах."))

    pipeline = SearchPipeline(load_jsonl(CORPUS), llm(handler))
    with use_pipeline(pipeline):
        body = post_search(client, query=MAIN_QUERY, top_k=10)
    ids = result_ids(body)
    assert len(ids) == 10
    [user_message] = sent
    context_ids = re.findall(r"^\[([^\[\]\s]+)\] ", user_message, flags=re.MULTILINE)
    assert context_ids == ids[:MAX_CONTEXT_DOCS]
    assert body["answer"] == answer_module.compose(answer_module.LLM_UNAVAILABLE_ANSWER)


def test_answer_check_removes_foreign_ids_and_reorders(client: TestClient) -> None:
    """Проверка ответа модели (architecture.md, раздел 8): чужие ID, порядок, повторы, вступление."""
    reply = (
        "Вот сравнение идеи с патентами:\n\n"
        "**[DEMO-003]** Не аналог. Это датчик влажности почвы.\n"
        "[DEMO-404] Аналог. Такого патента в выдаче нет.\n\n"
        "Продолжение абзаца о нём.\n\n"
        "1. [DEMO-001]: Аналог. Клапан по влажности почвы, как в [DEMO-404] и [DEMO-002].\n\n"
        "[DEMO-001] Аналог. Повторный абзац о том же патенте.\n\n"
        "[DEMO-002] Аналог. Полив откладывается перед дождём."
    )
    with use_pipeline(demo_pipeline(reply_with(reply))):
        body = post_search(client, query=MAIN_QUERY)
    assert body["answer"] == explanation(
        "[DEMO-002] Аналог. Полив откладывается перед дождём.",
        "[DEMO-001] Аналог. Клапан по влажности почвы, как в и [DEMO-002].",
        "[DEMO-003] Не аналог. Это датчик влажности почвы.",
    )
    assert "DEMO-404" not in body["answer"]


def test_paragraph_split_after_verdict_is_merged(client: TestClient) -> None:
    """Пояснение, перенесённое моделью на новую строку после вердикта, остаётся в том же абзаце."""
    reply = "[DEMO-002] Аналог.\n\nПолив откладывается перед дождём.\n[DEMO-001] Аналог.\nКлапан по датчику."
    with use_pipeline(demo_pipeline(reply_with(reply))):
        body = post_search(client, query=MAIN_QUERY, top_k=2)
    assert body["answer"] == explanation(
        "[DEMO-002] Аналог. Полив откладывается перед дождём.",
        "[DEMO-001] Аналог. Клапан по датчику.",
    )


def test_no_analogs_answer(client: TestClient) -> None:
    """У всех патентов вердикт «Не аналог.»: answer сообщает, что аналогов в корпусе нет; выдача остаётся."""
    reply = (
        "[DEMO-002] Не аналог. Это управление поливом.\n\n"
        "[DEMO-001] не аналог: это система полива.\n\n"
        "[DEMO-003] Не аналог. Это датчик почвы."
    )
    with use_pipeline(demo_pipeline(reply_with(reply))):
        outcome_body = post_search(client, query=MAIN_QUERY)
    assert result_ids(outcome_body) == DEMO_IDS
    paragraphs = outcome_body["answer"].split("\n\n")
    assert paragraphs[0] == f"{answer_module.DEMO_NOTE} {answer_module.NO_ANALOGS_INTRO}"
    assert paragraphs[0].removeprefix(answer_module.DEMO_NOTE + " ").startswith("Аналогов в корпусе не найдено")
    assert len(paragraphs) == 5


def test_one_analog_is_not_a_refusal() -> None:
    reply = "[DEMO-002] Аналог. Полив по датчику.\n\n[DEMO-001] Не аналог. Другое.\n\n[DEMO-003] Не аналог. Другое."
    outcome = demo_pipeline(reply_with(reply)).run(SearchRequest(query=MAIN_QUERY))
    assert outcome.status == "explained"
    assert outcome.verdicts == (True, False, False)


@pytest.mark.parametrize(
    "reply",
    [
        pytest.param("Аналогов среди найденных патентов нет.", id="no-paragraphs"),
        pytest.param("[DEMO-404] Аналог. Только чужой номер.", id="only-foreign-ids"),
    ],
)
def test_reply_without_patent_paragraphs_is_unavailable(client: TestClient, reply: str) -> None:
    """Не осталось ни одного абзаца о патентах — как при недоступной модели (сценарий А4)."""
    with use_pipeline(demo_pipeline(reply_with(reply))):
        body = post_search(client, query=MAIN_QUERY)
    assert result_ids(body) == DEMO_IDS
    assert body["answer"] == UNAVAILABLE
    assert not CITATION.search(body["answer"])


def test_truncated_reply_drops_last_paragraph() -> None:
    """finish_reason = length: ответ оборван по длине, последний абзац не дописан — он отбрасывается."""
    pipeline = demo_pipeline(reply_with(GOOD_REPLY, finish_reason="length"))
    outcome = pipeline.run(SearchRequest(query=MAIN_QUERY))
    assert outcome.status == "explained"
    assert outcome.response.answer == explanation(*GOOD_PARAGRAPHS[:2])


def test_prompt_truncated_by_server_is_unavailable(client: TestClient) -> None:
    """Сервер LLM обрезал промпт (символов на токен больше 4): пояснение отбрасывается."""
    handler = reply_with(GOOD_REPLY, prompt_tokens=100, completion_tokens=120)
    with use_pipeline(demo_pipeline(handler)):
        body = post_search(client, query=MAIN_QUERY)
    assert body["answer"] == UNAVAILABLE
    outcome = demo_pipeline(handler).run(SearchRequest(query=MAIN_QUERY))
    assert outcome.status == "context_truncated"
    assert outcome.llm_reply == GOOD_REPLY


def test_run_reports_details_for_benchmark() -> None:
    """run() отдаёт evaluate_answers.py то же, что видит пользователь, и подробности прогона."""
    outcome = demo_pipeline(reply_with(GOOD_REPLY, prompt_tokens=1640, completion_tokens=120)).run(
        SearchRequest(query=MAIN_QUERY)
    )
    assert outcome.status == "explained"
    assert outcome.context_ids == tuple(DEMO_IDS)
    assert outcome.verdicts == (True, True, False)
    assert outcome.llm_reply == GOOD_REPLY
    assert (outcome.prompt_tokens, outcome.completion_tokens) == (1640, 120)
    assert outcome.llm_seconds is not None and outcome.llm_seconds >= 0
    assert outcome.response.answer == explanation(*GOOD_PARAGRAPHS)


# --- POST /search: деградация -----------------------------------------------------------------


def raise_connect_error(request: httpx.Request) -> httpx.Response:
    raise httpx.ConnectError("Connection refused", request=request)


def raise_timeout(request: httpx.Request) -> httpx.Response:
    raise httpx.ReadTimeout("timed out", request=request)


@pytest.mark.parametrize(
    "handler",
    [
        pytest.param(raise_connect_error, id="ollama-not-running"),
        pytest.param(raise_timeout, id="timeout"),
        pytest.param(lambda _r: httpx.Response(404, json={"error": "model not found"}), id="model-not-found"),
        pytest.param(lambda _r: httpx.Response(500, text="Internal Server Error"), id="http-500"),
        pytest.param(lambda _r: httpx.Response(200, text="не JSON"), id="not-json"),
        pytest.param(lambda _r: httpx.Response(200, json=completion("   ")), id="empty-reply"),
    ],
)
def test_llm_failure_returns_results_without_explanation(client: TestClient, handler: Handler) -> None:
    """Сценарий А4: модель недоступна — ответ 200 с выдачей, без меток [ID] в answer."""
    with use_pipeline(demo_pipeline(handler)):
        body = post_search(client, query=MAIN_QUERY)
    assert result_ids(body) == DEMO_IDS
    assert body["answer"] == UNAVAILABLE
    assert not CITATION.search(body["answer"])
    assert demo_pipeline(handler).run(SearchRequest(query=MAIN_QUERY)).status == "llm_error"


def test_empty_results_do_not_call_llm(client: TestClient) -> None:
    def refuse(_request: httpx.Request) -> httpx.Response:
        raise AssertionError("при пустой выдаче LLM не вызывается")

    with use_pipeline(demo_pipeline(refuse)):
        body = post_search(client, query=MAIN_QUERY, ipc="B65D")
    assert body["results"] == []
    assert body["answer"] == answer_module.NO_RESULTS_ANSWER


def test_stub_provider_answer(client: TestClient) -> None:
    with use_pipeline(demo_pipeline(provider="stub")):
        body = post_search(client, query=MAIN_QUERY)
    assert result_ids(body) == DEMO_IDS
    assert body["answer"] == answer_module.compose(STUB_REPLY, demo=True)


# --- POST /search: валидация (422) ------------------------------------------------------------


@pytest.mark.parametrize(
    ("payload", "error_type"),
    [
        pytest.param({"query": TOO_SHORT}, "query_too_short", id="two-words"),
        pytest.param({"query": "   \n\t "}, "query_too_short", id="only-spaces"),
        pytest.param({"query": "полив — ?!"}, "query_too_short", id="punctuation-is-not-a-word"),
        pytest.param({"query": "а" * 1997 + " б в"}, "query_too_long", id="2001-chars"),
        pytest.param({"query": MAIN_QUERY, "mode": "fast"}, "extra_forbidden", id="extra-field"),
        pytest.param(
            {"query": MAIN_QUERY, "year_from": 2023, "year_to": 2019}, "year_range", id="year-from-gt-to"
        ),
        pytest.param({"query": MAIN_QUERY, "top_k": 0}, "greater_than_equal", id="top-k-0"),
        pytest.param({"query": MAIN_QUERY, "top_k": 21}, "less_than_equal", id="top-k-21"),
        pytest.param({"query": MAIN_QUERY, "top_k": "много"}, "int_parsing", id="top-k-not-int"),
        pytest.param({"query": MAIN_QUERY, "year_from": 1899}, "greater_than_equal", id="year-1899"),
        pytest.param({"query": MAIN_QUERY, "year_to": 2101}, "less_than_equal", id="year-2101"),
        pytest.param(
            {"query": MAIN_QUERY, "ipc": "A01G 25/16 G01N 27/22"}, "string_too_long", id="ipc-21-chars"
        ),
        pytest.param({"query": 42}, "string_type", id="query-not-string"),
        pytest.param({}, "missing", id="no-query"),
    ],
)
def test_invalid_request_returns_422(client: TestClient, payload: dict[str, Any], error_type: str) -> None:
    response = client.post("/search", json=payload)
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert isinstance(detail, list)
    assert error_type in {error["type"] for error in detail}


@pytest.mark.parametrize(
    ("payload", "error_type", "loc", "message"),
    [
        pytest.param(
            {"query": TOO_SHORT}, "query_too_short", ["body", "query"], QUERY_TOO_SHORT_MESSAGE, id="too-short"
        ),
        pytest.param(
            {"query": "а" * 1997 + " б в"},
            "query_too_long",
            ["body", "query"],
            "Запрос слишком длинный: сократите описание до 2000 символов.",
            id="too-long",
        ),
        pytest.param(
            {"query": MAIN_QUERY, "year_from": 2023, "year_to": 2019},
            "year_range",
            ["body"],
            "Начальный год не может быть больше конечного.",
            id="year-range",
        ),
    ],
)
def test_own_rules_use_interface_messages(
    client: TestClient, payload: dict[str, Any], error_type: str, loc: list[str], message: str
) -> None:
    """Тексты ошибок собственных правил совпадают с сообщениями интерфейса."""
    response = client.post("/search", json=payload)
    assert response.status_code == 422
    [error] = response.json()["detail"]
    assert error["type"] == error_type
    assert error["loc"] == loc
    assert error["msg"] == message


def test_malformed_json_returns_422(client: TestClient) -> None:
    response = client.post("/search", content=b'{"query": ', headers={"Content-Type": "application/json"})
    assert response.status_code == 422
    [error] = response.json()["detail"]
    assert error["type"] == "json_invalid"


def test_422_body_matches_contract_example(client: TestClient) -> None:
    """Ответ 422 — стандартный формат FastAPI, как в примере из spec/tech/architecture.md."""
    response = client.post("/search", json={"query": TOO_SHORT})
    assert response.status_code == 422
    assert response.json() == {
        "detail": [
            {
                "type": "query_too_short",
                "loc": ["body", "query"],
                "msg": QUERY_TOO_SHORT_MESSAGE,
                "input": TOO_SHORT,
                "ctx": {"min_words": 3},
            }
        ]
    }


@pytest.mark.parametrize(
    ("field", "raw_value", "error_type", "error_input"),
    [
        pytest.param("top_k", "NaN", "finite_number", "nan", id="top-k-nan"),
        pytest.param("year_from", "NaN", "finite_number", "nan", id="year-from-nan"),
        pytest.param("top_k", "Infinity", "finite_number", "inf", id="top-k-infinity"),
        pytest.param("year_to", "-Infinity", "finite_number", "-inf", id="year-to-minus-infinity"),
        pytest.param("top_k", "1e400", "finite_number", "inf", id="top-k-1e400"),
        pytest.param("query", "NaN", "string_type", "nan", id="query-nan"),
        pytest.param("ipc", "Infinity", "string_type", "inf", id="ipc-infinity"),
        pytest.param("mode", "NaN", "extra_forbidden", "nan", id="extra-field-nan"),
    ],
)
def test_nan_and_infinity_return_422(
    client: TestClient, field: str, raw_value: str, error_type: str, error_input: str
) -> None:
    """NaN, Infinity и -Infinity в теле — ответ 422 с валидным JSON, а не 500.

    json.loads принимает эти значения, хотя в стандарте JSON их нет, а число 1e400
    превращает в бесконечность. В ответе 422 такое значение input записано строкой.
    """
    fields = {"query": json.dumps(MAIN_QUERY), field: raw_value}
    content = "{" + ", ".join(f'"{name}": {value}' for name, value in fields.items()) + "}"
    response = client.post("/search", content=content, headers={"Content-Type": "application/json"})
    assert response.status_code == 422
    [error] = json.loads(response.text, parse_constant=reject_json_constant)["detail"]
    assert error["type"] == error_type
    assert error["input"] == error_input


@pytest.mark.parametrize(
    "query",
    [
        pytest.param("полив почвы датчиком", id="exactly-3-words"),
        pytest.param("а" * 1996 + " б в", id="exactly-2000-chars"),
        pytest.param("   " + "а" * 1996 + " б в   ", id="2000-chars-after-strip"),
    ],
)
def test_query_length_limits_are_inclusive(client: TestClient, query: str) -> None:
    with use_pipeline(demo_pipeline(provider="stub")):
        post_search(client, query=query)


# --- POST /search: top_k, фильтры, порог MIN_SCORE --------------------------------------------


@pytest.mark.parametrize(
    ("top_k", "expected"),
    [(1, DEMO_IDS[:1]), (2, DEMO_IDS[:2]), (3, DEMO_IDS), (20, DEMO_IDS)],
)
def test_top_k_limits_results(client: TestClient, top_k: int, expected: list[str]) -> None:
    with use_pipeline(demo_pipeline(provider="stub")):
        body = post_search(client, query=MAIN_QUERY, top_k=top_k)
    assert result_ids(body) == expected


@pytest.mark.parametrize(
    ("filters", "expected"),
    [
        pytest.param({"ipc": "A01G"}, ["DEMO-002", "DEMO-001"], id="ipc-A01G"),
        pytest.param({"ipc": "g01n"}, ["DEMO-001", "DEMO-003"], id="ipc-lowercase"),
        pytest.param({"ipc": "g01n 33"}, ["DEMO-003"], id="ipc-with-group"),
        pytest.param({"ipc": " a01g25/0 "}, ["DEMO-002"], id="ipc-without-spaces"),
        pytest.param({"ipc": "H04W"}, ["DEMO-003"], id="ipc-any-code"),
        pytest.param({"ipc": "B65D"}, [], id="ipc-no-match"),
        pytest.param({"ipc": "  "}, DEMO_IDS, id="ipc-blank-means-no-filter"),
        pytest.param({"ipc": None}, DEMO_IDS, id="ipc-null"),
        pytest.param({"year_from": 2022}, ["DEMO-003"], id="year-from-2022"),
        pytest.param({"year_to": 2020}, ["DEMO-001"], id="year-to-2020"),
        pytest.param({"year_from": 2021, "year_to": 2021}, ["DEMO-002"], id="equal-years"),
        pytest.param({"year_from": 2000, "year_to": 2010}, [], id="years-2000-2010"),
        pytest.param({"year_from": None, "year_to": None}, DEMO_IDS, id="years-null"),
        pytest.param({"ipc": "G01N", "year_from": 2020}, ["DEMO-003"], id="ipc-and-year"),
    ],
)
def test_filters(client: TestClient, filters: dict[str, Any], expected: list[str]) -> None:
    with use_pipeline(demo_pipeline(provider="stub")):
        body = post_search(client, query=MAIN_QUERY, **filters)
    assert result_ids(body) == expected
    if not expected:
        assert body["answer"] == answer_module.NO_RESULTS_ANSWER


def test_filters_apply_before_top_k(client: TestClient) -> None:
    """Фильтр применяется до обрезки до top_k: первый по score патент G01N — DEMO-001, а не пусто."""
    with use_pipeline(demo_pipeline(provider="stub")):
        body = post_search(client, query=MAIN_QUERY, ipc="G01N", top_k=1)
    assert result_ids(body) == ["DEMO-001"]


def test_min_score_threshold(client: TestClient) -> None:
    """В выдачу идут только документы со score >= MIN_SCORE; ниже порога всех — «ничего не найдено»."""
    scores = dict(build_engine(sample_records()).search(MAIN_QUERY))
    between = (scores["DEMO-001"] + scores["DEMO-003"]) / 2
    with use_pipeline(demo_pipeline(provider="stub", min_score=between)):
        assert result_ids(post_search(client, query=MAIN_QUERY)) == ["DEMO-002", "DEMO-001"]
    with use_pipeline(demo_pipeline(provider="stub", min_score=scores["DEMO-002"] + 0.01)):
        body = post_search(client, query=MAIN_QUERY)
    assert body["results"] == []
    assert body["answer"] == answer_module.NO_RESULTS_ANSWER


def test_scores_are_rounded_bm25(client: TestClient) -> None:
    """score в ответе — значение BM25 выбранной конфигурации, округлённое до 2 знаков."""
    scores = dict(build_engine(sample_records()).search(SENSOR_QUERY))
    with use_pipeline(demo_pipeline(provider="stub")):
        body = post_search(client, query=SENSOR_QUERY)
    assert {item["id"]: item["score"] for item in body["results"]} == {
        doc_id: round(score, 2) for doc_id, score in scores.items()
    }


# --- Согласованность с файлами других участников ------------------------------------------------


def test_api_ranking_matches_notebook(client: TestClient) -> None:
    """API ищет так же, как тетрадка benchmark: BM25 выбранной конфигурации и порог MIN_SCORE.

    По каждому запросу benchmark/queries.jsonl выдача POST /search (top_k = 10, без фильтров)
    совпадает с первыми 10 документами SearchEngine со score >= MIN_SCORE; порядок внутри
    равных после округления оценок — по id, как требует контракт.
    """
    queries = load_jsonl(BENCHMARK_QUERIES)
    pipeline: SearchPipeline = app.state.pipeline
    engine = build_engine(load_jsonl(CORPUS))
    for row in queries:
        expected = [(round(s, 2), d) for d, s in engine.search(row["query"]) if s >= MIN_SCORE]
        expected = sorted(expected, key=lambda pair: (-pair[0], pair[1]))[:10]
        got = pipeline.retrieve(SearchRequest(query=row["query"], top_k=10))
        assert [(item.score, item.id) for item in got] == expected, row["id"]


def test_frontend_mock_follows_contract() -> None:
    assert_search_contract(load_frontend_mock())


def test_frontend_mock_uses_sample_records() -> None:
    """Мок фронтенда — демо-записи data/sample/patents.jsonl (AGENTS.md, раздел 7)."""
    mock = load_frontend_mock()
    sample = {record["id"]: record for record in sample_records()}
    assert mock["results"]
    for item in mock["results"]:
        assert item["id"].startswith("DEMO-")
        assert {key: value for key, value in item.items() if key != "score"} == sample[item["id"]]


def test_sample_corpus_is_demo_only() -> None:
    records = load_jsonl(SAMPLE_CORPUS)
    assert {record.get("source") for record in records} == {"демонстрационные данные"}
    assert all(record["id"].startswith("DEMO-") for record in records)


def test_corpus_has_no_demo_records() -> None:
    """Демо-записи не смешиваются с реальным корпусом (AGENTS.md, раздел 7)."""
    records = load_jsonl(CORPUS)
    assert not [record["id"] for record in records if record["id"].startswith("DEMO-")]
    assert all(re.fullmatch(r"RU\d+[A-Z]\d?", record["id"]) for record in records)
