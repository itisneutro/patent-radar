"""Ранжирование BM25 поверх собственного инвертированного индекса.

Формулы (spec/tech/rag.md, раздел 6) — вариант с неотрицательным IDF, как в Lucene:

    IDF(t)      = ln(1 + (N - n_t + 0.5) / (n_t + 0.5))
    score(D, Q) = sum over t in set(Q) of
                  IDF(t) * tf(t, D) * (k1 + 1) / (tf(t, D) + k1 * (1 - b + b * |D| / avgdl))

N — число документов, n_t — число документов с термином t (df), tf(t, D) — сколько раз
t встречается в D, |D| — длина D в токенах после предобработки, avgdl — средняя длина.
По умолчанию k1 = 1.2 (насыщение частоты термина), b = 0.75 (нормировка длины).
Термины запроса берутся множеством: повтор слова в запросе не увеличивает score.

Статус КТ2: реализовано; примеры в докстрингах — doctest-проверки (tests/test_search.py).

Ограничения методички: BM25 — только собственная реализация; rank-bm25, Whoosh,
Elasticsearch, TfidfVectorizer из scikit-learn в роли поиска и любые готовые поисковые
индексы запрещены.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

from .index import InvertedIndex

SearchResult = tuple[str, float]
"""Результат поиска: (doc_id, score); score не округлён (округление до 2 знаков — в API)."""


class BM25:
    """BM25 по InvertedIndex.

    Example (КТ2; игрушечный индекс: D1 — 3 токена, D2 — 2 токена, avgdl = 2.5):
        >>> index = InvertedIndex.build([("D1", ["полив", "почва", "полив"]), ("D2", ["датчик", "почва"])])
        >>> bm25 = BM25(index)
        >>> [(doc_id, round(score, 4)) for doc_id, score in bm25.search(["полив", "почва"])]
        [('D1', 1.0709), ('D2', 0.1986)]
    """

    def __init__(self, index: InvertedIndex, k1: float = 1.2, b: float = 0.75) -> None:
        """Запоминает индекс и параметры.

        Args:
            index: построенный InvertedIndex.
            k1: насыщение частоты термина, k1 >= 0; при k1 = 0 учитывается только
                наличие термина, чем больше k1, тем ближе к линейному росту по tf.
            b: нормировка длины документа, 0 <= b <= 1; 0 — длина не учитывается,
                1 — полная нормировка на |D| / avgdl.

        Raises:
            ValueError: k1 < 0 или b вне [0, 1].

        Example:
            >>> BM25(InvertedIndex.build([("D1", ["полив"])]), k1=0.9, b=0.5).k1
            0.9
        """
        if k1 < 0:
            raise ValueError(f"k1 должен быть >= 0, получено {k1}")
        if not 0 <= b <= 1:
            raise ValueError(f"b должен быть в [0, 1], получено {b}")
        self.index = index
        self.k1 = float(k1)
        self.b = float(b)

    def idf(self, term: str) -> float:
        """IDF(t) = ln(1 + (N - n_t + 0.5) / (n_t + 0.5)) — всегда больше 0.

        В классическом варианте без «1 +» термин из большей половины документов получил
        бы отрицательный вес. При N = 3: термин из 1 документа — 0.9808, из 2 — 0.4700,
        из 3 — 0.1335.

        Args:
            term: термин после предобработки.

        Returns:
            Значение IDF.

        Example:
            >>> bm25 = BM25(InvertedIndex.build([("D1", ["полив", "почва"]), ("D2", ["датчик", "почва"])]))
            >>> round(bm25.idf("полив"), 4), round(bm25.idf("почва"), 4)
            (0.6931, 0.1823)
        """
        n_docs, n_t = self.index.n_docs, self.index.doc_freq(term)
        return math.log(1 + (n_docs - n_t + 0.5) / (n_t + 0.5))

    def score(self, query_tokens: Sequence[str], doc_id: str) -> float:
        """score(D, Q) для одного документа (для отладки и проверки формулы).

        Args:
            query_tokens: токены запроса после preprocess; повторы не учитываются.
            doc_id: документ из индекса.

        Returns:
            Значение BM25; 0.0, если общих терминов нет.

        Example:
            >>> bm25 = BM25(InvertedIndex.build([("D1", ["полив", "почва", "полив"]), ("D2", ["датчик", "почва"])]))
            >>> round(bm25.score(["почва"], "D2"), 4), bm25.score(["датчик"], "D1")
            (0.1986, 0.0)
        """
        total = 0.0
        for term in set(query_tokens):
            tf = self.index.postings(term).get(doc_id, 0)
            if tf:
                total += self._term_score(self.idf(term), tf, self.index.doc_length(doc_id))
        return total

    def search(self, query_tokens: Sequence[str], top_k: int | None = 10) -> list[SearchResult]:
        """Ранжирует документы, в которых есть хотя бы один термин запроса.

        - Перебираются только postings терминов из set(query_tokens).
        - Документы со score = 0 не возвращаются.
        - Порядок — по убыванию score, при равенстве — по doc_id (по возрастанию).
        - top_k=None — все документы со score > 0: API сначала применяет фильтры по году
          и МПК и порог MIN_SCORE, потом обрезает до top_k (spec/tech/rag.md, раздел 7).
        - Score не округляется; округление до 2 знаков и итоговая сортировка
          (-round(score, 2), id) — в API, чтобы порядок совпадал с контрактом.

        Args:
            query_tokens: токены запроса после preprocess.
            top_k: сколько результатов вернуть; None — все.

        Returns:
            Список пар (doc_id, score).

        Example:
            >>> bm25 = BM25(InvertedIndex.build([("D1", ["полив", "почва", "полив"]), ("D2", ["датчик", "почва"])]))
            >>> [(doc_id, round(score, 4)) for doc_id, score in bm25.search(["почва"], top_k=1)]  # tf равны, D2 короче
            [('D2', 0.1986)]
            >>> bm25.search(["зонт"])
            []
        """
        scores: dict[str, float] = {}
        for term in set(query_tokens):
            postings = self.index.postings(term)
            if not postings:
                continue
            idf = self.idf(term)
            for doc_id, tf in postings.items():
                scores[doc_id] = scores.get(doc_id, 0.0) + self._term_score(idf, tf, self.index.doc_length(doc_id))
        ranked = sorted(((d, s) for d, s in scores.items() if s > 0), key=lambda item: (-item[1], item[0]))
        return ranked if top_k is None else ranked[:top_k]

    def _term_score(self, idf: float, tf: int, doc_length: int) -> float:
        """Вклад одного термина: IDF · tf · (k1 + 1) / (tf + k1 · (1 − b + b · |D| / avgdl))."""
        avgdl = self.index.avgdl
        norm = 1 - self.b + self.b * doc_length / avgdl if avgdl > 0 else 1.0
        return idf * tf * (self.k1 + 1) / (tf + self.k1 * norm)
