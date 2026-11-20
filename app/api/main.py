"""Приложение FastAPI «Патентного радара»: GET /health и POST /search.

Запуск из корня репозитория:

    uvicorn app.api.main:app --reload

Документация Swagger: http://127.0.0.1:8000/docs.

При старте приложение читает корпус data/corpus/patents.jsonl и строит индекс BM25
(app/api/pipeline.py), а клиент языковой модели создаёт по переменным LLM_* из .env:
ошибка в корпусе или в настройках LLM видна сразу, а не на первом запросе.
POST /search ищет по корпусу и поясняет первые 5 результатов через LLM
(spec/tech/architecture.md, разделы 3 и 8).
"""

import math
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated, Any, Final

from dotenv import load_dotenv
from fastapi import Body, Depends, FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.openapi.models import Example
from fastapi.responses import JSONResponse

from app import __version__
from app.api.pipeline import SearchPipeline
from app.api.schemas import HealthResponse, SearchMode, SearchRequest, SearchResponse

# Переменные LLM_* из файла .env в корне репозитория; уже заданные переменные
# окружения не перезаписываются.
load_dotenv()

#: Режим поиска, который сообщает /health: с КТ2 — поиск BM25 по корпусу.
SEARCH_MODE: Final[SearchMode] = "bm25"

#: Основной пример: идея своими словами на тему корпуса «полив и влажность почвы» (A01G).
MAIN_QUERY: Final = (
    "Хочу, чтобы грядки на даче поливались сами: датчик в земле замечает, что почва "
    "пересохла, и включает воду, а если обещают дождь, полив не включается."
)

#: Готовые примеры тела POST /search для Swagger (/docs → Try it out).
SEARCH_EXAMPLES: Final[dict[str, Example]] = {
    "main": {
        "summary": "Автополив по влажности почвы",
        "value": {"query": MAIN_QUERY, "top_k": 10},
    },
    "bicycle": {
        "summary": "Складной велосипед",
        "value": {
            "query": (
                "Велосипед, рама которого складывается пополам на шарнире, чтобы его "
                "можно было занести в автобус или положить в багажник."
            ),
        },
    },
    "ipc": {
        "summary": "Фильтр по МПК A01G",
        "value": {"query": MAIN_QUERY, "ipc": "A01G"},
    },
    "year": {
        "summary": "Фильтр по году: с 2015",
        "value": {"query": MAIN_QUERY, "year_from": 2015},
    },
    "no_match": {
        "summary": "Фильтр МПК B65D — в корпусе таких нет: пустая выдача",
        "value": {"query": MAIN_QUERY, "ipc": "B65D"},
    },
    "too_short": {
        "summary": "Слишком короткий запрос: ответ 422",
        "value": {"query": "Умный полив"},
    },
}


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    """При старте: корпус, индекс BM25 и клиент LLM (SearchPipeline.from_corpus)."""
    application.state.pipeline = SearchPipeline.from_corpus()
    yield


app = FastAPI(
    title="Патентный радар API",
    version=__version__,
    description=(
        "Поиск похожих патентов РФ по описанию идеи изобретения: собственный BM25 по "
        "корпусу рефератов, пояснение первых 5 результатов — локальная языковая модель "
        "через Ollama. Это первичный поиск аналогов, а не юридическое заключение."
    ),
    lifespan=lifespan,
)


def get_pipeline(request: Request) -> SearchPipeline:
    """Конвейер поиска, собранный при старте; тесты подменяют его через dependency_overrides."""
    pipeline: SearchPipeline = request.app.state.pipeline
    return pipeline


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
    pipeline: Annotated[SearchPipeline, Depends(get_pipeline)],
) -> SearchResponse:
    """Находит патенты, похожие на описание идеи, и поясняет сходства и отличия.

    Некорректный запрос — ответ 422. Недоступность языковой модели — не ошибка:
    ответ 200 с выдачей и answer «Пояснение недоступно…».
    """
    return pipeline.search(request)


def _json_safe(value: Any) -> Any:
    """Заменяет NaN и бесконечности строками во вложенных списках и словарях."""
    if isinstance(value, float) and not math.isfinite(value):
        return str(value)
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    return value
