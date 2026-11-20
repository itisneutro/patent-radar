"""Конвейер POST /search (КТ2): BM25 по корпусу, фильтры, порог, пояснение LLM.

Порядок — spec/tech/architecture.md, разделы 3 и 8:

1. BM25 оценивает весь корпус data/corpus/patents.jsonl с выбранной конфигурацией
   (app/search/config.py). Индекс строится один раз — при старте API.
2. В выдачу идут документы со score >= MIN_SCORE, прошедшие фильтры по году
   публикации и префиксу МПК. Фильтры применяются до обрезки до top_k.
3. score округляется до 2 знаков; выдача сортируется по убыванию score, при
   равенстве — по id, и обрезается до top_k.
4. Пустая выдача: answer = NO_RESULTS_ANSWER, LLM не вызывается.
5. Первые MAX_CONTEXT_DOCS = 5 результатов идут в промпт (app/llm/prompts.py);
   ответ модели проверяет app/api/answer.py.
6. LLMError, обрезанный сервером промпт или ответ без единого абзаца о патентах —
   выдача без пояснения: answer = LLM_UNAVAILABLE_ANSWER и дисклеймер, код 200.

Тот же конвейер вызывает benchmark/evaluate_answers.py (метод run): метрики ответов
считаются ровно по тому, что получает пользователь.
"""

import json
import logging
import time
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, Literal, Self

from app.api.answer import (
    ANSWER_INTRO,
    LLM_UNAVAILABLE_ANSWER,
    NO_ANALOGS_INTRO,
    NO_RESULTS_ANSWER,
    check_reply,
    compose,
)
from app.api.schemas import PatentResult, SearchRequest, SearchResponse
from app.llm.client import STUB_REPLY, LLMClient, LLMError
from app.llm.prompts import MAX_CONTEXT_DOCS, build_messages
from app.search.config import MIN_SCORE, build_engine
from app.search.engine import SearchEngine

logger = logging.getLogger(__name__)

ROOT: Final = Path(__file__).resolve().parents[2]

#: Корпус рефератов (data/sample/README.md, раздел о корпусе).
CORPUS_PATH: Final = ROOT / "data" / "corpus" / "patents.jsonl"

#: Поля записи корпуса, которые попадают в выдачу; поле source в ответ не идёт.
RECORD_FIELDS: Final = ("id", "title", "abstract", "ipc", "year")

#: Больше символов на токен, чем бывает в русском тексте: значит, сервер обрезал промпт.
#: У qwen2.5 на промптах benchmark — 2,6–3,1 символа на токен, у обрезанных Ollama — 5,7–5,9
#: (spec/tech/architecture.md, раздел 6).
MAX_CHARS_PER_TOKEN: Final = 4.0

#: Что стало с пояснением:
#: explained — пояснение модели; no_analogs — у всех патентов вердикт «Не аналог.»;
#: no_results — пустая выдача, LLM не вызывалась; llm_error — LLMError;
#: context_truncated — сервер обрезал промпт; llm_invalid — в ответе нет абзацев о патентах;
#: llm_stub — провайдер stub, модель не вызывалась.
AnswerStatus = Literal[
    "explained", "no_analogs", "no_results", "llm_error", "context_truncated", "llm_invalid", "llm_stub"
]


@dataclass(frozen=True)
class SearchOutcome:
    """Ответ POST /search и подробности прогона для benchmark/evaluate_answers.py.

    Attributes:
        response: ответ API по контракту.
        status: что стало с пояснением (AnswerStatus).
        context_ids: id патентов, переданных в промпт, в порядке выдачи.
        verdicts: вердикты абзацев answer о патентах (True — «Аналог.», False — «Не аналог.»).
        removed_ids: id из ответа модели не из промпта — их абзацы и ссылки убраны.
        llm_reply: сырой ответ модели; None, если модель не вызывалась или не ответила.
        llm_seconds: время ответа модели в секундах; None, если модель не вызывалась.
        prompt_tokens, completion_tokens: usage из ответа сервера LLM.
        error: текст LLMError или причина, по которой пояснение отброшено.
    """

    response: SearchResponse
    status: AnswerStatus
    context_ids: tuple[str, ...] = ()
    verdicts: tuple[bool | None, ...] = ()
    removed_ids: tuple[str, ...] = ()
    llm_reply: str | None = None
    llm_seconds: float | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    error: str | None = None


def load_corpus(path: Path = CORPUS_PATH) -> list[dict[str, Any]]:
    """Читает корпус JSONL: по записи на строку, поля из RECORD_FIELDS обязательны.

    Raises:
        FileNotFoundError: файла нет.
        ValueError: строка не JSON, нет обязательного поля, повтор id или корпус пуст.
    """
    records: list[dict[str, Any]] = []
    seen: set[str] = set()
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path}, строка {number}: не JSON ({exc.msg})") from exc
        missing = [name for name in RECORD_FIELDS if name not in record]
        if missing:
            raise ValueError(f"{path}, строка {number}: нет полей {', '.join(missing)}")
        if record["id"] in seen:
            raise ValueError(f"{path}, строка {number}: id {record['id']} повторяется")
        seen.add(record["id"])
        records.append(record)
    if not records:
        raise ValueError(f"{path}: корпус пуст")
    return records


def normalize_ipc(code: str) -> str:
    """Приводит код или префикс МПК к виду для сравнения: без пробелов, прописными.

    Example:
        >>> normalize_ipc("g01n 33"), normalize_ipc("G01N 33/24")
        ('G01N33', 'G01N33/24')
    """
    return "".join(code.split()).upper()


def matches_filters(
    record: Mapping[str, Any],
    year_from: int | None = None,
    year_to: int | None = None,
    ipc: str | None = None,
) -> bool:
    """Проверяет запись по фильтрам года публикации (включительно) и префикса МПК.

    Фильтр со значением None не применяется. Префикс МПК подходит, если с него
    начинается хотя бы один код записи (без учёта регистра и пробелов).
    """
    if year_from is not None and record["year"] < year_from:
        return False
    if year_to is not None and record["year"] > year_to:
        return False
    if ipc is not None:
        prefix = normalize_ipc(ipc)
        return any(normalize_ipc(code).startswith(prefix) for code in record["ipc"])
    return True


class SearchPipeline:
    """Поиск BM25 по корпусу и пояснение выдачи языковой моделью."""

    def __init__(
        self,
        records: Iterable[Mapping[str, Any]],
        llm: LLMClient,
        min_score: float = MIN_SCORE,
        engine: SearchEngine | None = None,
    ) -> None:
        """Строит индекс по записям корпуса.

        Args:
            records: записи корпуса с полями RECORD_FIELDS.
            llm: клиент языковой модели.
            min_score: порог score (rag.md, раздел 7).
            engine: готовый движок по тем же записям; по умолчанию — build_engine(records).
        """
        self.records = {record["id"]: dict(record) for record in records}
        self.engine = engine or build_engine(self.records.values())
        self.llm = llm
        self.min_score = min_score

    @classmethod
    def from_corpus(cls, path: Path = CORPUS_PATH, llm: LLMClient | None = None) -> Self:
        """Конвейер по файлу корпуса; клиент LLM по умолчанию — из переменных окружения LLM_*."""
        return cls(load_corpus(path), llm if llm is not None else LLMClient.from_env())

    def retrieve(self, request: SearchRequest) -> list[PatentResult]:
        """Выдача без пояснения: BM25, порог MIN_SCORE, фильтры, округление, сортировка, top_k."""
        found = []
        for doc_id, score in self.engine.search(request.query):
            if score < self.min_score:
                break
            record = self.records[doc_id]
            if matches_filters(record, request.year_from, request.year_to, request.ipc):
                found.append(
                    PatentResult(**{name: record[name] for name in RECORD_FIELDS}, score=round(score, 2))
                )
        found.sort(key=lambda result: (-result.score, result.id))
        return found[: request.top_k]

    def run(self, request: SearchRequest) -> SearchOutcome:
        """Полный конвейер: выдача и answer вместе с подробностями прогона."""
        results = self.retrieve(request)
        if not results:
            return SearchOutcome(self._response(request, results, NO_RESULTS_ANSWER), "no_results")

        demo = any(result.id.startswith("DEMO-") for result in results)
        context = results[:MAX_CONTEXT_DOCS]
        context_ids = tuple(result.id for result in context)
        messages = build_messages(request.query, [result.model_dump() for result in context])
        started = time.perf_counter()
        try:
            reply = self.llm.complete(messages)
        except LLMError as exc:
            logger.warning("Пояснение недоступно: %s", exc)
            return SearchOutcome(
                self._response(request, results, compose(LLM_UNAVAILABLE_ANSWER, demo=demo)),
                "llm_error",
                context_ids,
                llm_seconds=round(time.perf_counter() - started, 2),
                error=str(exc),
            )
        seconds = round(time.perf_counter() - started, 2)
        details = {
            "context_ids": context_ids,
            "llm_reply": reply.text,
            "llm_seconds": seconds,
            "prompt_tokens": reply.prompt_tokens,
            "completion_tokens": reply.completion_tokens,
        }

        if self.llm.settings.provider == "stub":
            return SearchOutcome(
                self._response(request, results, compose(STUB_REPLY, demo=demo)), "llm_stub", **details
            )

        prompt_chars = sum(len(message["content"]) for message in messages)
        if reply.prompt_tokens and prompt_chars / reply.prompt_tokens > MAX_CHARS_PER_TOKEN:
            error = (
                f"сервер LLM обрезал промпт: {prompt_chars} символов, {reply.prompt_tokens} токенов; "
                "окно контекста модели меньше промпта — создайте модель из Modelfile "
                "(spec/tech/architecture.md, раздел 6)"
            )
            logger.warning("Пояснение отброшено: %s", error)
            return SearchOutcome(
                self._response(request, results, compose(LLM_UNAVAILABLE_ANSWER, demo=demo)),
                "context_truncated",
                error=error,
                **details,
            )

        checked = check_reply(reply.text, context_ids)
        paragraphs = list(checked.paragraphs)
        verdicts = list(checked.verdicts)
        if reply.finish_reason == "length" and paragraphs:
            # Ответ оборван по длине: последний абзац, скорее всего, не дописан.
            paragraphs.pop()
            verdicts.pop()
        if checked.removed_ids:
            logger.warning("Из пояснения убраны ссылки не на выдачу: %d", len(checked.removed_ids))
        if not paragraphs:
            error = "в ответе модели нет ни одного абзаца о патентах из промпта"
            logger.warning("Пояснение отброшено: %s", error)
            return SearchOutcome(
                self._response(request, results, compose(LLM_UNAVAILABLE_ANSWER, demo=demo)),
                "llm_invalid",
                removed_ids=checked.removed_ids,
                error=error,
                **details,
            )

        no_analogs = all(item is False for item in verdicts)
        intro = NO_ANALOGS_INTRO if no_analogs else ANSWER_INTRO
        return SearchOutcome(
            self._response(request, results, compose(intro, paragraphs, demo=demo)),
            "no_analogs" if no_analogs else "explained",
            verdicts=tuple(verdicts),
            removed_ids=checked.removed_ids,
            **details,
        )

    def search(self, request: SearchRequest) -> SearchResponse:
        """Ответ POST /search."""
        return self.run(request).response

    @staticmethod
    def _response(request: SearchRequest, results: Sequence[PatentResult], answer: str) -> SearchResponse:
        return SearchResponse(query=request.query, results=list(results), answer=answer)
