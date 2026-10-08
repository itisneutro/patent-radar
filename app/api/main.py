"""Приложение FastAPI «Патентного радара»: GET /health и POST /search.

Запуск из корня репозитория:

    uvicorn app.api.main:app --reload

Документация Swagger: http://127.0.0.1:8000/docs.

На КТ1 POST /search отвечает заглушкой (app/api/stub.py) на демонстрационных
данных: BM25 и языковая модель не вызываются. На КТ2 при старте приложения будет
строиться индекс BM25 из data/corpus/patents.jsonl, а пояснение будет писать LLM
через app/llm/client.py; формат ответа при этом не меняется.
"""

import math
from typing import Annotated, Any, Final

from dotenv import load_dotenv
from fastapi import Body, FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.openapi.models import Example
from fastapi.responses import JSONResponse

from app import __version__
from app.api.schemas import HealthResponse, SearchMode, SearchRequest, SearchResponse
from app.api.stub import EXAMPLE_QUERIES, search_stub

# Переменные LLM_* из файла .env в корне репозитория; уже заданные переменные
# окружения не перезаписываются. На КТ1 их никто не читает, они нужны с КТ2.
load_dotenv()

#: Режим поиска, который сообщает /health: "stub" на КТ1, "bm25" после КТ2.
SEARCH_MODE: Final[SearchMode] = "stub"

#: Готовые примеры тела POST /search для Swagger (/docs → Try it out).
SEARCH_EXAMPLES: Final[dict[str, Example]] = {
    "main": {
        "summary": "Основной демо-запрос: 3 результата",
        "value": {"query": EXAMPLE_QUERIES["main"], "top_k": 10},
    },
    "sensor": {
        "summary": "Датчик влажности: 3 результата",
        "value": {"query": EXAMPLE_QUERIES["sensor"]},
    },
    "ipc": {
        "summary": "Фильтр по МПК G01N: DEMO-001, DEMO-003",
        "value": {"query": EXAMPLE_QUERIES["main"], "ipc": "G01N"},
    },
    "year": {
        "summary": "Фильтр по году с 2022: DEMO-003",
        "value": {"query": EXAMPLE_QUERIES["main"], "year_from": 2022},
    },
    "no_match": {
        "summary": "Ничего не найдено: пустая выдача",
        "value": {"query": EXAMPLE_QUERIES["no_match"]},
    },
    "too_short": {
        "summary": "Слишком короткий запрос: ответ 422",
        "value": {"query": EXAMPLE_QUERIES["too_short"]},
    },
}

app = FastAPI(
    title="Патентный радар API",
    version=__version__,
    description=(
        "Поиск похожих патентов РФ по описанию идеи изобретения. "
        "КТ1: POST /search возвращает заглушку на демонстрационных данных, "
        "поиск BM25 и языковая модель не вызываются. "
        "Это первичный поиск аналогов, а не юридическое заключение."
    ),
)


@app.exception_handler(RequestValidationError)
async def validation_error(_request: Request, exc: RequestValidationError) -> JSONResponse:
    """Отвечает 422 в стандартном формате FastAPI {"detail": [...]}.

    Отличие от обработчика по умолчанию одно: значения NaN, Infinity и -Infinity
    из тела запроса (json.loads их принимает, хотя в стандарте JSON их нет)
    записываются в ответ строками "nan", "inf" и "-inf". Иначе ответ 422 нельзя
    записать в JSON, и клиент вместо него получает 500.
    """
    return JSONResponse(
        status_code=422,
        content={"detail": _json_safe(jsonable_encoder(exc.errors()))},
    )


@app.get("/health", summary="Проверка работоспособности")
def health() -> HealthResponse:
    """Сообщает, что сервис запущен, его версию и режим поиска."""
    return HealthResponse(status="ok", version=__version__, mode=SEARCH_MODE)


@app.post(
    "/search",
    summary="Поиск похожих патентов",
    response_description="Выдача по убыванию score и пояснение answer",
)
def search(
    request: Annotated[SearchRequest, Body(openapi_examples=SEARCH_EXAMPLES)],
) -> SearchResponse:
    """Находит патенты, похожие на описание идеи, и поясняет сходства и отличия.

    КТ1: ответ заглушки (app/api/stub.py). Некорректный запрос — ответ 422.
    """
    return search_stub(request)


def _json_safe(value: Any) -> Any:
    """Заменяет NaN и бесконечности строками во вложенных списках и словарях."""
    if isinstance(value, float) and not math.isfinite(value):
        return str(value)
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    return value
