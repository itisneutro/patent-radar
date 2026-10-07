import marimo

__generated_with = "0.25.1"
app = marimo.App(width="medium")


@app.cell
def _():
    import marimo as mo

    return (mo,)


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    # Патентный радар: benchmark поиска BM25

    **Статус: КТ1 — план экспериментов.** Поиск ещё не реализован: функции в `app/search/` — заготовки, которые бросают `NotImplementedError`. Поэтому на КТ1 тетрадка:

    1. загружает корпус и запросы benchmark;
    2. проверяет формат benchmark;
    3. проверяет функции метрик на игрушечном примере;
    4. показывает сетку экспериментов A/B/C — ту же, что в `spec/tech/rag.md` (раздел 8);
    5. пытается построить индекс через `app.search` и сообщает, что BM25 ещё не реализован.

    **Цель (КТ2):** выбрать предобработку и параметры BM25 (k1, b) по Recall@5 на dev-части запросов и проверить выбор на test-части. Методика — `spec/tech/rag.md`, разделы 8–10.

    Запуск из корня репозитория: `marimo edit benchmark/experiments.py` — интерактивно; `python benchmark/experiments.py` — короткая сводка в консоль.
    """)
    return


@app.cell
def _(mo):
    import hashlib
    import json
    import math
    import platform
    import re
    import sys
    from collections import Counter, defaultdict
    from importlib import metadata
    from pathlib import Path

    _notebook_dir = mo.notebook_dir()
    BENCHMARK_DIR = (
        Path(_notebook_dir) if _notebook_dir is not None else Path(__file__).resolve().parent
    )
    REPO_ROOT = BENCHMARK_DIR.parent
    if str(REPO_ROOT) not in sys.path:
        # корень репозитория в sys.path — чтобы импортировать app.search
        sys.path.insert(0, str(REPO_ROOT))


    def first_existing(*candidates):
        """Первый существующий путь из списка; если нет ни одного — последний (для сообщения)."""
        for candidate in candidates:
            if candidate.exists():
                return candidate
        return candidates[-1]


    def package_version(name):
        """Версия установленного пакета или «не установлен»."""
        try:
            return metadata.version(name)
        except metadata.PackageNotFoundError:
            return "не установлен"


    # реальные файлы (КТ2), если они есть, иначе демо-корпус и пример запросов
    CORPUS_PATH = first_existing(
        REPO_ROOT / "data" / "corpus" / "patents.jsonl",
        REPO_ROOT / "data" / "sample" / "patents.jsonl",
    )
    QUERIES_PATH = first_existing(
        BENCHMARK_DIR / "queries.jsonl",
        BENCHMARK_DIR / "queries.example.jsonl",
    )
    return (
        CORPUS_PATH,
        Counter,
        QUERIES_PATH,
        REPO_ROOT,
        defaultdict,
        hashlib,
        json,
        math,
        package_version,
        platform,
        re,
    )


@app.cell
def _(CORPUS_PATH, QUERIES_PATH, REPO_ROOT, hashlib, json, mo):
    def load_jsonl(path):
        """Читает JSONL в UTF-8: одна запись — одна строка, пустые строки пропускаются."""
        with path.open(encoding="utf-8") as file:
            return [json.loads(line) for line in file if line.strip()]


    def file_fingerprint(path):
        """Первые 12 символов SHA-256 файла — фиксируем версию данных (rag.md, 8.1)."""
        return hashlib.sha256(path.read_bytes()).hexdigest()[:12]


    def repo_path(path):
        """Путь относительно корня репозитория — для таблиц и сводки."""
        return path.relative_to(REPO_ROOT).as_posix()


    mo.stop(
        not CORPUS_PATH.exists() or not QUERIES_PATH.exists(),
        mo.callout(
            mo.md(f"Нет файла корпуса или запросов: `{repo_path(CORPUS_PATH)}`, `{repo_path(QUERIES_PATH)}`."),
            kind="danger",
        ),
    )
    corpus = load_jsonl(CORPUS_PATH)
    queries = load_jsonl(QUERIES_PATH)
    corpus_by_id = {doc.get("id"): doc for doc in corpus}
    is_demo_corpus = all(str(doc.get("id", "")).startswith("DEMO-") for doc in corpus)
    return corpus, corpus_by_id, file_fingerprint, is_demo_corpus, queries, repo_path


@app.cell
def _(Counter, corpus):
    CORPUS_FIELDS = {"id", "title", "abstract", "ipc", "year", "source"}
    _ids = [doc.get("id") for doc in corpus]
    _duplicates = sorted(str(doc_id) for doc_id, count in Counter(_ids).items() if count > 1)
    corpus_errors = [f"дубли id в корпусе: {', '.join(_duplicates)}"] if _duplicates else []
    corpus_errors += [
        f"{doc.get('id')}: поля {sorted(doc)}"
        for doc in corpus
        if set(doc) != CORPUS_FIELDS
    ]
    corpus_errors += [
        f"{doc.get('id')}: пустой список ipc"
        for doc in corpus
        if not isinstance(doc.get("ipc"), list) or not doc.get("ipc")
    ]
    return (corpus_errors,)


@app.cell
def _(corpus_by_id, queries, re):
    QUERY_FIELDS = {"id", "query", "relevant", "topic"}
    MIN_RELEVANT = 3
    MIN_QUERY_WORDS = 3  # как в проверке запроса в API: слово = [^\W_]+
    MAX_QUERY_CHARS = 2000


    def check_query(row, seen_ids):
        """Проблемы одной записи benchmark; пустой список — запись в порядке."""
        problems = []
        if set(row) != QUERY_FIELDS:
            problems.append(f"поля {sorted(row)}, нужны ровно {sorted(QUERY_FIELDS)}")
        query_id = row.get("id")
        if not isinstance(query_id, str) or not re.fullmatch(r"Q-\d{3}", query_id):
            problems.append("id не вида Q-001")
        elif query_id in seen_ids:
            problems.append("id повторяется")
        text = row.get("query")
        words = re.findall(r"[^\W_]+", text) if isinstance(text, str) else []
        if len(words) < MIN_QUERY_WORDS:
            problems.append(f"в запросе меньше {MIN_QUERY_WORDS} слов")
        if isinstance(text, str) and len(text.strip()) > MAX_QUERY_CHARS:
            problems.append(f"запрос длиннее {MAX_QUERY_CHARS} символов")
        relevant = row.get("relevant")
        if not isinstance(relevant, list) or not all(isinstance(x, str) for x in relevant):
            problems.append("relevant — не список строк")
            relevant = []
        if len(set(relevant)) != len(relevant):
            problems.append("повторы в relevant")
        if len(set(relevant)) < MIN_RELEVANT:
            problems.append(f"релевантных меньше {MIN_RELEVANT}")
        missing = [doc_id for doc_id in relevant if doc_id not in corpus_by_id]
        if missing:
            problems.append("нет в корпусе: " + ", ".join(missing))
        topic = row.get("topic")
        if not isinstance(topic, str) or not re.fullmatch(r"[A-H]\d{2}[A-Z]", topic):
            problems.append("topic не подкласс МПК вида A01G")
        return problems


    _seen_ids = set()
    format_rows = []
    for _row in queries:
        _problems = check_query(_row, _seen_ids)
        _seen_ids.add(_row.get("id"))
        _query = _row.get("query") if isinstance(_row.get("query"), str) else ""
        _relevant = _row.get("relevant") if isinstance(_row.get("relevant"), list) else []
        format_rows.append(
            {
                "id": str(_row.get("id")),
                "topic": str(_row.get("topic")),
                "слов": len(re.findall(r"[^\W_]+", _query)),
                "релевантных": len(set(_relevant)),
                "в корпусе": sum(doc_id in corpus_by_id for doc_id in set(_relevant)),
                "проверка": "OK" if not _problems else "; ".join(_problems),
            }
        )
    format_errors = [
        f"{_r['id']}: {_r['проверка']}" for _r in format_rows if _r["проверка"] != "OK"
    ]
    if not queries:
        format_errors.append("файл запросов пуст")
    return format_errors, format_rows


@app.cell
def _(defaultdict, queries):
    def split_dev_test(rows):
        """Разбиение rag.md, 8.3: внутри темы запросы по id, каждый третий — test, остальные — dev."""
        by_topic = defaultdict(list)
        for row in rows:
            by_topic[str(row.get("topic"))].append(row)
        dev, test = [], []
        for topic in sorted(by_topic):
            ordered = sorted(by_topic[topic], key=lambda row: str(row.get("id")))
            for position, row in enumerate(ordered):
                (test if position % 3 == 2 else dev).append(row)
        return (
            sorted(dev, key=lambda row: str(row.get("id"))),
            sorted(test, key=lambda row: str(row.get("id"))),
        )


    dev_queries, test_queries = split_dev_test(queries)
    return dev_queries, test_queries


@app.cell
def _():
    def markdown_table(rows, columns):
        """Markdown-таблица из списка словарей (без pandas)."""
        def cell(value):
            return str(value).replace("|", "\\|")

        header = "| " + " | ".join(columns) + " |"
        separator = "|" + "---|" * len(columns)
        body = ["| " + " | ".join(cell(row.get(column, "")) for column in columns) + " |" for row in rows]
        return "\n".join([header, separator, *body])

    return (markdown_table,)


@app.cell(hide_code=True)
def _(
    CORPUS_PATH,
    QUERIES_PATH,
    corpus,
    corpus_errors,
    file_fingerprint,
    is_demo_corpus,
    markdown_table,
    mo,
    package_version,
    platform,
    queries,
    repo_path,
):
    _files = markdown_table(
        [
            {
                "что": "корпус",
                "файл": f"`{repo_path(CORPUS_PATH)}`",
                "записей": len(corpus),
                "SHA-256 (начало)": f"`{file_fingerprint(CORPUS_PATH)}`",
            },
            {
                "что": "запросы",
                "файл": f"`{repo_path(QUERIES_PATH)}`",
                "записей": len(queries),
                "SHA-256 (начало)": f"`{file_fingerprint(QUERIES_PATH)}`",
            },
        ],
        ["что", "файл", "записей", "SHA-256 (начало)"],
    )
    _versions = (
        f"Python {platform.python_version()}, marimo {package_version('marimo')}, "
        f"pymorphy3 {package_version('pymorphy3')}, словарь pymorphy3-dicts-ru {package_version('pymorphy3-dicts-ru')}"
    )
    _note = (
        mo.callout(
            mo.md(
                "**Демонстрационные данные:** записи DEMO-xxx — не реальные патенты. "
                "Реальный корпус появится в `data/corpus/patents.jsonl`, запросы — в `benchmark/queries.jsonl` (КТ2)."
            ),
            kind="info",
        )
        if is_demo_corpus
        else mo.md("Корпус — реальные рефераты.")
    )
    _corpus_check = (
        mo.callout(mo.md("Ошибки корпуса:\n\n" + "\n".join(f"- {e}" for e in corpus_errors)), kind="danger")
        if corpus_errors
        else mo.md("Корпус: id уникальны, у всех записей ровно 6 полей и непустой список МПК.")
    )
    mo.vstack(
        [
            mo.md("## 1. Данные\n\n" + _files + "\n\nВерсии: " + _versions + "."),
            _note,
            _corpus_check,
        ]
    )
    return


@app.cell(hide_code=True)
def _(
    Counter,
    corpus,
    dev_queries,
    format_errors,
    format_rows,
    markdown_table,
    mo,
    test_queries,
):
    _dev_ids = {str(row.get("id")) for row in dev_queries}
    _test_ids = {str(row.get("id")) for row in test_queries}
    _topics = sorted({row["topic"] for row in format_rows})
    _topic_rows = [
        {
            "topic": topic,
            "запросов": sum(row["topic"] == topic for row in format_rows),
            "dev": sum(row["topic"] == topic and row["id"] in _dev_ids for row in format_rows),
            "test": sum(row["topic"] == topic and row["id"] in _test_ids for row in format_rows),
        }
        for topic in _topics
    ]
    _corpus_topics = Counter(
        (doc.get("ipc") or ["—"])[0].replace(" ", "")[:4] for doc in corpus
    )
    _corpus_rows = [
        {"подкласс первого кода МПК": topic, "документов": count}
        for topic, count in sorted(_corpus_topics.items())
    ]
    _counts = [row["запросов"] for row in _topic_rows]
    _balance = (
        f"от {min(_counts)} до {max(_counts)} запросов на тему (план: 8 тем по 3 запроса)"
        if _counts
        else "запросов нет"
    )
    _verdict = (
        mo.callout(mo.md("**Формат benchmark: OK**"), kind="success")
        if not format_errors
        else mo.callout(
            mo.md("**Формат benchmark: ошибки**\n\n" + "\n".join(f"- {e}" for e in format_errors)),
            kind="danger",
        )
    )
    mo.vstack(
        [
            mo.md(
                "## 2. Проверка формата benchmark\n\n"
                "Правила (rag.md, раздел 10): поля ровно `id`, `query`, `relevant`, `topic`; `id` вида `Q-001` и уникален; "
                "в запросе не меньше 3 слов; не меньше 3 релевантных без повторов; все релевантные есть в корпусе; "
                "`topic` — подкласс МПК."
            ),
            mo.md(markdown_table(format_rows, ["id", "topic", "слов", "релевантных", "в корпусе", "проверка"])),
            mo.md(
                "**Распределение запросов по темам** (разбиение dev/test — rag.md, 8.3): "
                + _balance
                + "\n\n"
                + markdown_table(_topic_rows, ["topic", "запросов", "dev", "test"])
            ),
            mo.md(
                "**Документы корпуса по подклассу первого кода МПК** (план: ~25 на тему)\n\n"
                + markdown_table(_corpus_rows, ["подкласс первого кода МПК", "документов"])
            ),
            _verdict,
        ]
    )
    return


@app.cell
def _():
    def recall_at_k(ranked_ids, relevant_ids, k):
        """Recall@k одного запроса: доля релевантных документов запроса, попавших в первые k результатов."""
        relevant = set(relevant_ids)
        if not relevant:
            raise ValueError("у запроса нет релевантных документов")
        return len(relevant.intersection(list(ranked_ids)[:k])) / len(relevant)


    def reciprocal_rank(ranked_ids, relevant_ids, k=10):
        """1 / ранг первого релевантного документа среди первых k; 0, если его там нет."""
        relevant = set(relevant_ids)
        for rank, doc_id in enumerate(list(ranked_ids)[:k], start=1):
            if doc_id in relevant:
                return 1.0 / rank
        return 0.0


    def mean_recall_at_k(rankings, relevants, k):
        """Средний Recall@k: rankings и relevants — списки одинаковой длины (по запросам)."""
        if len(rankings) != len(relevants) or not rankings:
            raise ValueError("нужны непустые списки выдач и релевантных одинаковой длины")
        return sum(recall_at_k(r, rel, k) for r, rel in zip(rankings, relevants)) / len(rankings)


    def mrr(rankings, relevants, k=10):
        """MRR@k: среднее 1 / ранг первого релевантного по запросам (0, если его нет в первых k)."""
        if len(rankings) != len(relevants) or not rankings:
            raise ValueError("нужны непустые списки выдач и релевантных одинаковой длины")
        return sum(reciprocal_rank(r, rel, k) for r, rel in zip(rankings, relevants)) / len(rankings)

    return mean_recall_at_k, mrr, recall_at_k, reciprocal_rank


@app.cell(hide_code=True)
def _(markdown_table, math, mean_recall_at_k, mo, mrr, recall_at_k, reciprocal_rank):
    # Иллюстрация, не результат: выдуманные id D1…D12, тот же пример — в rag.md, раздел 9.
    _toy = {
        "T1": (["D3", "D1", "D5", "D7", "D9", "D2", "D4", "D8", "D6", "D10"], ["D1", "D4", "D7"]),
        "T2": (["D8", "D9", "D3", "D1", "D4", "D7", "D10", "D2", "D11", "D12"], ["D2", "D5", "D6"]),
    }
    _expected = {"T1": (2 / 3, 1.0, 0.5), "T2": (0.0, 1 / 3, 0.125)}
    _rows = []
    for _query_id, (_ranked, _relevant) in _toy.items():
        _got = (
            recall_at_k(_ranked, _relevant, 5),
            recall_at_k(_ranked, _relevant, 10),
            reciprocal_rank(_ranked, _relevant, 10),
        )
        if not all(math.isclose(a, b) for a, b in zip(_got, _expected[_query_id])):
            raise AssertionError(f"самопроверка метрик не прошла: {_query_id} {_got}")
        _rows.append(
            {
                "запрос": _query_id,
                "релевантные": ", ".join(_relevant),
                "выдача, первые 10": ", ".join(_ranked),
                "Recall@5": f"{_got[0]:.3f}",
                "Recall@10": f"{_got[1]:.3f}",
                "1 / rank": f"{_got[2]:.3f}",
            }
        )
    _rankings = [ranked for ranked, _ in _toy.values()]
    _relevants = [relevant for _, relevant in _toy.values()]
    _means = (
        mean_recall_at_k(_rankings, _relevants, 5),
        mean_recall_at_k(_rankings, _relevants, 10),
        mrr(_rankings, _relevants, 10),
    )
    if not all(math.isclose(a, b) for a, b in zip(_means, (1 / 3, 2 / 3, 0.3125))):
        raise AssertionError(f"самопроверка средних не прошла: {_means}")
    _rows.append(
        {
            "запрос": "среднее",
            "Recall@5": f"{_means[0]:.3f}",
            "Recall@10": f"{_means[1]:.3f}",
            "1 / rank": f"MRR = {_means[2]:.4f}",
        }
    )
    metrics_selfcheck = "пройдена"
    mo.vstack(
        [
            mo.md(
                "## 3. Метрики: Recall@5, Recall@10, MRR@10\n\n"
                "Функции `recall_at_k`, `reciprocal_rank`, `mean_recall_at_k`, `mrr` — формулы rag.md, раздел 9. "
                "Главная метрика выбора — Recall@5 (в контекст LLM идут первые 5 рефератов), при равенстве — MRR."
            ),
            mo.callout(
                mo.md(
                    "**Иллюстрация, не результат.** Выдуманные выдачи с id D1…D12 — только для проверки формул; "
                    "к корпусу и к качеству поиска отношения не имеют. Самопроверка пройдена."
                ),
                kind="neutral",
            ),
            mo.md(
                markdown_table(
                    _rows,
                    ["запрос", "релевантные", "выдача, первые 10", "Recall@5", "Recall@10", "1 / rank"],
                )
            ),
        ]
    )
    return (metrics_selfcheck,)


@app.cell
def _():
    # Сетка экспериментов — ровно как в spec/tech/rag.md, раздел 8.2.
    BASE_K1, BASE_B = 1.2, 0.75
    EXPERIMENTS_A = (
        {"run": "A1 (baseline)", "lemmatize": False, "general_stopwords": False, "patent_stopwords": False,
         "shows": "нижняя граница: регистр, МПК, токенизация"},
        {"run": "A2", "lemmatize": True, "general_stopwords": False, "patent_stopwords": False,
         "shows": "вклад лемматизации (A2 против A1)"},
        {"run": "A3", "lemmatize": False, "general_stopwords": True, "patent_stopwords": True,
         "shows": "стоп-слова без лемматизации (A3 против A1)"},
        {"run": "A4", "lemmatize": True, "general_stopwords": True, "patent_stopwords": False,
         "shows": "общие стоп-слова при лемматизации (A4 против A2)"},
        {"run": "A5", "lemmatize": True, "general_stopwords": True, "patent_stopwords": True,
         "shows": "полный конвейер; вклад патентного списка (A5 против A4)"},
    )
    K1_GRID = (0.6, 0.9, 1.2, 1.5, 2.0)
    B_GRID = (0.3, 0.5, 0.75, 0.9)
    EXPERIMENTS_B = tuple({"run": f"B({k1}, {b})", "k1": k1, "b": b} for k1 in K1_GRID for b in B_GRID)
    EXPERIMENTS_C = (
        {"run": "C1", "title_boost": 2, "ipc_tokens": False, "extra_stopwords": (),
         "change": "название ×2 (title boost): токены названия входят в документ дважды",
         "question": "важнее ли название, чем реферат"},
        {"run": "C2", "title_boost": 1, "ipc_tokens": True, "extra_stopwords": (),
         "change": "коды МПК как токены: коды записи (поле `ipc`, в виде `a01g25/16`) добавляются к токенам документа — вкл/выкл",
         "question": "помогают ли коды запросам, в которых пользователь указал код, и не портят ли остальную выдачу"},
        {"run": "C3", "title_boost": 1, "ipc_tokens": False, "extra_stopwords": ("способ", "устройство", "система"),
         "change": "расширенный стоп-список: + «способ», «устройство», «система»",
         "question": "шум эти слова или полезный сигнал о типе изобретения"},
    )
    return BASE_B, BASE_K1, B_GRID, EXPERIMENTS_A, EXPERIMENTS_B, EXPERIMENTS_C, K1_GRID


@app.cell(hide_code=True)
def _(
    BASE_B,
    BASE_K1,
    B_GRID,
    EXPERIMENTS_A,
    EXPERIMENTS_B,
    EXPERIMENTS_C,
    K1_GRID,
    markdown_table,
    mo,
):
    def _flag(value, forms=False):
        if not value:
            return "нет"
        return "да, словоформы" if forms else "да"


    _a_rows = [
        {
            "Прогон": run["run"],
            "Лемматизация": _flag(run["lemmatize"]),
            "Общие стоп-слова": _flag(run["general_stopwords"], forms=not run["lemmatize"]),
            "Патентные стоп-слова": _flag(run["patent_stopwords"], forms=not run["lemmatize"]),
            "Что показывает": run["shows"],
        }
        for run in EXPERIMENTS_A
    ]
    _b_rows = [{"k1 \\ b": k1, **{str(b): f"B({k1}, {b})" for b in B_GRID}} for k1 in K1_GRID]
    _c_rows = [{"Прогон": run["run"], "Изменение": run["change"], "Вопрос": run["question"]} for run in EXPERIMENTS_C]
    mo.md(
        "## 4. Сетка экспериментов (rag.md, 8.2)\n\n"
        f"**Блок A** — предобработка 2 × 2 и уточнение; k1 = {BASE_K1}, b = {BASE_B}:\n\n"
        + markdown_table(_a_rows, ["Прогон", "Лемматизация", "Общие стоп-слова", "Патентные стоп-слова", "Что показывает"])
        + f"\n\n**Блок B** — лучшая конфигурация блока A × k1 × b: {len(EXPERIMENTS_B)} прогонов на dev-части. "
        "Прогон B(1.2, 0.75) совпадает с победителем блока A; победитель блока проверяется на test-части.\n\n"
        + markdown_table(_b_rows, ["k1 \\ b", *[str(b) for b in B_GRID]])
        + "\n\n**Блок C** (по желанию) — на лучшей конфигурации A + B, каждый опыт сравнивается с ней по отдельности:\n\n"
        + markdown_table(_c_rows, ["Прогон", "Изменение", "Вопрос"])
        + "\n\n**Выбор победителя (rag.md, 8.4):** максимум Recall@5 на dev → больший MRR → больший Recall@10 → "
        "более простая конфигурация. Test считаем один раз, в конце, и по нему ничего не подбираем."
    )
    return


@app.cell
def _(corpus, mo):
    try:
        from app.search import bm25 as search_bm25
        from app.search import index as search_index
        from app.search import preprocess as search_preprocess
    except ImportError as _import_error:
        search_bm25 = search_index = search_preprocess = None
        bm25_ready = False
        bm25_status = f"модули app.search не найдены ({_import_error})"
        _view = mo.callout(mo.md(f"**Не удалось импортировать app.search:** {_import_error}"), kind="danger")
    else:
        try:
            _config = search_preprocess.PreprocessConfig()
            _documents = [
                (doc["id"], search_preprocess.preprocess(doc["title"], _config) + search_preprocess.preprocess(doc["abstract"], _config))
                for doc in corpus
            ]
            search_bm25.BM25(search_index.InvertedIndex.build(_documents))
        except NotImplementedError as _error:
            bm25_ready = False
            bm25_status = "не реализован (NotImplementedError) — эксперименты запустим на КТ2"
            _view = mo.callout(
                mo.md(
                    "**BM25 ещё не реализован — эксперименты запустим на КТ2**\n\n"
                    f"Первая заготовка, ответившая `NotImplementedError`: «{_error}». "
                    "Разделы 6–8 ниже заполнятся, когда app.search будет реализован."
                ),
                kind="warn",
            )
        else:
            bm25_ready = True
            bm25_status = "реализован: индекс построен"
            _view = mo.callout(mo.md("**BM25 реализован:** индекс построен, ниже — прогоны блоков A, B и C."), kind="success")
    mo.vstack([mo.md("## 5. Запуск: индекс через app.search"), _view])
    return bm25_ready, bm25_status, search_bm25, search_index, search_preprocess


@app.cell
def _(
    BASE_B,
    BASE_K1,
    corpus,
    mean_recall_at_k,
    mrr,
    search_bm25,
    search_index,
    search_preprocess,
):
    def build_documents(config, title_boost=1, ipc_tokens=False, extra_stopwords=frozenset()):
        """Токены документов корпуса для одного прогона: название × title_boost + реферат (+ коды МПК)."""
        documents = []
        for doc in corpus:
            tokens = search_preprocess.preprocess(doc["title"], config) * title_boost
            tokens += search_preprocess.preprocess(doc["abstract"], config)
            if ipc_tokens:
                ipc_text = search_preprocess.normalize(" ".join(doc["ipc"]))
                tokens += search_preprocess.extract_ipc_codes(ipc_text)[0]
            documents.append((doc["id"], [t for t in tokens if t not in extra_stopwords]))
        return documents


    def evaluate_run(run, query_rows, top_k=10):
        """Строит индекс под прогон и считает Recall@5, Recall@10, MRR@10 по запросам query_rows."""
        config = search_preprocess.PreprocessConfig(
            lemmatize=run["lemmatize"],
            general_stopwords=run["general_stopwords"],
            patent_stopwords=run["patent_stopwords"],
        )
        extra = tuple(run.get("extra_stopwords", ()))
        if not extra:
            extra_set = frozenset()
        elif config.lemmatize:
            extra_set = frozenset(extra)
        else:
            extra_set = search_preprocess.expand_wordforms(extra)
        documents = build_documents(config, run.get("title_boost", 1), run.get("ipc_tokens", False), extra_set)
        bm25 = search_bm25.BM25(
            search_index.InvertedIndex.build(documents), k1=run.get("k1", BASE_K1), b=run.get("b", BASE_B)
        )
        rankings = []
        for row in query_rows:
            query_tokens = [t for t in search_preprocess.preprocess(row["query"], config) if t not in extra_set]
            rankings.append([doc_id for doc_id, _ in bm25.search(query_tokens, top_k=top_k)])
        relevants = [row["relevant"] for row in query_rows]
        return {
            "Recall@5": mean_recall_at_k(rankings, relevants, 5),
            "Recall@10": mean_recall_at_k(rankings, relevants, 10),
            "MRR": mrr(rankings, relevants, 10),
            "rankings": rankings,
        }


    def pick_best(results, simplicity):
        """Победитель rag.md, 8.4: Recall@5 → MRR → Recall@10 → более простая конфигурация."""
        return min(
            results,
            key=lambda item: (-item["Recall@5"], -item["MRR"], -item["Recall@10"], simplicity(item)),
        )


    def metric_row(name, result):
        return {
            "прогон": name,
            "Recall@5": f"{result['Recall@5']:.3f}",
            "Recall@10": f"{result['Recall@10']:.3f}",
            "MRR": f"{result['MRR']:.3f}",
        }

    return evaluate_run, metric_row, pick_best


@app.cell
def _(
    EXPERIMENTS_A,
    bm25_ready,
    dev_queries,
    evaluate_run,
    markdown_table,
    metric_row,
    mo,
    pick_best,
    queries,
):
    best_a = None
    if not bm25_ready:
        _view = mo.md("## 6. Блок A\n\nТаблица блока A на dev-части появится на КТ2, когда BM25 будет реализован.")
    elif not dev_queries:
        _view = mo.md("## 6. Блок A\n\nВ dev-части нет запросов.")
    else:
        _results_a = [
            {**_run, **evaluate_run(_run, dev_queries), "position": _position}
            for _position, _run in enumerate(EXPERIMENTS_A)
        ]
        best_a = pick_best(_results_a, simplicity=lambda item: item["position"])
        # pooling (rag.md, 10.3): непомеченные документы из первых 10 результатов всех прогонов A
        _pool = {}
        for _run in EXPERIMENTS_A:
            _all = evaluate_run(_run, queries)
            for _row, _ranked in zip(queries, _all["rankings"]):
                for _doc_id in _ranked:
                    if _doc_id not in _row["relevant"]:
                        _pool.setdefault((_row["id"], _doc_id), []).append(_run["run"])
        _pool_rows = [
            {"запрос": query_id, "документ": doc_id, "в первых 10 у": ", ".join(runs)}
            for (query_id, doc_id), runs in sorted(_pool.items())
        ]
        _view = mo.vstack(
            [
                mo.md(
                    "## 6. Блок A (dev)\n\n"
                    + markdown_table([metric_row(r["run"], r) for r in _results_a], ["прогон", "Recall@5", "Recall@10", "MRR"])
                    + f"\n\nЛучшая предобработка: **{best_a['run']}**."
                ),
                mo.md(
                    "**Pooling** — документы из первых 10 результатов, которых нет в `relevant` (просмотреть и доразметить):\n\n"
                    + (markdown_table(_pool_rows, ["запрос", "документ", "в первых 10 у"]) if _pool_rows else "нет")
                ),
            ]
        )
    _view
    return (best_a,)


@app.cell
def _(
    BASE_B,
    BASE_K1,
    B_GRID,
    EXPERIMENTS_B,
    K1_GRID,
    best_a,
    dev_queries,
    evaluate_run,
    markdown_table,
    mo,
    pick_best,
):
    best_b = None
    if best_a is None:
        _view = mo.md("## 7. Блок B\n\nСетка k1 × b (20 прогонов на dev-части) появится на КТ2, после блока A.")
    else:
        _results_b = [
            {**best_a, **_run, **evaluate_run({**best_a, "k1": _run["k1"], "b": _run["b"]}, dev_queries)}
            for _run in EXPERIMENTS_B
        ]
        best_b = pick_best(
            _results_b, simplicity=lambda item: abs(item["k1"] - BASE_K1) + abs(item["b"] - BASE_B)
        )
        _by_params = {(r["k1"], r["b"]): r for r in _results_b}
        _matrix = [
            {"k1 \\ b": k1, **{str(b): f"{_by_params[(k1, b)]['Recall@5']:.3f}" for b in B_GRID}}
            for k1 in K1_GRID
        ]
        _view = mo.md(
            f"## 7. Блок B (dev): Recall@5 по сетке k1 × b, предобработка {best_a['run']}\n\n"
            + markdown_table(_matrix, ["k1 \\ b", *[str(b) for b in B_GRID]])
            + f"\n\nЛучшие параметры: **{best_b['run']}** (MRR {best_b['MRR']:.3f}, Recall@10 {best_b['Recall@10']:.3f})."
        )
    _view
    return (best_b,)


@app.cell
def _(
    EXPERIMENTS_A,
    EXPERIMENTS_C,
    best_a,
    best_b,
    dev_queries,
    evaluate_run,
    markdown_table,
    metric_row,
    mo,
    test_queries,
):
    if best_a is None or best_b is None:
        _view = mo.md("## 8. Блок C и итог на test\n\nТаблицы появятся на КТ2, после блоков A и B.")
    else:
        _base = {key: best_b[key] for key in ("run", "lemmatize", "general_stopwords", "patent_stopwords", "k1", "b")}
        _base_dev = evaluate_run(_base, dev_queries)
        _c_dev = [(_run, evaluate_run({**_base, **_run}, dev_queries)) for _run in EXPERIMENTS_C]
        _c_rows = [metric_row(f"{best_a['run']} + {best_b['run']} (база)", _base_dev)]
        _c_rows += [metric_row(_run["run"], _res) for _run, _res in _c_dev]

        def _dev_key(result):
            """Порядок сравнения rag.md, 8.4: Recall@5, затем MRR, затем Recall@10."""
            return (result["Recall@5"], result["MRR"], result["Recall@10"])

        # rag.md, 8.3, п. 4: оставляем опыты C, которые на dev лучше базы A + B (равенство — не улучшение)
        _kept = [_run for _run, _res in _c_dev if _dev_key(_res) > _dev_key(_base_dev)]
        # в каждом опыте C заданы все три ключа, поэтому настройки оставленных опытов объединяем по ключам
        _final = {
            **_base,
            "title_boost": max([1, *(_run["title_boost"] for _run in _kept)]),
            "ipc_tokens": any(_run["ipc_tokens"] for _run in _kept),
            "extra_stopwords": tuple(_word for _run in _kept for _word in _run["extra_stopwords"]),
        }
        _final_name = f"итоговая: {best_a['run']} + {best_b['run']}" + "".join(f" + {_run['run']}" for _run in _kept)
        _kept_md = (
            "Улучшили dev и вошли в итоговую конфигурацию: " + ", ".join(_run["run"] for _run in _kept) + "."
            if _kept
            else "Ни один опыт C не улучшил dev: итоговая конфигурация — лучшая A и лучшие (k1, b)."
        )
        if test_queries:
            _test_rows = [
                metric_row("A1 (baseline)", evaluate_run(EXPERIMENTS_A[0], test_queries)),
                metric_row(f"лучшая A: {best_a['run']}", evaluate_run(best_a, test_queries)),
                metric_row(_final_name, evaluate_run(_final, test_queries)),
            ]
            _test_md = markdown_table(_test_rows, ["прогон", "Recall@5", "Recall@10", "MRR"])
        else:
            _test_md = "В test-части нет запросов."
        _view = mo.md(
            "## 8. Блок C (dev) и итог на test\n\n"
            + markdown_table(_c_rows, ["прогон", "Recall@5", "Recall@10", "MRR"])
            + "\n\nОпыты C оставляем, только если они улучшили dev (rag.md, 8.3). "
            + _kept_md
            + " Итог на test считаем один раз:\n\n"
            + _test_md
        )
    _view
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## 9. План отчёта (КТ2)

    Какие таблицы и графики появятся в этой тетрадке, когда BM25 будет реализован:

    1. **Блок A на dev** — Recall@5, Recall@10, MRR для A1–A5 и число запросов, выигравших и проигравших относительно A1.
    2. **Блок B на dev** — тепловая карта Recall@5 по сетке k1 × b и таблица 20 прогонов с MRR и Recall@10.
    3. **Блок C на dev** — C1–C3 относительно лучшей конфигурации A + B.
    4. **Итог на test** — A1, лучшая конфигурация A и итоговая; test считаем один раз.
    5. **Таблица по запросам** — Recall@5 у A1 и у итоговой конфигурации; «трудные» запросы с Recall@10 = 0 и их разбор (лексический разрыв, rag.md, раздел 11).
    6. **Распределение score первого результата** у запросов benchmark и у посторонних запросов — для выбора порога MIN_SCORE (rag.md, раздел 7).
    7. **Гистограмма длин документов** (|D| / avgdl) — насколько рефераты различаются по длине и почему параметр b может слабо влиять.
    8. **Pooling** — список непомеченных документов из первых 10 результатов для доразметки до выбора конфигураций.

    Для графиков понадобится библиотека визуализации; её добавим в зависимости на КТ2.
    """)
    return


@app.cell(hide_code=True)
def _(
    CORPUS_PATH,
    QUERIES_PATH,
    bm25_status,
    corpus,
    corpus_errors,
    dev_queries,
    format_errors,
    format_rows,
    is_demo_corpus,
    metrics_selfcheck,
    mo,
    queries,
    repo_path,
    test_queries,
):
    _topics = len({row["topic"] for row in format_rows})
    _lines = [
        "Патентный радар — benchmark поиска (КТ1)",
        f"Корпус: {repo_path(CORPUS_PATH)} — записей: {len(corpus)}"
        + (" (демонстрационные данные)" if is_demo_corpus else ""),
        f"Запросы: {repo_path(QUERIES_PATH)} — запросов: {len(queries)} (dev: {len(dev_queries)}, test: {len(test_queries)}, тем: {_topics})",
        "Формат benchmark: OK" if not format_errors else "Формат benchmark: ОШИБКИ — " + "; ".join(format_errors),
    ]
    if corpus_errors:
        _lines.append("Корпус: ОШИБКИ — " + "; ".join(corpus_errors))
    _lines += [
        f"Метрики: самопроверка на игрушечном примере {metrics_selfcheck}",
        f"BM25: {bm25_status}",
    ]
    _summary = "\n".join(_lines)
    if mo.app_meta().mode == "script":
        print(_summary)
    mo.md("## Сводка\n\n```text\n" + _summary + "\n```")
    return


if __name__ == "__main__":
    app.run()
