"""Тесты HTTP API: GET /health и POST /search строго по контракту.

Контракт: spec/tech/architecture.md, раздел «Контракт API». Тесты не ходят в сеть
и не требуют Ollama: TestClient вызывает приложение внутри процесса, а на КТ1
POST /search отвечает заглушкой (app/api/stub.py). Тесты с пометкой
«заглушка КТ1» на КТ2 заменяются проверками поиска BM25 по корпусу.
"""

import json
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from app import __version__
from app.api import stub
from app.api.main import app
from app.api.schemas import QUERY_TOO_SHORT_MESSAGE
from app.llm.client import LLMClient

ROOT = Path(__file__).resolve().parents[1]
FRONTEND_MOCK = ROOT / "frontend" / "src" / "mock" / "search.json"
SAMPLE_CORPUS = ROOT / "data" / "sample" / "patents.jsonl"

RESPONSE_FIELDS = {"query", "results", "answer"}
RESULT_FIELDS = {"id", "title", "abstract", "score", "ipc", "year"}
#: Ссылка на патент в answer: [ID], например [DEMO-001].
CITATION = re.compile(r"\[([^\[\]\s]+)\]")
#: Начало абзаца о патенте: «[ID] ».
PARAGRAPH_LEAD = re.compile(r"\[([^\[\]\s]+)\] ")
#: Код МПК без версии, например «A01G 25/16».
IPC_CODE = re.compile(r"[A-H]\d{2}[A-Z] \d{1,4}/\d{2,}")
DEMO_MARK = "Демонстрационные данные"

MAIN = stub.EXAMPLE_QUERIES["main"]
SENSOR = stub.EXAMPLE_QUERIES["sensor"]
NO_MATCH = stub.EXAMPLE_QUERIES["no_match"]
TOO_SHORT = stub.EXAMPLE_QUERIES["too_short"]
DEMO_IDS = ["DEMO-002", "DEMO-001", "DEMO-003"]


@pytest.fixture(scope="module")
def client() -> Iterator[TestClient]:
    """Клиент приложения внутри процесса, без сети и без запуска uvicorn."""
    with TestClient(app) as test_client:
        yield test_client


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
    assert paragraphs[-1] == stub.ANSWER_DISCLAIMER
    positions = []
    for paragraph in paragraphs[1:-1]:
        lead = PARAGRAPH_LEAD.match(paragraph)
        assert lead, f"абзац о патенте должен начинаться с [ID]: {paragraph[:60]}"
        positions.append(ids.index(lead.group(1)))
    assert positions == sorted(set(positions))
    if any(patent_id.startswith("DEMO-") for patent_id in ids):
        assert DEMO_MARK in answer


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


def expected_answer(ids: list[str]) -> str:
    """Собирает ожидаемый answer заглушки КТ1: ровно по абзацу на каждый патент выдачи."""
    if not ids:
        return stub.NO_RESULTS_ANSWER
    explanations = [stub.EXPLANATIONS[patent_id] for patent_id in ids]
    return "\n\n".join([stub.ANSWER_INTRO, *explanations, stub.ANSWER_DISCLAIMER])


def load_frontend_mock() -> dict[str, Any]:
    """Читает мок фронтенда или пропускает тест, если фронтенда ещё нет в репозитории."""
    if not FRONTEND_MOCK.is_file():
        pytest.skip("нет frontend/src/mock/search.json: он появится вместе с фронтендом (Ника)")
    mock: dict[str, Any] = json.loads(FRONTEND_MOCK.read_text(encoding="utf-8"))
    return mock


def reject_json_constant(name: str) -> Any:
    """Для json.loads: NaN, Infinity и -Infinity в ответе — ошибка, в стандарте JSON их нет."""
    raise ValueError(f"в ответе не JSON-значение {name}")


# --- GET /health и документация ---------------------------------------------------


def test_health(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": "0.1.0", "mode": "stub"}
    assert __version__ == "0.1.0"


def test_openapi_lists_only_contract_endpoints(client: TestClient) -> None:
    schema = client.get("/openapi.json").json()
    assert schema["info"]["title"] == "Патентный радар API"
    assert schema["info"]["version"] == __version__
    assert set(schema["paths"]) == {"/health", "/search"}
    assert client.get("/docs").status_code == 200


# --- POST /search: формат ответа ----------------------------------------------------


def test_search_main_query(client: TestClient) -> None:
    body = post_search(client, query=MAIN)
    assert result_ids(body) == DEMO_IDS
    assert [item["score"] for item in body["results"]] == [12.47, 9.85, 4.31]
    assert body["answer"] == expected_answer(DEMO_IDS)
    assert body["answer"].startswith(DEMO_MARK)


def test_search_strips_query(client: TestClient) -> None:
    body = post_search(client, query=f"  \n{MAIN}\t ")
    assert body["query"] == MAIN


def test_search_sensor_query(client: TestClient) -> None:
    body = post_search(client, query=SENSOR)
    assert result_ids(body) == DEMO_IDS


def test_search_no_match_returns_empty_results(client: TestClient) -> None:
    body = post_search(client, query=NO_MATCH)
    assert body["results"] == []
    assert body["answer"] == stub.NO_RESULTS_ANSWER


def test_search_does_not_call_llm(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """На КТ1 /search не обращается к LLM и вообще не выходит в сеть."""

    def refuse(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("на КТ1 POST /search не должен вызывать LLM и ходить в сеть")

    monkeypatch.setattr(LLMClient, "chat", refuse)
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", refuse)
    body = post_search(client, query=MAIN)
    assert result_ids(body) == DEMO_IDS


# --- POST /search: валидация (422) ---------------------------------------------------


@pytest.mark.parametrize(
    ("payload", "error_type"),
    [
        pytest.param({"query": TOO_SHORT}, "query_too_short", id="two-words"),
        pytest.param({"query": "   \n\t "}, "query_too_short", id="only-spaces"),
        pytest.param({"query": "полив — ?!"}, "query_too_short", id="punctuation-is-not-a-word"),
        pytest.param({"query": "а" * 1997 + " б в"}, "query_too_long", id="2001-chars"),
        pytest.param({"query": MAIN, "mode": "fast"}, "extra_forbidden", id="extra-field"),
        pytest.param(
            {"query": MAIN, "year_from": 2023, "year_to": 2019}, "year_range", id="year-from-gt-to"
        ),
        pytest.param({"query": MAIN, "top_k": 0}, "greater_than_equal", id="top-k-0"),
        pytest.param({"query": MAIN, "top_k": 21}, "less_than_equal", id="top-k-21"),
        pytest.param({"query": MAIN, "top_k": "много"}, "int_parsing", id="top-k-not-int"),
        pytest.param({"query": MAIN, "year_from": 1899}, "greater_than_equal", id="year-1899"),
        pytest.param({"query": MAIN, "year_to": 2101}, "less_than_equal", id="year-2101"),
        pytest.param(
            {"query": MAIN, "ipc": "A01G 25/16 G01N 27/22"}, "string_too_long", id="ipc-21-chars"
        ),
        pytest.param({"query": 42}, "string_type", id="query-not-string"),
        pytest.param({}, "missing", id="no-query"),
    ],
)
def test_invalid_request_returns_422(
    client: TestClient, payload: dict[str, Any], error_type: str
) -> None:
    response = client.post("/search", json=payload)
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert isinstance(detail, list)
    assert error_type in {error["type"] for error in detail}


@pytest.mark.parametrize(
    ("payload", "error_type", "loc", "message"),
    [
        pytest.param(
            {"query": TOO_SHORT},
            "query_too_short",
            ["body", "query"],
            QUERY_TOO_SHORT_MESSAGE,
            id="too-short",
        ),
        pytest.param(
            {"query": "а" * 1997 + " б в"},
            "query_too_long",
            ["body", "query"],
            "Запрос слишком длинный: сократите описание до 2000 символов.",
            id="too-long",
        ),
        pytest.param(
            {"query": MAIN, "year_from": 2023, "year_to": 2019},
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
    response = client.post(
        "/search", content=b'{"query": ', headers={"Content-Type": "application/json"}
    )
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
    fields = {"query": json.dumps(MAIN), field: raw_value}
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
    post_search(client, query=query)


def test_equal_years_are_allowed(client: TestClient) -> None:
    body = post_search(client, query=MAIN, year_from=2021, year_to=2021)
    assert result_ids(body) == ["DEMO-002"]


# --- POST /search: top_k и фильтры (заглушка КТ1) -----------------------------------


@pytest.mark.parametrize(
    ("top_k", "expected"),
    [
        (1, ["DEMO-002"]),
        (2, ["DEMO-002", "DEMO-001"]),
        (3, DEMO_IDS),
        (20, DEMO_IDS),
    ],
)
def test_top_k_limits_results(client: TestClient, top_k: int, expected: list[str]) -> None:
    body = post_search(client, query=MAIN, top_k=top_k)
    assert result_ids(body) == expected
    assert body["answer"] == expected_answer(expected)


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
        pytest.param({"year_from": 2000, "year_to": 2010}, [], id="years-2000-2010"),
        pytest.param({"year_from": None, "year_to": None}, DEMO_IDS, id="years-null"),
        pytest.param({"ipc": "G01N", "year_from": 2020}, ["DEMO-003"], id="ipc-and-year"),
    ],
)
def test_filters(client: TestClient, filters: dict[str, Any], expected: list[str]) -> None:
    body = post_search(client, query=MAIN, **filters)
    assert result_ids(body) == expected
    assert body["answer"] == expected_answer(expected)


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        pytest.param("Предупреждение о сильных ДОЖДЯХ для дачников", DEMO_IDS, id="uppercase"),
        pytest.param("Складной велосипед с электроприводом и фарой", [], id="other-topic"),
    ],
)
def test_demo_topic_heuristic(client: TestClient, query: str, expected: list[str]) -> None:
    body = post_search(client, query=query)
    assert result_ids(body) == expected


def test_demo_topic_ignores_case_and_yo() -> None:
    """Перед поиском основ запрос приводится к нижнему регистру, «ё» заменяется на «е»."""
    assert stub.is_demo_topic("ТЁПЛИЦА")
    assert not stub.is_demo_topic("Складной зонт")


# --- Согласованность с файлами других участников ---------------------------------------


def test_frontend_mock_follows_contract() -> None:
    assert_search_contract(load_frontend_mock())


def test_stub_matches_frontend_mock(client: TestClient) -> None:
    """Заглушка КТ1: на запрос из мока бэкенд отвечает тем же JSON, что и мок фронтенда."""
    mock = load_frontend_mock()
    assert post_search(client, query=mock["query"]) == mock


def test_stub_patents_match_sample_corpus() -> None:
    """Заглушка КТ1: демо-записи в коде совпадают с data/sample/patents.jsonl без поля source."""
    if not SAMPLE_CORPUS.is_file():
        pytest.skip("нет data/sample/patents.jsonl: он появится вместе с демо-данными (Бобур)")
    lines = SAMPLE_CORPUS.read_text(encoding="utf-8").splitlines()
    records = [json.loads(line) for line in lines if line.strip()]
    assert {record.get("source") for record in records} == {"демонстрационные данные"}
    without_source = [{k: v for k, v in record.items() if k != "source"} for record in records]
    assert without_source == list(stub.DEMO_PATENTS)
