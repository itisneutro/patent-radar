"""Выбранная конфигурация поиска и порог «ничего не найдено» — итог экспериментов КТ2.

Значения взяты из прогона `python benchmark/experiments.py` (spec/tech/rag.md, раздел
«Результаты КТ2»): победитель блоков A, B и C на dev-части по правилу раздела 8.4 и порог
MIN_SCORE по распределению score с посторонними запросами (раздел 7). Тетрадка сверяет
эти значения со своим победителем и пишет в сводке, если они разошлись.

API (app/api) и прогон ответов benchmark/evaluate_answers.py берут конфигурацию отсюда.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from .engine import SearchConfig, SearchEngine
from .preprocess import PreprocessConfig

SELECTED_CONFIG = SearchConfig(
    # A4: лемматизация и общие стоп-слова; патентные стоп-слова метрик на dev не изменили (A5 = A4),
    # при равенстве выбирается более простая конфигурация (rag.md, 8.4)
    preprocess=PreprocessConfig(lemmatize=True, general_stopwords=True, patent_stopwords=False),
    # B(1.2, 0.5): лучший MRR при максимальном Recall@5 на dev
    k1=1.2,
    b=0.5,
    # C1: название входит в документ дважды — улучшил MRR на dev
    title_boost=2,
    ipc_tokens=False,
    extra_stopwords=(),
)
"""Итоговая конфигурация: A4 + B(1.2, 0.5) + C1."""

MIN_SCORE = 4.42
"""Порог score: в выдачу попадают документы со score >= MIN_SCORE (rag.md, раздел 7).

Минимум score релевантных документов из первых 5 у dev-запросов, округлённый вниз:
посторонние запросы набирают до 8.41, поэтому порог их почти не отсекает; отказ на
запросы без аналогов — задача промпта (app/llm/prompts.py).
"""


def build_engine(records: Iterable[Mapping]) -> SearchEngine:
    """Поисковый движок по записям корпуса с выбранной конфигурацией."""
    return SearchEngine(records, SELECTED_CONFIG)
