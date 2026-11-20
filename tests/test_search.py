"""Тесты поиска: предобработка, инвертированный индекс, BM25 (spec/tech/rag.md, разделы 4–6).

Ожидаемые значения — из спецификации (трассировки раздела 4.7, примеры разделов 4.1–4.6
и 6) и из докстрингов модулей, а не из вывода кода. Сеть и Ollama не нужны.
"""

from __future__ import annotations

import doctest
import json
import math
import unicodedata
from pathlib import Path

import pytest

from app.llm import prompts as prompts_module
from app.search import bm25 as bm25_module
from app.search import config as config_module
from app.search import engine as engine_module
from app.search import index as index_module
from app.search import preprocess as preprocess_module
from app.search.bm25 import BM25
from app.search.index import InvertedIndex
from app.search.preprocess import (
    GENERAL_STOPWORDS,
    PATENT_STOPWORDS,
    PreprocessConfig,
    expand_wordforms,
    extract_ipc_codes,
    fold_yo,
    lemmatize,
    normalize,
    preprocess,
    remove_stopwords,
    stopwords_for,
    tokenize,
)

ROOT = Path(__file__).resolve().parents[1]
DEMO_QUERY = (
    "Хочу, чтобы грядки на даче поливались сами: датчик в земле замечает, что почва пересохла, "
    "и включает воду, а если обещают дождь, полив не включается."
)
A1 = PreprocessConfig(lemmatize=False, general_stopwords=False, patent_stopwords=False)
A3 = PreprocessConfig(lemmatize=False, general_stopwords=True, patent_stopwords=True)


@pytest.mark.parametrize("module", [preprocess_module, index_module, bm25_module, engine_module, prompts_module])
def test_docstring_examples(module) -> None:
    """Примеры из докстрингов модулей выполняются как doctest."""
    result = doctest.testmod(module, optionflags=doctest.NORMALIZE_WHITESPACE)
    assert result.failed == 0, f"{module.__name__}: {result.failed} из {result.attempted} примеров не прошли"
    assert result.attempted > 0


def test_normalize_glues_decomposed_letters() -> None:
    """rag.md, 4.1: без NFC «й» и «ё» в разложенной форме рвут слово."""
    text = unicodedata.normalize("NFD", "Беспроводной датчик, ёмкостный элемент")
    assert tokenize(text.lower()) == ["беспроводнои", "датчик", "е", "мкостныи", "элемент"]
    assert tokenize(normalize(text)) == ["беспроводной", "датчик", "ёмкостный", "элемент"]


@pytest.mark.parametrize(
    ("text", "codes", "rest"),
    [
        (
            "Датчик по МПК G01N 33/24 и A01G 25/16 (2006.01), см. также G05B19/042",
            ["g01n33/24", "a01g25/16", "g05b19/042"],
            ["датчик", "по", "мпк", "и", "см", "также"],
        ),
        ("Аналоги в А01G 25/16 и Н04W 4/38", ["a01g25/16", "h04w4/38"], ["аналоги", "в", "и"]),
    ],
)
def test_extract_ipc_codes(text: str, codes: list[str], rest: list[str]) -> None:
    """rag.md, 4.2: коды — одним токеном, кириллические двойники -> латиница, версия отброшена."""
    found, remainder = extract_ipc_codes(normalize(text))
    assert found == codes
    assert tokenize(remainder) == rest


def test_tokenize_keeps_hyphenated_words() -> None:
    """rag.md, 4.3."""
    text = normalize("Покрытие кремний-органическое, связь по Wi-Fi, 12 часов, 0,5 л, т. е. «умный» полив — проект")
    assert tokenize(text) == [
        "покрытие", "кремний-органическое", "связь", "по", "wi-fi", "12", "часов",
        "0", "5", "л", "т", "е", "умный", "полив", "проект",
    ]


@pytest.mark.parametrize(
    ("word", "lemma"),
    [
        ("отличающийся", "отличаться"),
        ("отличается", "отличаться"),
        ("поливались", "поливаться"),
        ("воду", "вода"),
        ("установленный", "установленный"),
        ("установлен", "установить"),
        ("полив", "полить"),
        ("полива", "полив"),
        ("кремний-органическим", "кремний-органический"),
        ("емкостные", "ёмкостный"),
    ],
)
def test_lemmatize_matches_spec(word: str, lemma: str) -> None:
    """rag.md, 4.4: parse()[0].normal_form, включая известные неоднозначности."""
    assert lemmatize([word]) == [lemma]


def test_lemmatize_skips_non_cyrillic_tokens() -> None:
    assert lemmatize(["a01g25/16", "wi-fi", "12", "co2"]) == ["a01g25/16", "wi-fi", "12", "co2"]


def test_fold_yo_after_lemmatization() -> None:
    """rag.md, 4.4: «причем» и «причём» дают один токен."""
    assert fold_yo(lemmatize(["причем", "причём"])) == ["причем", "причем"]


def test_stopword_lists_as_in_spec() -> None:
    """rag.md, 4.5–4.6: 78 общих и 23 патентных леммы; без лемматизации — 1224 словоформы."""
    assert len(GENERAL_STOPWORDS) == 78
    assert len(PATENT_STOPWORDS) == 23
    assert not any("ё" in word for word in GENERAL_STOPWORDS | PATENT_STOPWORDS)
    assert len(stopwords_for(A3)) == 1224
    forms = expand_wordforms(["мочь", "отличаться", "в"])
    assert {"может", "могут", "мог", "отличающийся", "отличающаяся", "во"} <= forms
    assert stopwords_for(A1) == frozenset()


def test_remove_stopwords_keeps_order() -> None:
    assert remove_stopwords(["отличаться", "тем", "что", "контроллер", "и", "клапан"], stopwords_for(PreprocessConfig())) == [
        "контроллер",
        "клапан",
    ]


def test_preprocess_demo_query_trace() -> None:
    """rag.md, 4.7: основной демо-запрос, конфигурация A5 — 15 токенов."""
    assert preprocess(DEMO_QUERY) == [
        "хотеть", "грядка", "дача", "поливаться", "сам", "датчик", "земля", "замечать",
        "почва", "пересохнуть", "вода", "обещать", "дождь", "полить", "включаться",
    ]


def test_preprocess_demo_query_without_lemmatization() -> None:
    """rag.md, 4.7: опыт A3 — те же 15 позиций, но словоформы."""
    assert preprocess(DEMO_QUERY, A3) == (
        "хочу грядки даче поливались сами датчик земле замечает почва пересохла воду обещают дождь полив включается"
    ).split()


def test_preprocess_demo_abstract_fragment() -> None:
    """rag.md, 4.7: фрагмент реферата DEMO-001 — 19 токенов, «ёмкостный» -> «емкостный»."""
    fragment = (
        "Система автоматического полива, содержащая ёмкостные датчики влажности почвы, контроллер и "
        "электромагнитные клапаны, установленные на линиях подачи воды к зонам полива, отличающаяся тем, "
        "что контроллер выполнен с возможностью открывать клапан зоны"
    )
    assert preprocess(fragment) == (
        "система автоматический полив емкостный датчик влажность почва контроллер электромагнитный клапан "
        "линия подача вода зона полив контроллер открывать клапан зона"
    ).split()


def test_preprocess_puts_ipc_codes_last() -> None:
    assert preprocess("Датчик по МПК G01N 33/24 (2006.01)") == ["датчик", "мпк", "g01n33/24"]


def test_index_structures() -> None:
    index = InvertedIndex.build([("D1", ["полив", "почва", "полив"]), ("D2", ["датчик", "почва"]), ("D3", [])])
    assert dict(index.postings("полив")) == {"D1": 2}
    assert index.doc_freq("почва") == 2 and index.doc_freq("зонт") == 0
    assert index.n_docs == 3 and index.doc_length("D3") == 0
    assert math.isclose(index.avgdl, 5 / 3)
    with pytest.raises(ValueError):
        index.add_document("D1", ["вода"])
    with pytest.raises(TypeError):
        index.postings("полив")["D9"] = 1  # postings только для чтения


def test_index_save_load_roundtrip(tmp_path: Path) -> None:
    index = InvertedIndex.build([("D1", ["полив", "полив"]), ("D2", ["почва"])])
    path = tmp_path / "index.json"
    index.save(path)
    loaded = InvertedIndex.load(path)
    assert dict(loaded.postings("полив")) == {"D1": 2}
    assert loaded.n_docs == 2 and loaded.avgdl == index.avgdl


def test_bm25_idf_values_from_spec() -> None:
    """rag.md, 6 и докстринг BM25.idf: при N = 3 термин из 1, 2, 3 документов."""
    index = InvertedIndex.build([("D1", ["a", "b", "c"]), ("D2", ["b", "c"]), ("D3", ["c"])])
    bm25 = BM25(index)
    assert [round(bm25.idf(t), 4) for t in ("a", "b", "c")] == [0.9808, 0.4700, 0.1335]
    assert bm25.idf("c") > 0


def test_bm25_ranking_rules() -> None:
    index = InvertedIndex.build([("D2", ["полив"]), ("D1", ["полив"]), ("D3", ["почва"])])
    bm25 = BM25(index)
    # одинаковый score — порядок по id; документ без общих терминов не возвращается
    assert [doc for doc, _ in bm25.search(["полив"])] == ["D1", "D2"]
    # повтор термина в запросе не меняет score
    assert bm25.search(["полив", "полив"]) == bm25.search(["полив"])
    assert len(bm25.search(["полив", "почва"], top_k=None)) == 3
    assert bm25.search(["полив", "почва"], top_k=1) == bm25.search(["полив", "почва"])[:1]
    assert math.isclose(bm25.score(["полив"], "D1"), bm25.search(["полив"])[0][1])


def test_bm25_parameters_validation_and_effect() -> None:
    with pytest.raises(ValueError):
        BM25(InvertedIndex(), k1=-0.1)
    with pytest.raises(ValueError):
        BM25(InvertedIndex(), b=1.5)
    index = InvertedIndex.build([("D1", ["полив"] * 3), ("D2", ["полив", "почва", "вода", "клапан"])])
    # k1 = 0: учитывается только наличие термина — оба документа равны
    s0 = dict(BM25(index, k1=0).search(["полив"]))
    assert math.isclose(s0["D1"], s0["D2"])
    # b = 0: длина не учитывается, при большем tf score выше
    s_b0 = dict(BM25(index, b=0).search(["полив"]))
    assert s_b0["D1"] > s_b0["D2"]


def test_demo_corpus_document_lengths() -> None:
    """rag.md, 6: длины демо-документов после полного конвейера — 61, 64 и 55 токенов."""
    path = ROOT / "data" / "sample" / "patents.jsonl"
    docs = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    lengths = {d["id"]: len(preprocess(d["title"]) + preprocess(d["abstract"])) for d in docs}
    assert lengths == {"DEMO-001": 61, "DEMO-002": 64, "DEMO-003": 55}


def _demo_records() -> list[dict]:
    path = ROOT / "data" / "sample" / "patents.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_search_engine_on_demo_corpus() -> None:
    from app.search.engine import SearchConfig, SearchEngine

    engine = SearchEngine(_demo_records())
    hits = engine.search(DEMO_QUERY)
    assert {doc_id for doc_id, _ in hits} <= {"DEMO-001", "DEMO-002", "DEMO-003"} and hits
    assert hits == sorted(hits, key=lambda item: (-item[1], item[0]))
    # верхняя граница score — Σ IDF · (k1 + 1): ни один документ её не превышает
    assert all(score <= engine.score_upper_bound(DEMO_QUERY) for _, score in hits)
    # with_params меняет только k1 и b, индекс общий
    other = engine.with_params(0.9, 0.3)
    assert other.index is engine.index and (other.config.k1, other.config.b) == (0.9, 0.3)
    # title_boost: токены названия входят в документ дважды
    boosted = SearchEngine(_demo_records(), SearchConfig(title_boost=2))
    assert boosted.index.doc_length("DEMO-003") > engine.index.doc_length("DEMO-003")


def test_selected_config_is_documented_choice() -> None:
    """app/search/config.py — итог экспериментов (rag.md, раздел 13): A4 + B(1.2, 0.5) + C1, MIN_SCORE = 4.42."""
    cfg = config_module.SELECTED_CONFIG
    assert (cfg.preprocess.lemmatize, cfg.preprocess.general_stopwords, cfg.preprocess.patent_stopwords) == (True, True, False)
    assert (cfg.k1, cfg.b, cfg.title_boost, cfg.ipc_tokens, cfg.extra_stopwords) == (1.2, 0.5, 2, False, ())
    assert config_module.MIN_SCORE == 4.42
    assert config_module.build_engine(_demo_records()).index.n_docs == 3


@pytest.mark.parametrize(
    ("paragraph", "expected"),
    [
        ("Аналог. Тоже паровой утюг.", True),
        ("аналог: тоже паровой утюг.", True),
        ("Не аналог. Это холодильник.", False),
        ("НЕ  АНАЛОГ — это холодильник.", False),
        ("Аналогичный утюг с паром.", None),
        ("Аналоги есть.", None),
        ("Похож на идею.", None),
    ],
)
def test_verdict_detection(paragraph: str, expected: bool | None) -> None:
    assert prompts_module.verdict(paragraph) is expected


def test_prompt_requires_verdicts_and_sources_only() -> None:
    """Промпт требует вердикт у каждого патента и запрещает факты не из рефератов."""
    system = prompts_module.SYSTEM_PROMPT
    assert prompts_module.ANALOG_VERDICT in system and prompts_module.NOT_ANALOG_VERDICT in system
    assert "только на приведённые рефераты" in system and "назначения" in system
    assert "без вступления и без заключения" in system
    messages = prompts_module.build_messages(DEMO_QUERY, [dict(r, score=1.0) for r in _demo_records()])
    user = messages[1]["content"]
    assert user.endswith("«[идентификатор] Аналог.» или «[идентификатор] Не аналог.».")
    assert "[DEMO-001], [DEMO-002], [DEMO-003]" in user

