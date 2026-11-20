"""Поиск по корпусу целиком: документы корпуса -> индекс -> BM25 по тексту запроса.

Один и тот же класс используют тетрадка benchmark/experiments.py (прогоны блоков A, B, C)
и API (app/api), поэтому эксперименты и POST /search ищут одинаково. Выбранная по
результатам экспериментов конфигурация и порог MIN_SCORE — в app/search/config.py.

Документ = название × title_boost + реферат (+ коды МПК записи при ipc_tokens) —
spec/tech/rag.md, разделы 2 и 8.2 (опыты C1–C3).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field, replace

from .bm25 import BM25, SearchResult
from .index import InvertedIndex
from .preprocess import PreprocessConfig, expand_wordforms, extract_ipc_codes, normalize, preprocess


@dataclass(frozen=True)
class SearchConfig:
    """Конфигурация поиска (spec/tech/rag.md, раздел 8).

    Attributes:
        preprocess: флаги предобработки (блок A).
        k1, b: параметры BM25 (блок B).
        title_boost: сколько раз токены названия входят в документ (опыт C1).
        ipc_tokens: добавлять коды МПК записи к токенам документа (опыт C2).
        extra_stopwords: дополнительные стоп-слова в форме лемм (опыт C3).
    """

    preprocess: PreprocessConfig = field(default_factory=PreprocessConfig)
    k1: float = 1.2
    b: float = 0.75
    title_boost: int = 1
    ipc_tokens: bool = False
    extra_stopwords: tuple[str, ...] = ()


class SearchEngine:
    """Индекс и BM25 по записям корпуса для одной конфигурации.

    Example (демо-корпус из трёх записей):
        >>> engine = SearchEngine([
        ...     {"id": "DEMO-1", "title": "Полив по датчику", "abstract": "Датчик влажности почвы.", "ipc": ["A01G 25/16"]},
        ...     {"id": "DEMO-2", "title": "Зонт", "abstract": "Складной зонт.", "ipc": ["A45B 19/00"]},
        ... ])
        >>> [doc_id for doc_id, _ in engine.search("датчик влажности почвы")]
        ['DEMO-1']
    """

    def __init__(self, records: Iterable[Mapping], config: SearchConfig | None = None) -> None:
        self.config = config or SearchConfig()
        extra = self.config.extra_stopwords
        if not extra:
            self._extra = frozenset()
        elif self.config.preprocess.lemmatize:
            self._extra = frozenset(extra)
        else:
            self._extra = expand_wordforms(extra)
        documents = []
        for record in records:
            tokens = preprocess(record["title"], self.config.preprocess) * self.config.title_boost
            tokens += preprocess(record["abstract"], self.config.preprocess)
            if self.config.ipc_tokens:
                tokens += extract_ipc_codes(normalize(" ".join(record.get("ipc", []))))[0]
            documents.append((record["id"], [t for t in tokens if t not in self._extra]))
        self.index = InvertedIndex.build(documents)
        self.bm25 = BM25(self.index, k1=self.config.k1, b=self.config.b)

    def with_params(self, k1: float, b: float) -> SearchEngine:
        """Тот же индекс с другими k1 и b (блок B): документы заново не обрабатываются."""
        clone = object.__new__(SearchEngine)
        clone.config = replace(self.config, k1=k1, b=b)
        clone._extra = self._extra
        clone.index = self.index
        clone.bm25 = BM25(self.index, k1=k1, b=b)
        return clone

    def query_tokens(self, query: str) -> list[str]:
        """Токены запроса — та же предобработка, что у документов."""
        return [t for t in preprocess(query, self.config.preprocess) if t not in self._extra]

    def search(self, query: str, top_k: int | None = None) -> list[SearchResult]:
        """Документы со score > 0 по убыванию score (при равенстве — по id); top_k=None — все."""
        return self.bm25.search(self.query_tokens(query), top_k=top_k)

    def score_upper_bound(self, query: str) -> float:
        """Σ IDF(t) · (k1 + 1) по терминам запроса — верхняя граница score (rag.md, раздел 7)."""
        return sum(self.bm25.idf(t) for t in set(self.query_tokens(query))) * (self.config.k1 + 1)
