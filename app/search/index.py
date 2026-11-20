"""Собственный инвертированный индекс для BM25.

Структуры данных (spec/tech/rag.md, раздел 5):

- postings: term -> {doc_id: tf} — в каких документах встречается термин и сколько раз;
- doc_lengths: doc_id -> |D| — длина документа в токенах после предобработки;
- N = число документов, avgdl = средняя длина, df(t) = len(postings[t]).

Индекс хранит только id и счётчики; название, реферат, МПК и год API держит отдельно,
по id. Токены документа = preprocess(title) + preprocess(abstract) из
app.search.preprocess, с той же PreprocessConfig, что и для запросов. Индекс строится
при старте API из data/corpus/patents.jsonl (сотни документов — доли секунды);
сохранение в JSON — опционально.

Статус КТ2: реализовано; примеры в докстрингах — doctest-проверки (tests/test_search.py).

Ограничения методички: только собственная реализация; готовые поисковые индексы
(Whoosh, Elasticsearch и т. п.) не используются.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from types import MappingProxyType

DocId = str
"""Идентификатор документа: "RU<номер><код вида>" или "DEMO-001"."""

Term = str
"""Термин индекса — токен после предобработки."""

Postings = dict[DocId, int]
"""Список вхождений термина: doc_id -> tf (сколько раз термин встречается в документе)."""


class InvertedIndex:
    """Инвертированный индекс term -> {doc_id: tf} с длинами документов.

    Поля:
        _postings: term -> {doc_id: tf};
        _doc_lengths: doc_id -> |D|;
        _total_length: сумма длин документов (для avgdl).

    Example (КТ2; игрушечный индекс):
        >>> index = InvertedIndex.build([("D1", ["полив", "почва", "полив"]), ("D2", ["датчик", "почва"])])
        >>> dict(index.postings("полив"))
        {'D1': 2}
        >>> index.doc_freq("почва"), index.n_docs, index.avgdl, index.doc_length("D1")
        (2, 2, 2.5, 3)
    """

    _postings: dict[Term, Postings]
    _doc_lengths: dict[DocId, int]
    _total_length: int

    def __init__(self) -> None:
        """Создаёт пустой индекс; документы добавляются через add_document или build."""
        self._postings = {}
        self._doc_lengths = {}
        self._total_length = 0

    @classmethod
    def build(cls, documents: Iterable[tuple[DocId, Sequence[Term]]]) -> InvertedIndex:
        """Строит индекс по документам.

        Args:
            documents: пары (doc_id, токены документа после предобработки), например
                [("DEMO-001", ["система", "автоматический", "полив", ...]), ...].

        Returns:
            Заполненный индекс.

        Raises:
            ValueError: если doc_id повторяется.

        Example:
            >>> InvertedIndex.build([("D1", ["полив"]), ("D2", ["почва"])]).n_docs
            2
        """
        index = cls()
        for doc_id, tokens in documents:
            index.add_document(doc_id, tokens)
        return index

    def add_document(self, doc_id: DocId, tokens: Sequence[Term]) -> None:
        """Добавляет документ: обновляет postings, длину документа и сумму длин.

        Документ без токенов допустим (|D| = 0): он учитывается в N, но не найдётся
        ни по одному запросу.

        Args:
            doc_id: идентификатор документа.
            tokens: токены после предобработки; повторы увеличивают tf.

        Raises:
            ValueError: если doc_id уже есть в индексе.

        Example:
            >>> index = InvertedIndex()
            >>> index.add_document("D1", ["полив", "полив", "почва"])
            >>> index.postings("полив")["D1"], index.doc_length("D1")
            (2, 3)
        """
        if doc_id in self._doc_lengths:
            raise ValueError(f"документ {doc_id!r} уже есть в индексе")
        for term in tokens:
            postings = self._postings.setdefault(term, {})
            postings[doc_id] = postings.get(doc_id, 0) + 1
        self._doc_lengths[doc_id] = len(tokens)
        self._total_length += len(tokens)

    def postings(self, term: Term) -> Mapping[DocId, int]:
        """Возвращает вхождения термина: {doc_id: tf}.

        Args:
            term: термин после предобработки.

        Returns:
            Отображение doc_id -> tf; пустое, если термина нет. Изменять его нельзя.

        Example:
            >>> dict(InvertedIndex.build([("D1", ["полив", "полив"])]).postings("полив"))
            {'D1': 2}
        """
        return MappingProxyType(self._postings.get(term, {}))

    def doc_freq(self, term: Term) -> int:
        """df(t) — число документов, в которых есть термин (n_t в формуле IDF).

        Args:
            term: термин после предобработки.

        Returns:
            len(postings(term)); 0, если термина нет.

        Example:
            >>> InvertedIndex.build([("D1", ["почва"]), ("D2", ["почва", "почва"])]).doc_freq("почва")
            2
        """
        return len(self._postings.get(term, ()))

    def doc_length(self, doc_id: DocId) -> int:
        """|D| — длина документа в токенах после предобработки.

        Args:
            doc_id: идентификатор документа.

        Returns:
            Число токенов документа.

        Raises:
            KeyError: если документа нет в индексе.

        Example:
            >>> InvertedIndex.build([("D1", ["полив", "почва", "полив"])]).doc_length("D1")
            3
        """
        return self._doc_lengths[doc_id]

    @property
    def n_docs(self) -> int:
        """N — число документов в индексе.

        Example:
            >>> InvertedIndex.build([("D1", ["полив"]), ("D2", [])]).n_docs
            2
        """
        return len(self._doc_lengths)

    @property
    def avgdl(self) -> float:
        """avgdl — средняя длина документа в токенах; 0.0 для пустого индекса.

        Example:
            >>> InvertedIndex.build([("D1", ["полив", "почва", "полив"]), ("D2", ["датчик", "почва"])]).avgdl
            2.5
        """
        return self._total_length / len(self._doc_lengths) if self._doc_lengths else 0.0

    def save(self, path: str | Path) -> None:
        """Сохраняет индекс в JSON (UTF-8) — опционально.

        Формат: {"version": 1, "doc_lengths": {doc_id: |D|}, "postings": {term: {doc_id: tf}}}.
        Конфигурацию предобработки, с которой построен индекс, сохраняют рядом: запросы
        должны обрабатываться так же.

        Args:
            path: путь к файлу.

        Example:
            Сохранение и загрузка — в примере к load.
        """
        data = {"version": 1, "doc_lengths": self._doc_lengths, "postings": self._postings}
        Path(path).write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    @classmethod
    def load(cls, path: str | Path) -> InvertedIndex:
        """Загружает индекс, сохранённый методом save.

        Args:
            path: путь к файлу JSON.

        Returns:
            Индекс с теми же postings и длинами документов.

        Example:
            >>> import pathlib, tempfile
            >>> path = pathlib.Path(tempfile.mkdtemp()) / "index.json"
            >>> InvertedIndex.build([("D1", ["полив"])]).save(path)
            >>> InvertedIndex.load(path).postings("полив")["D1"]
            1
        """
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        if data.get("version") != 1:
            raise ValueError(f"неизвестная версия индекса: {data.get('version')!r}")
        index = cls()
        index._doc_lengths = {str(k): int(v) for k, v in data["doc_lengths"].items()}
        index._postings = {t: {str(d): int(tf) for d, tf in p.items()} for t, p in data["postings"].items()}
        index._total_length = sum(index._doc_lengths.values())
        return index
