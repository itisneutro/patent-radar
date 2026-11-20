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

    **Статус: КТ2.** Собственный BM25 (`app/search/`) по корпусу `data/corpus/patents.jsonl` и benchmark `benchmark/queries.jsonl`. Тетрадка:

    1. проверяет корпус, запросы, ловушки и посторонние запросы; печатает SHA-256 файлов;
    2. показывает распределение запросов по темам, документов по подклассам и длины документов;
    3. считает Recall@5, Recall@10 и MRR@10 (spec/tech/rag.md, раздел 9);
    4. ставит опыты блоков A, B и C на dev-части, pooling после блока A, итог на test — один раз;
    5. подбирает порог `MIN_SCORE` по распределению score с посторонними запросами (раздел 7);
    6. даёт слайдеры k1 и b для ручной проверки запросов.

    Методика — `spec/tech/rag.md`, разделы 7–10. Запуск из корня репозитория: `python benchmark/experiments.py` — сводка в консоль; `marimo edit benchmark/experiments.py` — интерактивно. Вопросы-ловушки здесь только проверяются на формат: для подбора настроек они не используются (раздел 10.7).
    """)
    return


@app.cell
def _(mo):
    import hashlib
    import json
    import math
    import platform
    import re
    import statistics
    import sys
    from collections import Counter, defaultdict
    from importlib import metadata
    from pathlib import Path

    _notebook_dir = mo.notebook_dir()
    BENCHMARK_DIR = Path(_notebook_dir) if _notebook_dir is not None else Path(__file__).resolve().parent
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
    CORPUS_PATH = first_existing(REPO_ROOT / "data" / "corpus" / "patents.jsonl", REPO_ROOT / "data" / "sample" / "patents.jsonl")
    QUERIES_PATH = first_existing(BENCHMARK_DIR / "queries.jsonl", BENCHMARK_DIR / "queries.example.jsonl")
    # пример запросов ссылается на демо-записи, поэтому его проверяем по демо-корпусу
    QUERY_CORPUS_PATH = (
        REPO_ROOT / "data" / "sample" / "patents.jsonl" if QUERIES_PATH.name == "queries.example.jsonl" else CORPUS_PATH
    )
    TRAPS_PATH = BENCHMARK_DIR / "traps.jsonl"
    OFFTOPIC_PATH = BENCHMARK_DIR / "offtopic.jsonl"
    POOLING_PATH = BENCHMARK_DIR / "pooling.jsonl"
    return (
        CORPUS_PATH,
        Counter,
        OFFTOPIC_PATH,
        POOLING_PATH,
        QUERIES_PATH,
        QUERY_CORPUS_PATH,
        REPO_ROOT,
        TRAPS_PATH,
        defaultdict,
        hashlib,
        json,
        math,
        package_version,
        platform,
        re,
        statistics,
    )


@app.cell
def _(
    CORPUS_PATH,
    OFFTOPIC_PATH,
    POOLING_PATH,
    QUERIES_PATH,
    QUERY_CORPUS_PATH,
    REPO_ROOT,
    TRAPS_PATH,
    hashlib,
    json,
    mo,
):
    def load_jsonl(path):
        """Читает JSONL в UTF-8: одна запись — одна строка; нет файла — пустой список."""
        if not path.exists():
            return []
        with path.open(encoding="utf-8") as file:
            return [json.loads(line) for line in file if line.strip()]


    def file_fingerprint(path):
        """Первые 16 символов SHA-256 файла — фиксируем версию данных (rag.md, 8.1)."""
        return hashlib.sha256(path.read_bytes()).hexdigest()[:16] if path.exists() else "—"


    def repo_path(path):
        """Путь относительно корня репозитория — для таблиц и сводки."""
        return path.relative_to(REPO_ROOT).as_posix()


    mo.stop(
        not CORPUS_PATH.exists() or not QUERIES_PATH.exists(),
        mo.callout(mo.md(f"Нет файла корпуса или запросов: `{repo_path(CORPUS_PATH)}`, `{repo_path(QUERIES_PATH)}`."), kind="danger"),
    )
    corpus = load_jsonl(CORPUS_PATH)
    queries = load_jsonl(QUERIES_PATH)
    traps = load_jsonl(TRAPS_PATH)
    offtopic = load_jsonl(OFFTOPIC_PATH)
    pooling = load_jsonl(POOLING_PATH)
    corpus_by_id = {doc.get("id"): doc for doc in corpus}
    query_corpus_by_id = (
        corpus_by_id if QUERY_CORPUS_PATH == CORPUS_PATH else {doc.get("id"): doc for doc in load_jsonl(QUERY_CORPUS_PATH)}
    )
    is_demo_corpus = all(str(doc.get("id", "")).startswith("DEMO-") for doc in corpus)
    real_benchmark = QUERIES_PATH.name == "queries.jsonl" and not is_demo_corpus
    return (
        corpus,
        corpus_by_id,
        file_fingerprint,
        is_demo_corpus,
        offtopic,
        pooling,
        queries,
        query_corpus_by_id,
        real_benchmark,
        repo_path,
        traps,
    )


@app.cell
def _(Counter, corpus, re):
    CORPUS_FIELDS = {"id", "title", "abstract", "ipc", "year", "source"}
    _ids = [doc.get("id") for doc in corpus]
    _duplicates = sorted(str(doc_id) for doc_id, count in Counter(_ids).items() if count > 1)
    corpus_errors = [f"дубли id в корпусе: {', '.join(_duplicates)}"] if _duplicates else []
    corpus_errors += [f"{doc.get('id')}: поля {sorted(doc)}" for doc in corpus if set(doc) != CORPUS_FIELDS]
    corpus_errors += [
        f"{doc.get('id')}: код МПК не вида A01G 25/16"
        for doc in corpus
        if not isinstance(doc.get("ipc"), list)
        or not doc.get("ipc")
        or not all(re.fullmatch(r"[A-H]\d{2}[A-Z] \d{1,4}/\d{2,6}", str(code)) for code in doc.get("ipc", []))
    ]
    return (corpus_errors,)


@app.cell
def _(queries, query_corpus_by_id, re):
    QUERY_FIELDS = {"id", "query", "relevant", "topic", "expected"}
    MIN_RELEVANT = 3
    MIN_QUERY_WORDS = 3  # как в проверке запроса в API: слово = [^\W_]+
    MAX_QUERY_CHARS = 2000


    def check_query(row, seen_ids):
        """Проблемы одной записи benchmark (rag.md, 10.5); пустой список — запись в порядке."""
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
        missing = [doc_id for doc_id in relevant if doc_id not in query_corpus_by_id]
        if missing:
            problems.append("нет в корпусе: " + ", ".join(missing))
        topic = row.get("topic")
        if not isinstance(topic, str) or not re.fullmatch(r"[A-H]\d{2}[A-Z]", topic):
            problems.append("topic не подкласс МПК вида A01G")
        expected = row.get("expected")
        if not isinstance(expected, str) or not expected.strip():
            problems.append("expected — не непустая строка (эталонный ответ, rag.md, 10.5)")
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
                "в корпусе": sum(doc_id in query_corpus_by_id for doc_id in set(_relevant)),
                "проверка": "OK" if not _problems else "; ".join(_problems),
            }
        )
    format_errors = [f"{_r['id']}: {_r['проверка']}" for _r in format_rows if _r["проверка"] != "OK"]
    if not queries:
        format_errors.append("файл запросов пуст")
    return format_errors, format_rows


@app.cell
def _(offtopic, re, traps):
    # ловушки и посторонние запросы — формат rag.md, 10.5; для подбора настроек ловушки не используются
    extra_errors = []
    for _t in traps:
        if set(_t) != {"id", "query", "near_topic", "expected"} or not re.fullmatch(r"T-0[1-9]", str(_t.get("id"))):
            extra_errors.append(f"ловушка {_t.get('id')}: формат")
        elif _t["expected"] != "аналогов в корпусе не найдено" or len(re.findall(r"[^\W_]+", _t["query"])) < 3:
            extra_errors.append(f"ловушка {_t['id']}: expected или длина запроса")
    for _o in offtopic:
        if set(_o) != {"id", "query"} or not re.fullmatch(r"O-(0[1-9]|10)", str(_o.get("id"))):
            extra_errors.append(f"посторонний запрос {_o.get('id')}: формат")
    _overlap = {_t["query"] for _t in traps} & {_o["query"] for _o in offtopic}
    if _overlap:
        extra_errors.append("ловушки и посторонние запросы пересекаются")
    return (extra_errors,)


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
    OFFTOPIC_PATH,
    POOLING_PATH,
    QUERIES_PATH,
    TRAPS_PATH,
    corpus,
    corpus_errors,
    file_fingerprint,
    is_demo_corpus,
    markdown_table,
    mo,
    offtopic,
    package_version,
    platform,
    pooling,
    queries,
    repo_path,
    traps,
):
    data_files = [
        {"что": what, "файл": f"`{repo_path(path)}`", "записей": count, "SHA-256 (начало)": f"`{file_fingerprint(path)}`"}
        for what, path, count in (
            ("корпус", CORPUS_PATH, len(corpus)),
            ("запросы", QUERIES_PATH, len(queries)),
            ("ловушки", TRAPS_PATH, len(traps)),
            ("посторонние запросы", OFFTOPIC_PATH, len(offtopic)),
            ("pooling", POOLING_PATH, len(pooling)),
        )
    ]
    versions = (
        f"Python {platform.python_version()}, marimo {package_version('marimo')}, "
        f"pymorphy3 {package_version('pymorphy3')}, словарь pymorphy3-dicts-ru {package_version('pymorphy3-dicts-ru')}"
    )
    _note = (
        mo.callout(mo.md("**Демонстрационные данные:** записи DEMO-xxx — не реальные патенты."), kind="info")
        if is_demo_corpus
        else mo.md("Корпус — реальные рефераты патентов РФ (`data/sample/README.md`, раздел «Реальный корпус»).")
    )
    _corpus_check = (
        mo.callout(mo.md("Ошибки корпуса:\n\n" + "\n".join(f"- {e}" for e in corpus_errors)), kind="danger")
        if corpus_errors
        else mo.md("Корпус: id уникальны, у всех записей ровно 6 полей, коды МПК вида `A01G 25/16`.")
    )
    mo.vstack(
        [
            mo.md("## 1. Данные\n\n" + markdown_table(data_files, ["что", "файл", "записей", "SHA-256 (начало)"]) + "\n\nВерсии: " + versions + "."),
            _note,
            _corpus_check,
        ]
    )
    return data_files, versions


@app.cell(hide_code=True)
def _(
    Counter,
    corpus,
    dev_queries,
    extra_errors,
    format_errors,
    format_rows,
    markdown_table,
    mo,
    test_queries,
):
    _dev_ids = {str(row.get("id")) for row in dev_queries}
    _test_ids = {str(row.get("id")) for row in test_queries}
    topic_rows = [
        {
            "topic": topic,
            "запросов": sum(row["topic"] == topic for row in format_rows),
            "dev": sum(row["topic"] == topic and row["id"] in _dev_ids for row in format_rows),
            "test": sum(row["topic"] == topic and row["id"] in _test_ids for row in format_rows),
            "документов (первый код МПК)": sum((doc.get("ipc") or ["—"])[0][:4] == topic for doc in corpus),
        }
        for topic in sorted({row["topic"] for row in format_rows})
    ]
    _corpus_topics = Counter((doc.get("ipc") or ["—"])[0][:4] for doc in corpus)
    _verdict = (
        mo.callout(mo.md("**Формат benchmark: OK**"), kind="success")
        if not format_errors and not extra_errors
        else mo.callout(mo.md("**Формат benchmark: ошибки**\n\n" + "\n".join(f"- {e}" for e in format_errors + extra_errors)), kind="danger")
    )
    mo.vstack(
        [
            mo.md(
                "## 2. Проверка формата и распределение\n\n"
                "Правила (rag.md, 10.5): поля ровно `id`, `query`, `relevant`, `topic`, `expected`; не меньше 3 слов и 3 релевантных "
                "без повторов; все релевантные есть в корпусе; `topic` — подкласс МПК; `expected` — эталонный ответ. Ловушки — "
                "`T-01`…, `near_topic`, отказ в `expected`; посторонние запросы — `O-01`…`O-10`, с ловушками не пересекаются."
            ),
            mo.md(markdown_table(format_rows, ["id", "topic", "слов", "релевантных", "в корпусе", "проверка"])),
            mo.md(
                "**Запросы и документы по темам** (разбиение dev/test — rag.md, 8.3; документы — по подклассу первого кода МПК, план — 25 на тему):\n\n"
                + markdown_table(topic_rows, ["topic", "запросов", "dev", "test", "документов (первый код МПК)"])
                + f"\n\nВсего подклассов первого кода в корпусе: {len(_corpus_topics)}."
            ),
            _verdict,
        ]
    )
    return (topic_rows,)


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
        _got = (recall_at_k(_ranked, _relevant, 5), recall_at_k(_ranked, _relevant, 10), reciprocal_rank(_ranked, _relevant, 10))
        if not all(math.isclose(a, b) for a, b in zip(_got, _expected[_query_id])):
            raise AssertionError(f"самопроверка метрик не прошла: {_query_id} {_got}")
        _rows.append({"запрос": _query_id, "Recall@5": f"{_got[0]:.3f}", "Recall@10": f"{_got[1]:.3f}", "1 / rank": f"{_got[2]:.3f}"})
    _means = (
        mean_recall_at_k([r for r, _ in _toy.values()], [rel for _, rel in _toy.values()], 5),
        mean_recall_at_k([r for r, _ in _toy.values()], [rel for _, rel in _toy.values()], 10),
        mrr([r for r, _ in _toy.values()], [rel for _, rel in _toy.values()], 10),
    )
    if not all(math.isclose(a, b) for a, b in zip(_means, (1 / 3, 2 / 3, 0.3125))):
        raise AssertionError(f"самопроверка средних не прошла: {_means}")
    metrics_selfcheck = "пройдена"
    mo.vstack(
        [
            mo.md("## 3. Метрики: Recall@5, Recall@10, MRR@10\n\nФормулы — rag.md, раздел 9. Главная метрика выбора — Recall@5 (в контекст LLM идут первые 5 рефератов), при равенстве — MRR, затем Recall@10."),
            mo.callout(mo.md("**Иллюстрация, не результат:** выдуманные выдачи D1…D12 проверяют формулы; самопроверка пройдена."), kind="neutral"),
            mo.md(markdown_table(_rows, ["запрос", "Recall@5", "Recall@10", "1 / rank"])),
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
    EXPERIMENTS_C = (
        {"run": "C1", "title_boost": 2, "ipc_tokens": False, "extra_stopwords": (),
         "change": "название ×2 (title boost)", "question": "важнее ли название, чем реферат"},
        {"run": "C2", "title_boost": 1, "ipc_tokens": True, "extra_stopwords": (),
         "change": "коды МПК записи как токены документа", "question": "помогают ли коды МПК"},
        {"run": "C3", "title_boost": 1, "ipc_tokens": False, "extra_stopwords": ("способ", "устройство", "система"),
         "change": "расширенный стоп-список: + «способ», «устройство», «система»", "question": "шум эти слова или сигнал"},
    )
    return BASE_B, BASE_K1, B_GRID, EXPERIMENTS_A, EXPERIMENTS_C, K1_GRID


@app.cell
def _(BASE_B, BASE_K1, corpus, mean_recall_at_k, mrr, recall_at_k, reciprocal_rank):
    try:
        from app.search.engine import SearchConfig, SearchEngine
        from app.search.preprocess import PreprocessConfig
    except ImportError as _import_error:
        bm25_ready = False
        bm25_status = f"модули app.search не найдены ({_import_error})"
    else:
        try:
            SearchEngine(corpus[:1], SearchConfig())
        except NotImplementedError as _error:
            bm25_ready = False
            bm25_status = f"не реализован (NotImplementedError: {_error})"
        else:
            bm25_ready = True
            bm25_status = "реализован: собственный индекс и BM25 (app/search)"

    _engines = {}


    def engine_for(run):
        """SearchEngine под прогон; индекс общий для прогонов с одинаковой обработкой документов."""
        key = (
            run["lemmatize"], run["general_stopwords"], run["patent_stopwords"],
            run.get("title_boost", 1), run.get("ipc_tokens", False), tuple(run.get("extra_stopwords", ())),
        )
        if key not in _engines:
            _engines[key] = SearchEngine(
                corpus,
                SearchConfig(
                    preprocess=PreprocessConfig(lemmatize=key[0], general_stopwords=key[1], patent_stopwords=key[2]),
                    title_boost=key[3], ipc_tokens=key[4], extra_stopwords=key[5],
                ),
            )
        return _engines[key].with_params(run.get("k1", BASE_K1), run.get("b", BASE_B))


    def evaluate_run(run, query_rows, top_k=10):
        """Recall@5, Recall@10, MRR@10 по запросам query_rows и выдачи (первые top_k id) для прогона."""
        engine = engine_for(run)
        rankings = [[doc_id for doc_id, _ in engine.search(row["query"], top_k=top_k)] for row in query_rows]
        relevants = [row["relevant"] for row in query_rows]
        return {
            "Recall@5": mean_recall_at_k(rankings, relevants, 5),
            "Recall@10": mean_recall_at_k(rankings, relevants, 10),
            "MRR": mrr(rankings, relevants, 10),
            "rankings": rankings,
            "per_query": [
                {"id": row["id"], "Recall@5": recall_at_k(r, row["relevant"], 5), "RR": reciprocal_rank(r, row["relevant"], 10)}
                for row, r in zip(query_rows, rankings)
            ],
        }


    def pick_best(results, simplicity):
        """Победитель rag.md, 8.4: Recall@5 → MRR → Recall@10 → более простая конфигурация."""
        return min(results, key=lambda item: (-item["Recall@5"], -item["MRR"], -item["Recall@10"], simplicity(item)))


    def metric_row(name, result):
        return {"прогон": name, "Recall@5": f"{result['Recall@5']:.3f}", "Recall@10": f"{result['Recall@10']:.3f}", "MRR": f"{result['MRR']:.3f}"}

    return bm25_ready, bm25_status, engine_for, evaluate_run, metric_row, pick_best


@app.cell(hide_code=True)
def _(EXPERIMENTS_A, bm25_ready, engine_for, markdown_table, mo, statistics):
    doc_length_stats = None
    if not bm25_ready:
        _view = mo.md("## 4. Длины документов\n\nПоявятся, когда BM25 будет реализован.")
    else:
        _engine = engine_for(EXPERIMENTS_A[-1])
        _lengths = sorted(_engine.index.doc_length(d) for d in _engine.index._doc_lengths)
        _avgdl = _engine.index.avgdl
        _ratios = [length / _avgdl for length in _lengths]
        _buckets = [(0, 0.5), (0.5, 0.75), (0.75, 1.0), (1.0, 1.25), (1.25, 1.5), (1.5, 2.0), (2.0, 99)]
        _hist = [
            {"|D| / avgdl": f"{lo}–{hi}" if hi < 99 else f"≥ {lo}", "документов": sum(lo <= r < hi for r in _ratios),
             "": "█" * sum(lo <= r < hi for r in _ratios)}
            for lo, hi in _buckets
        ]
        doc_length_stats = {
            "min": _lengths[0], "median": statistics.median(_lengths), "max": _lengths[-1], "avgdl": _avgdl,
            "share_0_75_1_25": sum(0.75 <= r < 1.25 for r in _ratios) / len(_ratios),
        }
        _view = mo.md(
            "## 4. Длины документов (A5: название + реферат после полной предобработки)\n\n"
            f"|D| от {_lengths[0]} до {_lengths[-1]} токенов, медиана {statistics.median(_lengths):.0f}, avgdl = {_avgdl:.1f}. "
            f"В пределах 0,75–1,25 avgdl — {doc_length_stats['share_0_75_1_25']:.0%} документов: от этого разброса зависит, насколько влияет b (rag.md, 6).\n\n"
            + markdown_table(_hist, ["|D| / avgdl", "документов", ""])
        )
    _view
    return (doc_length_stats,)


@app.cell(hide_code=True)
def _(
    EXPERIMENTS_A,
    bm25_ready,
    dev_queries,
    evaluate_run,
    markdown_table,
    metric_row,
    mo,
    pick_best,
    real_benchmark,
):
    best_a = None
    results_a = []
    wins_a = []
    if not bm25_ready or not real_benchmark:
        _view = mo.md("## 5. Блок A\n\nНужны реализованный BM25 и реальные запросы `benchmark/queries.jsonl`.")
    else:
        results_a = [{**_run, **evaluate_run(_run, dev_queries), "position": _position} for _position, _run in enumerate(EXPERIMENTS_A)]
        best_a = pick_best(results_a, simplicity=lambda item: item["position"])
        _base = results_a[0]["per_query"]
        for _res in results_a[1:]:
            _won = sum(a["Recall@5"] > b["Recall@5"] for a, b in zip(_res["per_query"], _base))
            _lost = sum(a["Recall@5"] < b["Recall@5"] for a, b in zip(_res["per_query"], _base))
            wins_a.append({"прогон": _res["run"], "лучше A1": _won, "хуже A1": _lost, "так же": len(_base) - _won - _lost})
        _view = mo.md(
            f"## 5. Блок A (dev, {len(dev_queries)} запросов; k1 = 1.2, b = 0.75)\n\n"
            + markdown_table([metric_row(r["run"], r) for r in results_a], ["прогон", "Recall@5", "Recall@10", "MRR"])
            + "\n\n**По запросам — Recall@5 относительно A1** (rag.md, 8.4: одна найденная или потерянная запись меняет средний Recall@5 на ~0,02):\n\n"
            + markdown_table(wins_a, ["прогон", "лучше A1", "хуже A1", "так же"])
            + f"\n\nЛучшая предобработка: **{best_a['run']}**."
        )
    _view
    return best_a, results_a, wins_a


@app.cell(hide_code=True)
def _(EXPERIMENTS_A, bm25_ready, engine_for, markdown_table, mo, pooling, queries, real_benchmark):
    pooling_stats = None
    if not bm25_ready or not real_benchmark:
        _view = mo.md("## 6. Pooling\n\nПоявится после блока A.")
    else:
        _pool = {}
        for _run in EXPERIMENTS_A:
            _engine = engine_for(_run)
            for _row in queries:
                for _doc_id, _ in _engine.search(_row["query"], top_k=10):
                    if _doc_id not in _row["relevant"]:
                        _pool.setdefault((_row["id"], _doc_id), []).append(_run["run"])
        _judged = {(p["query"], p["doc"]): p for p in pooling}
        _added = [p for p in pooling if p.get("relevant")]
        _unjudged = sorted(key for key in _pool if key not in _judged)
        pooling_stats = {"просмотрено": len(pooling), "добавлено в relevant": len(_added), "не просмотрено": len(_unjudged)}
        _view = mo.vstack(
            [
                mo.md(
                    "## 6. Pooling (rag.md, 10.3)\n\n"
                    "После первого прогона блока A по всем запросам просмотрены документы из первых 10 результатов A1–A5, "
                    f"которых нет в `relevant`: {len(pooling)} пар «запрос — документ», решения — `benchmark/pooling.jsonl`. "
                    f"Найдено и добавлено в `relevant` пропусков: {len(_added)}. После этого разметка заморожена."
                ),
                mo.md(markdown_table(
                    [{"запрос": p["query"], "документ": p["doc"], "почему релевантен": p.get("note", "")} for p in _added],
                    ["запрос", "документ", "почему релевантен"],
                ) if _added else "Пропусков не найдено."),
                mo.callout(
                    mo.md("Непросмотренные пары (появились после изменения корпуса или запросов):\n\n" + ", ".join(f"{q}/{d}" for q, d in _unjudged[:40])),
                    kind="warn",
                ) if _unjudged else mo.md("Все пары пула просмотрены."),
            ]
        )
    _view
    return (pooling_stats,)


@app.cell(hide_code=True)
def _(BASE_B, BASE_K1, B_GRID, K1_GRID, best_a, dev_queries, evaluate_run, markdown_table, mo, pick_best):
    best_b = None
    results_b = []
    if best_a is None:
        _view = mo.md("## 7. Блок B\n\nСетка k1 × b появится после блока A.")
    else:
        results_b = [
            {**best_a, "run": f"B({k1}, {b})", "k1": k1, "b": b, **evaluate_run({**best_a, "k1": k1, "b": b}, dev_queries)}
            for k1 in K1_GRID
            for b in B_GRID
        ]
        best_b = pick_best(results_b, simplicity=lambda item: abs(item["k1"] - BASE_K1) + abs(item["b"] - BASE_B))
        _by_params = {(r["k1"], r["b"]): r for r in results_b}
        _matrix = [{"k1 \\ b": k1, **{str(b): f"{_by_params[(k1, b)]['Recall@5']:.3f}" for b in B_GRID}} for k1 in K1_GRID]
        _mrr = [{"k1 \\ b": k1, **{str(b): f"{_by_params[(k1, b)]['MRR']:.3f}" for b in B_GRID}} for k1 in K1_GRID]
        _view = mo.md(
            f"## 7. Блок B (dev): сетка k1 × b, предобработка {best_a['run']}\n\n**Recall@5:**\n\n"
            + markdown_table(_matrix, ["k1 \\ b", *[str(b) for b in B_GRID]])
            + "\n\n**MRR@10:**\n\n"
            + markdown_table(_mrr, ["k1 \\ b", *[str(b) for b in B_GRID]])
            + f"\n\nЛучшие параметры: **{best_b['run']}** (Recall@5 {best_b['Recall@5']:.3f}, MRR {best_b['MRR']:.3f}, Recall@10 {best_b['Recall@10']:.3f})."
        )
    _view
    return best_b, results_b


@app.cell(hide_code=True)
def _(EXPERIMENTS_C, best_a, best_b, dev_queries, evaluate_run, markdown_table, metric_row, mo):
    final_run = None
    final_name = None
    results_c = []
    kept_c = []
    if best_a is None or best_b is None:
        _view = mo.md("## 8. Блок C\n\nПоявится после блоков A и B.")
    else:
        base_run = {key: best_b[key] for key in ("lemmatize", "general_stopwords", "patent_stopwords", "k1", "b")}
        _base_dev = evaluate_run(base_run, dev_queries)
        results_c = [(_run, evaluate_run({**base_run, **_run}, dev_queries)) for _run in EXPERIMENTS_C]

        def _dev_key(result):
            """Порядок сравнения rag.md, 8.4: Recall@5, затем MRR, затем Recall@10."""
            return (round(result["Recall@5"], 6), round(result["MRR"], 6), round(result["Recall@10"], 6))

        # rag.md, 8.3, п. 4: оставляем опыты C, которые на dev лучше базы A + B (равенство — не улучшение)
        kept_c = [_run for _run, _res in results_c if _dev_key(_res) > _dev_key(_base_dev)]
        final_run = {
            **base_run,
            "title_boost": max([1, *(_run["title_boost"] for _run in kept_c)]),
            "ipc_tokens": any(_run["ipc_tokens"] for _run in kept_c),
            "extra_stopwords": tuple(_word for _run in kept_c for _word in _run["extra_stopwords"]),
        }
        final_name = f"{best_a['run'].split(' ')[0]} + {best_b['run']}" + "".join(f" + {_run['run']}" for _run in kept_c)
        _rows = [metric_row(f"база: {best_a['run'].split(' ')[0]} + {best_b['run']}", _base_dev)]
        _rows += [metric_row(f"{_run['run']}: {_run['change']}", _res) for _run, _res in results_c]
        _view = mo.md(
            "## 8. Блок C (dev)\n\n" + markdown_table(_rows, ["прогон", "Recall@5", "Recall@10", "MRR"])
            + "\n\nОпыты C оставляем, только если они улучшили dev (rag.md, 8.3). "
            + (("Улучшили dev: " + ", ".join(_run["run"] for _run in kept_c) + ".") if kept_c else "Ни один опыт C не улучшил dev.")
            + f" Итоговая конфигурация: **{final_name}**."
        )
    _view
    return final_name, final_run, kept_c, results_c


@app.cell(hide_code=True)
def _(EXPERIMENTS_A, best_a, evaluate_run, final_name, final_run, markdown_table, metric_row, mo, test_queries):
    test_results = []
    if final_run is None:
        _view = mo.md("## 9. Итог на test\n\nПоявится после блоков A, B и C.")
    else:
        # test считаем один раз, в конце; по нему ничего не подбираем (rag.md, 8.3)
        test_results = [
            ("A1 (baseline)", evaluate_run(EXPERIMENTS_A[0], test_queries)),
            (f"лучшая A: {best_a['run']}", evaluate_run(best_a, test_queries)),
            (f"итоговая: {final_name}", evaluate_run(final_run, test_queries)),
        ]
        _view = mo.md(
            f"## 9. Итог на test ({len(test_queries)} запросов, считается один раз)\n\n"
            + markdown_table([metric_row(name, res) for name, res in test_results], ["прогон", "Recall@5", "Recall@10", "MRR"])
        )
    _view
    return (test_results,)


@app.cell(hide_code=True)
def _(dev_queries, engine_for, final_run, markdown_table, math, mo, offtopic, statistics, test_queries):
    min_score_info = None
    if final_run is None or not offtopic:
        _view = mo.md("## 10. Порог MIN_SCORE\n\nПоявится после выбора конфигурации и при наличии `benchmark/offtopic.jsonl`.")
    else:
        _engine = engine_for(final_run)

        def _top1(text):
            found = _engine.search(text, top_k=1)
            return found[0][1] if found else 0.0

        def _relevant_in_top5(rows):
            return [s for row in rows for d, s in _engine.search(row["query"], top_k=5) if d in row["relevant"]]

        def _relative_top1(text):
            bound = _engine.score_upper_bound(text)
            return _top1(text) / bound if bound else 0.0

        def _relative_relevant_in_top5(rows):
            return [s / _engine.score_upper_bound(row["query"]) for row in rows
                    for d, s in _engine.search(row["query"], top_k=5) if d in row["relevant"]]

        _dev_top1 = [_top1(row["query"]) for row in dev_queries]
        _off_top1 = [_top1(row["query"]) for row in offtopic]
        _rel_scores = _relevant_in_top5(dev_queries)
        _off_max = max(_off_top1)
        _rel_min = min(_rel_scores) if _rel_scores else 0.0
        _rel_rel_min = min(_relative_relevant_in_top5(dev_queries))
        _off_rel_max = max(_relative_top1(row["query"]) for row in offtopic)
        # rag.md, 7: порог должен отсечь посторонние запросы (score первого результата < порога)
        # и не выбросить релевантные документы из первых 5 у dev-запросов (score >= порога).
        # Сначала абсолютный порог; если он не разделяет — относительный (доля от верхней
        # границы score запроса); если не разделяет и он — не теряем релевантные: порог =
        # минимум score релевантных из первых 5 на dev, округлённый вниз до 2 знаков.
        if _off_max < _rel_min:
            _threshold = math.floor((_off_max + 0.01) * 100) / 100
            _rule = f"абсолютный порог разделяет: чуть выше максимума посторонних ({_off_max:.2f})"
        elif _off_rel_max < _rel_rel_min:
            _threshold = None
            _rule = f"абсолютный порог не разделяет, относительный разделяет (посторонние ≤ {_off_rel_max:.3f} < {_rel_rel_min:.3f})"
        else:
            _threshold = math.floor(_rel_min * 100) / 100
            _rule = (
                f"не разделяет ни абсолютный порог (посторонние до {_off_max:.2f}, релевантные из первых 5 от {_rel_min:.2f}), "
                f"ни относительный (посторонние до {_off_rel_max:.3f}, релевантные от {_rel_rel_min:.3f}); порог = минимум score "
                "релевантных из первых 5 на dev, округлённый вниз, — релевантные не теряем, отказ на посторонние — задача промпта"
            )
        _cut_off = sum(s < _threshold for s in _off_top1) if _threshold is not None else 0
        _test_rel = _relevant_in_top5(test_queries)
        _test_lost = sum(s < _threshold for s in _test_rel) if _threshold is not None else 0
        _test_top1 = [_top1(row["query"]) for row in test_queries]
        min_score_info = {
            "MIN_SCORE": _threshold, "rule": _rule, "offtopic_max": _off_max, "relevant_min_dev": _rel_min,
            "offtopic_relative_max": _off_rel_max, "relevant_relative_min_dev": _rel_rel_min,
            "offtopic_cut": _cut_off, "offtopic_total": len(_off_top1),
            "test_relevant_top5": len(_test_rel), "test_relevant_lost": _test_lost,
            "test_empty": sum(s < _threshold for s in _test_top1) if _threshold is not None else 0,
        }
        _off_rel = [_relative_top1(row["query"]) for row in offtopic]
        _dev_rel = _relative_relevant_in_top5(dev_queries)
        _rows = [
            {"набор": "dev: score первого результата", "мин": f"{min(_dev_top1):.2f}", "медиана": f"{statistics.median(_dev_top1):.2f}", "макс": f"{max(_dev_top1):.2f}"},
            {"набор": "dev: score релевантных в первых 5", "мин": f"{_rel_min:.2f}", "медиана": f"{statistics.median(_rel_scores):.2f}", "макс": f"{max(_rel_scores):.2f}"},
            {"набор": "посторонние: score первого результата", "мин": f"{min(_off_top1):.2f}", "медиана": f"{statistics.median(_off_top1):.2f}", "макс": f"{_off_max:.2f}"},
            {"набор": "dev: релевантные в первых 5, доля от верхней границы", "мин": f"{min(_dev_rel):.3f}", "медиана": f"{statistics.median(_dev_rel):.3f}", "макс": f"{max(_dev_rel):.3f}"},
            {"набор": "посторонние: первый результат, доля от верхней границы", "мин": f"{min(_off_rel):.3f}", "медиана": f"{statistics.median(_off_rel):.3f}", "макс": f"{max(_off_rel):.3f}"},
        ]
        min_score_info["table"] = _rows
        _view = mo.md(
            "## 10. Порог MIN_SCORE (rag.md, раздел 7)\n\n"
            + markdown_table(_rows, ["набор", "мин", "медиана", "макс"])
            + f"\n\nПравило: {_rule}. **MIN_SCORE = {_threshold:.2f}**: отсечено посторонних {_cut_off} из {len(_off_top1)}. "
            + f"Проверка на test: релевантных в первых 5 — {len(_test_rel)}, из них ниже порога — {_test_lost}; "
            + f"запросов test с пустой выдачей — {min_score_info['test_empty']} из {len(test_queries)}."
        )
    _view
    return (min_score_info,)


@app.cell
def _(mo):
    k1_slider = mo.ui.slider(0.0, 3.0, step=0.1, value=1.2, label="k1")
    b_slider = mo.ui.slider(0.0, 1.0, step=0.05, value=0.75, label="b")
    query_input = mo.ui.text_area(
        value="Хочу, чтобы огород поливался сам, когда земля подсыхает", label="Запрос", full_width=True
    )
    return b_slider, k1_slider, query_input


@app.cell(hide_code=True)
def _(b_slider, bm25_ready, corpus_by_id, engine_for, final_run, k1_slider, markdown_table, mo, query_input):
    if not bm25_ready or final_run is None:
        _view = mo.md("## 11. Ручная проверка\n\nПоявится после выбора конфигурации.")
    elif mo.app_meta().mode == "script":
        _view = mo.md("")
    else:
        _engine = engine_for({**final_run, "k1": k1_slider.value, "b": b_slider.value})
        _hits = _engine.search(query_input.value, top_k=10)
        _view = mo.vstack(
            [
                mo.md("## 11. Ручная проверка: k1 и b на итоговой предобработке"),
                mo.hstack([k1_slider, b_slider]),
                query_input,
                mo.md(markdown_table(
                    [{"№": i, "id": d, "score": f"{s:.2f}", "название": corpus_by_id[d]["title"]} for i, (d, s) in enumerate(_hits, 1)],
                    ["№", "id", "score", "название"],
                ) if _hits else "Ничего не найдено."),
            ]
        )
    _view
    return


@app.cell(hide_code=True)
def _(
    bm25_status,
    corpus,
    corpus_errors,
    data_files,
    dev_queries,
    doc_length_stats,
    extra_errors,
    final_name,
    final_run,
    format_errors,
    is_demo_corpus,
    metric_row,
    metrics_selfcheck,
    min_score_info,
    mo,
    pooling_stats,
    queries,
    results_a,
    results_b,
    best_b,
    results_c,
    test_queries,
    test_results,
    topic_rows,
    versions,
    wins_a,
):
    def _fmt(name, res):
        row = metric_row(name, res)
        return f"  {row['прогон']:<45} Recall@5 {row['Recall@5']}  Recall@10 {row['Recall@10']}  MRR {row['MRR']}"

    _lines = ["Патентный радар — benchmark поиска (КТ2)"]
    _lines += [f"{f['что']}: {f['файл'].strip('`')} — записей: {f['записей']}, SHA-256 {f['SHA-256 (начало)'].strip('`')}" for f in data_files]
    _lines.append(f"Версии: {versions}")
    _lines.append(f"Корпус: {len(corpus)} записей" + (" (демонстрационные данные)" if is_demo_corpus else "") + (" — ОШИБКИ: " + "; ".join(corpus_errors) if corpus_errors else ""))
    _lines.append(f"Запросы: {len(queries)} (dev: {len(dev_queries)}, test: {len(test_queries)}, тем: {len(topic_rows)})")
    _lines.append("Формат benchmark: OK" if not format_errors and not extra_errors else "Формат benchmark: ОШИБКИ — " + "; ".join(format_errors + extra_errors))
    _lines.append(f"Метрики: самопроверка на игрушечном примере {metrics_selfcheck}")
    _lines.append(f"BM25: {bm25_status}")
    if doc_length_stats:
        _lines.append(
            f"Длины документов (A5): от {doc_length_stats['min']} до {doc_length_stats['max']}, медиана {doc_length_stats['median']:.0f}, "
            f"avgdl {doc_length_stats['avgdl']:.1f}; в пределах 0,75–1,25 avgdl — {doc_length_stats['share_0_75_1_25']:.0%}"
        )
    if results_a:
        _lines.append(f"Блок A (dev, {len(dev_queries)} запросов):")
        _lines += [_fmt(r["run"], r) for r in results_a]
        _lines += [f"  {w['прогон']}: лучше A1 — {w['лучше A1']}, хуже — {w['хуже A1']}, так же — {w['так же']}" for w in wins_a]
    if pooling_stats:
        _lines.append("Pooling: " + ", ".join(f"{k} {v}" for k, v in pooling_stats.items()))
    if results_b:
        _top = sorted(results_b, key=lambda r: (-r["Recall@5"], -r["MRR"], -r["Recall@10"]))[:5]
        _lines.append("Блок B (dev), лучшие 5 из 20:")
        _lines += [_fmt(r["run"], r) for r in _top]
        _lines.append(f"  выбрано: {best_b['run']}")
        _lines.append("  Recall@5 по сетке: " + "; ".join(f"{r['run']} {r['Recall@5']:.3f}" for r in results_b))
    if results_c:
        _lines.append("Блок C (dev):")
        _lines += [_fmt(f"{run['run']}: {run['change']}", res) for run, res in results_c]
        _lines.append(f"Итоговая конфигурация: {final_name}")
    if test_results:
        _lines.append(f"Test ({len(test_queries)} запросов, один раз):")
        _lines += [_fmt(name, res) for name, res in test_results]
    if final_run is not None:
        try:
            from app.search.config import MIN_SCORE as _cfg_min_score, SELECTED_CONFIG as _cfg
        except ImportError:
            _lines.append("app/search/config.py: нет файла")
        else:
            _same = (
                (_cfg.preprocess.lemmatize, _cfg.preprocess.general_stopwords, _cfg.preprocess.patent_stopwords,
                 _cfg.k1, _cfg.b, _cfg.title_boost, _cfg.ipc_tokens, tuple(_cfg.extra_stopwords))
                == (final_run["lemmatize"], final_run["general_stopwords"], final_run["patent_stopwords"],
                    final_run["k1"], final_run["b"], final_run["title_boost"], final_run["ipc_tokens"], tuple(final_run["extra_stopwords"]))
            )
            _same_threshold = min_score_info is not None and _cfg_min_score == min_score_info["MIN_SCORE"]
            _lines.append(
                "app/search/config.py: конфигурация " + ("совпадает с итоговой" if _same else "НЕ совпадает с итоговой — обновите config.py")
                + ", MIN_SCORE " + ("совпадает" if _same_threshold else "НЕ совпадает — обновите config.py")
            )
    if min_score_info:
        _lines.append(
            f"MIN_SCORE = {min_score_info['MIN_SCORE']:.2f} ({min_score_info['rule']}); посторонних отсечено "
            f"{min_score_info['offtopic_cut']} из {min_score_info['offtopic_total']} (max {min_score_info['offtopic_max']:.2f}); "
            f"min score релевантных в первых 5 на dev {min_score_info['relevant_min_dev']:.2f}; test: релевантных в первых 5 "
            f"{min_score_info['test_relevant_top5']}, ниже порога {min_score_info['test_relevant_lost']}, пустых выдач {min_score_info['test_empty']}"
        )
    if min_score_info:
        _lines += [f"  {r['набор']}: мин {r['мин']}, медиана {r['медиана']}, макс {r['макс']}" for r in min_score_info["table"]]
    _summary = "\n".join(_lines)
    if mo.app_meta().mode == "script":
        print(_summary)
    mo.md("## Сводка\n\n```text\n" + _summary + "\n```")
    return


if __name__ == "__main__":
    app.run()
