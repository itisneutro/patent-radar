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

Статус КТ1: заготовка. Методы бросают NotImplementedError, реализация — на КТ2.

Ограничения методички: только собственная реализация; готовые поисковые индексы
(Whoosh, Elasticsearch и т. п.) не используются.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path

DocId = str
"""Идентификатор документа: "RU<номер><код вида>" или "DEMO-001"."""

Term = str
"""Термин индекса — токен после предобработки."""

Postings = dict[DocId, int]
"""Список вхождений термина: doc_id -> tf (сколько раз термин встречается в документе)."""


class InvertedIndex:
    """Инвертированный индекс term -> {doc_id: tf} с длинами документов.

    Планируемые поля (КТ2):
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
        raise NotImplementedError("КТ2: InvertedIndex.__init__ — пустые postings и doc_lengths")

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
        raise NotImplementedError("КТ2: InvertedIndex.build — add_document для каждого документа")

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
        raise NotImplementedError("КТ2: InvertedIndex.add_document")

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
        raise NotImplementedError("КТ2: InvertedIndex.postings")

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
        raise NotImplementedError("КТ2: InvertedIndex.doc_freq")

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
        raise NotImplementedError("КТ2: InvertedIndex.doc_length")

    @property
    def n_docs(self) -> int:
        """N — число документов в индексе.

        Example:
            >>> InvertedIndex.build([("D1", ["полив"]), ("D2", [])]).n_docs
            2
        """
        raise NotImplementedError("КТ2: InvertedIndex.n_docs")

    @property
    def avgdl(self) -> float:
        """avgdl — средняя длина документа в токенах; 0.0 для пустого индекса.

        Example:
            >>> InvertedIndex.build([("D1", ["полив", "почва", "полив"]), ("D2", ["датчик", "почва"])]).avgdl
            2.5
        """
        raise NotImplementedError("КТ2: InvertedIndex.avgdl")

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
        raise NotImplementedError("КТ2: InvertedIndex.save — JSON")

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
        raise NotImplementedError("КТ2: InvertedIndex.load — JSON")
