"""Pydantic-модели контракта API: запрос и ответ POST /search, ответ GET /health.

Правила валидации совпадают с контрактом (spec/tech/architecture.md, раздел
«Контракт API») и с проверками фронтенда. Нарушение правил FastAPI возвращает
как ответ 422 в стандартном формате {"detail": [...]}; ошибки собственных
правил имеют свои коды type: query_too_short, query_too_long, year_range.
"""

import re
from typing import Final, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from pydantic_core import PydanticCustomError

#: Слово запроса — последовательность букв и цифр (во фронтенде: /[\p{L}\p{N}]+/gu).
WORD_PATTERN: Final = re.compile(r"[^\W_]+")

MIN_QUERY_WORDS: Final = 3
MAX_QUERY_CHARS: Final = 2000
DEFAULT_TOP_K: Final = 10
MAX_TOP_K: Final = 20
MIN_YEAR: Final = 1900
MAX_YEAR: Final = 2100
MAX_IPC_CHARS: Final = 20

# Тексты ошибок собственных правил совпадают с сообщениями интерфейса
# (spec/product/scenarios.md, правила проверки ввода).
QUERY_TOO_SHORT_MESSAGE: Final = (
    "Запрос слишком короткий. Опишите идею хотя бы тремя словами: "
    "что это, из чего состоит и как работает."
)
QUERY_TOO_LONG_MESSAGE: Final = (
    "Запрос слишком длинный: сократите описание до {max_chars} символов."
)
YEAR_RANGE_MESSAGE: Final = "Начальный год не может быть больше конечного."

#: Режим поиска в ответе /health: "stub" — заглушка КТ1, "bm25" — настоящий поиск (КТ2).
SearchMode = Literal["stub", "bm25"]


def count_words(text: str) -> int:
    """Возвращает число слов в тексте; слово — последовательность букв и цифр."""
    return len(WORD_PATTERN.findall(text))


class SearchRequest(BaseModel):
    """Тело запроса POST /search. Лишние поля запрещены (ответ 422)."""

    model_config = ConfigDict(extra="forbid")

    query: str = Field(
        description=(
            "Описание идеи своими словами: после обрезки пробелов не меньше 3 слов "
            "и не больше 2000 символов."
        ),
    )
    top_k: int = Field(
        default=DEFAULT_TOP_K,
        ge=1,
        le=MAX_TOP_K,
        description="Сколько патентов вернуть, от 1 до 20.",
    )
    year_from: int | None = Field(
        default=None,
        ge=MIN_YEAR,
        le=MAX_YEAR,
        description="Год публикации не раньше указанного (включительно).",
    )
    year_to: int | None = Field(
        default=None,
        ge=MIN_YEAR,
        le=MAX_YEAR,
        description="Год публикации не позже указанного (включительно).",
    )
    ipc: str | None = Field(
        default=None,
        max_length=MAX_IPC_CHARS,
        description=(
            "Префикс кода МПК, например «A01G» или «G01N 33». Регистр и пробелы "
            "не учитываются; патент проходит, если с префикса начинается любой его код."
        ),
    )

    @field_validator("query")
    @classmethod
    def _validate_query(cls, value: str) -> str:
        """Обрезает пробелы по краям и проверяет длину и число слов запроса."""
        value = value.strip()
        if len(value) > MAX_QUERY_CHARS:
            raise PydanticCustomError(
                "query_too_long",
                QUERY_TOO_LONG_MESSAGE,
                {"max_chars": MAX_QUERY_CHARS},
            )
        if count_words(value) < MIN_QUERY_WORDS:
            raise PydanticCustomError(
                "query_too_short",
                QUERY_TOO_SHORT_MESSAGE,
                {"min_words": MIN_QUERY_WORDS},
            )
        return value

    @field_validator("ipc")
    @classmethod
    def _validate_ipc(cls, value: str | None) -> str | None:
        """Обрезает пробелы; пустой префикс МПК означает «без фильтра» (None)."""
        if value is None:
            return None
        return value.strip() or None

    @model_validator(mode="after")
    def _validate_years(self) -> Self:
        """Проверяет, что начало диапазона лет не позже его конца."""
        if (
            self.year_from is not None
            and self.year_to is not None
            and self.year_from > self.year_to
        ):
            raise PydanticCustomError(
                "year_range",
                YEAR_RANGE_MESSAGE,
                {"year_from": self.year_from, "year_to": self.year_to},
            )
        return self


class PatentResult(BaseModel):
    """Патент в выдаче POST /search: ровно шесть полей."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(
        description=(
            "Номер патента вида RU<номер><код вида> или DEMO-001 для демонстрационных данных."
        ),
    )
    title: str = Field(description="Название (INID 54).")
    abstract: str = Field(description="Реферат (INID 57).")
    score: float = Field(
        ge=0,
        description="Оценка BM25, округлена до 2 знаков; сравнима только внутри одной выдачи.",
    )
    ipc: list[str] = Field(description="Коды МПК (INID 51) вида «A01G 25/16», без версии.")
    year: int = Field(description="Год публикации (INID 45).")


class SearchResponse(BaseModel):
    """Ответ POST /search: ровно три поля верхнего уровня."""

    model_config = ConfigDict(extra="forbid")

    query: str = Field(description="Запрос пользователя после обрезки пробелов.")
    results: list[PatentResult] = Field(
        description="Патенты по убыванию score (при равенстве — по id), не больше top_k.",
    )
    answer: str = Field(
        description=(
            "Пояснение простым текстом: абзацы через пустую строку, ссылки вида [ID] "
            "только на патенты из results, последний абзац — дисклеймер."
        ),
    )


class HealthResponse(BaseModel):
    """Ответ GET /health."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["ok"] = Field(description="Сервис запущен и отвечает.")
    version: str = Field(description="Версия приложения (app.__version__).")
    mode: SearchMode = Field(
        description="Режим поиска: stub — заглушка КТ1, bm25 — поиск по корпусу (с КТ2).",
    )
