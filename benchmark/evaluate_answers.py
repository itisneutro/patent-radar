"""Прогон ответов benchmark через конвейер POST /search: Accuracy и Correct Rejection Rate (КТ2).

Каждый обычный вопрос (benchmark/queries.jsonl, 24) и каждая ловушка (benchmark/traps.jsonl, 5)
проходят тот же конвейер, что POST /search (app/api/pipeline.py: BM25 выбранной конфигурации,
порог MIN_SCORE, первые 5 результатов в промпт, проверка ответа модели). Модель и её настройки —
из переменных LLM_* и файла .env, как у API (spec/tech/architecture.md, раздел 7).

Запуск из корня репозитория (нужны Ollama и модель patent-radar:7b — README, «Запуск»):

    python benchmark/evaluate_answers.py            # прогон: около 10 минут, пишет answers.jsonl
    python benchmark/evaluate_answers.py --score    # без модели: метрики по сохранённому прогону

Результаты:
- benchmark/results/answers.jsonl — по строке на вопрос: выдача (id и score), id из промпта,
  статус пояснения, вердикты, answer, сырой ответ модели, время и токены;
- benchmark/results/answers_review.md — ручная разметка ответов (spec/tech/rag.md, раздел 9.1):
  верно или неверно и где потеряли правильный ответ. Разметка привязана к прогону: в файле
  записан SHA-256 answers.jsonl, для которого она сделана.

Correct Rejection Rate считается автоматически: отказ — пустая выдача после MIN_SCORE (статус
no_results) или вердикт «Не аналог.» у всех патентов из промпта (статус no_analogs). Accuracy
считается только по ручной разметке: «полностью правильный» ответ проверяет человек. После нового
прогона (ответы модели при температуре 0.2 меняются от прогона к прогону) разметку нужно сделать
заново — скрипт сообщает, что она относится к другому прогону.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import statistics
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

from app.api.pipeline import SearchPipeline  # noqa: E402
from app.api.schemas import SearchRequest  # noqa: E402
from app.llm.client import LLMClient  # noqa: E402

QUERIES = ROOT / "benchmark" / "queries.jsonl"
TRAPS = ROOT / "benchmark" / "traps.jsonl"
RESULTS_DIR = ROOT / "benchmark" / "results"
ANSWERS = RESULTS_DIR / "answers.jsonl"
REVIEW = RESULTS_DIR / "answers_review.md"

#: Отказ на ловушку (spec/tech/rag.md, раздел 9.1).
REFUSAL_STATUSES = {"no_results", "no_analogs"}
#: Строка таблицы разметки: | id | набор | верно/неверно | где потеряли | обоснование |
REVIEW_ROW = re.compile(r"^\|\s*(Q-\d{3}|T-\d{2})\s*\|\s*(dev|test|ловушка)\s*\|\s*(верно|неверно)\s*\|\s*([^|]*?)\s*\|")
REVIEW_SHA = re.compile(r"SHA-256 `([0-9a-f]{16})")
WHERE = ("в базе", "в поиске", "в контексте", "в ответе")


def load_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def split_dev_test(rows: list[dict]) -> dict[str, str]:
    """Разбиение spec/tech/rag.md, 8.3 (как в тетрадке): внутри темы по id каждый третий — test."""
    split: dict[str, str] = {}
    by_topic: dict[str, list[dict]] = {}
    for row in rows:
        by_topic.setdefault(row["topic"], []).append(row)
    for topic_rows in by_topic.values():
        for position, row in enumerate(sorted(topic_rows, key=lambda r: r["id"])):
            split[row["id"]] = "test" if position % 3 == 2 else "dev"
    return split


def sha16(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def run(pipeline: SearchPipeline) -> list[dict]:
    """Прогоняет вопросы и ловушки через конвейер; возвращает строки answers.jsonl."""
    queries, traps = load_jsonl(QUERIES), load_jsonl(TRAPS)
    split = split_dev_test(queries)
    settings = pipeline.llm.settings
    items = [("query", row) for row in queries] + [("trap", row) for row in traps]
    rows = []
    for number, (kind, item) in enumerate(items, start=1):
        started = time.perf_counter()
        outcome = pipeline.run(SearchRequest(query=item["query"], top_k=10))
        relevant = set(item.get("relevant", []))
        verdicts = dict(zip(outcome.context_ids, [None] * len(outcome.context_ids)))
        for paragraph, verdict in zip(outcome.response.answer.split("\n\n")[1:-1], outcome.verdicts):
            lead = re.match(r"\[([^\[\]\s]+)\] ", paragraph)
            if lead:
                verdicts[lead.group(1)] = verdict
        analogs = [doc_id for doc_id, verdict in verdicts.items() if verdict is True]
        row = {
            "id": item["id"],
            "kind": kind,
            "split": split.get(item["id"]) if kind == "query" else None,
            "topic": item.get("topic"),
            "query": item["query"],
            "expected": item["expected"],
            "relevant": sorted(relevant) if kind == "query" else [],
            "results": [{"id": r.id, "score": r.score} for r in outcome.response.results],
            "context_ids": list(outcome.context_ids),
            "status": outcome.status,
            "verdicts": verdicts,
            "answer": outcome.response.answer,
            "llm_reply": outcome.llm_reply,
            "llm_seconds": outcome.llm_seconds,
            "prompt_tokens": outcome.prompt_tokens,
            "completion_tokens": outcome.completion_tokens,
            "removed_ids": list(outcome.removed_ids),
            "error": outcome.error,
            "model": settings.model if settings.provider != "stub" else "stub",
            "temperature": settings.temperature,
            "auto": {
                "relevant_in_context": [d for d in outcome.context_ids if d in relevant],
                "analogs": analogs,
                "relevant_analogs": [d for d in analogs if d in relevant],
                "refusal": outcome.status in REFUSAL_STATUSES,
            },
        }
        rows.append(row)
        print(
            f"[{number:2}/{len(items)}] {item['id']} {outcome.status:17} {time.perf_counter() - started:5.1f} с  "
            f"аналоги {len(analogs)}, из них релевантных {len(row['auto']['relevant_analogs'])}; "
            f"релевантных в промпте {len(row['auto']['relevant_in_context'])}",
            flush=True,
        )
    return rows


def read_review(answers_sha: str) -> dict[str, tuple[bool, str]] | None:
    """Разметка из answers_review.md: id → (верно, где потеряли); None — нет файла или он для другого прогона."""
    if not REVIEW.is_file():
        print(f"\nРазметки {REVIEW.relative_to(ROOT)} нет: Accuracy не посчитана (нужна ручная разметка, rag.md 9.1).")
        return None
    text = REVIEW.read_text(encoding="utf-8")
    sha = REVIEW_SHA.search(text)
    if sha is None or sha.group(1) != answers_sha:
        print(
            f"\nРазметка {REVIEW.relative_to(ROOT)} сделана для другого прогона "
            f"(в ней SHA-256 {sha.group(1) if sha else 'не указан'}, у answers.jsonl — {answers_sha}): "
            "Accuracy по ней не считается, разметьте новый прогон."
        )
        return None
    review = {}
    for line in text.splitlines():
        match = REVIEW_ROW.match(line)
        if match:
            review[match.group(1)] = (match.group(3) == "верно", match.group(4).strip())
    return review


def report(rows: list[dict], answers_sha: str) -> None:
    """Печатает сводку прогона, CRR и (при разметке этого прогона) Accuracy и разбор ошибок."""
    queries = [r for r in rows if r["kind"] == "query"]
    traps = [r for r in rows if r["kind"] == "trap"]
    seconds = [r["llm_seconds"] for r in rows if r["llm_seconds"] is not None]
    model = {r["model"] for r in rows}
    print(f"\nПрогон: {len(queries)} вопросов, {len(traps)} ловушек; модель {', '.join(sorted(model))}; "
          f"answers.jsonl SHA-256 {answers_sha}")
    print("Статусы пояснения:", dict(Counter(r["status"] for r in rows)))
    if seconds:
        print(f"Время ответа модели, с: мин {min(seconds):.1f}, медиана {statistics.median(seconds):.1f}, "
              f"макс {max(seconds):.1f}")
    tokens = [r["prompt_tokens"] for r in rows if r["prompt_tokens"]]
    if tokens:
        print(f"Промпт, токенов: мин {min(tokens)}, медиана {statistics.median(tokens):.0f}, макс {max(tokens)}")

    refused = [r["id"] for r in traps if r["auto"]["refusal"]]
    print(f"\nCorrect Rejection Rate (ловушки): {len(refused)}/{len(traps)} = {len(refused) / len(traps):.2f}"
          f"  (отказ: {', '.join(refused) or 'нет'})")
    for name in ("dev", "test"):
        part = [r for r in queries if r["split"] == name]
        named = sum(bool(r["auto"]["relevant_analogs"]) for r in part)
        print(f"Автоматическая предразметка, {name}: модель назвала аналогом хотя бы один релевантный патент "
              f"в {named} из {len(part)} вопросов (это не Accuracy: факты и эталон проверяет человек)")

    review = read_review(answers_sha)
    if review is None:
        return
    missing = [r["id"] for r in rows if r["id"] not in review]
    if missing:
        print(f"\nВ разметке нет вопросов: {', '.join(missing)} — Accuracy не посчитана.")
        return
    print("\nПо разметке answers_review.md:")
    for name in ("dev", "test"):
        part = [r for r in queries if r["split"] == name]
        correct = sum(review[r["id"]][0] for r in part)
        print(f"  Accuracy, {name}: {correct}/{len(part)} = {correct / len(part):.2f}")
    correct_all = sum(review[r["id"]][0] for r in queries)
    print(f"  Accuracy, все вопросы: {correct_all}/{len(queries)} = {correct_all / len(queries):.2f}")
    crr_review = sum(review[r["id"]][0] for r in traps)
    print(f"  Correct Rejection Rate по разметке: {crr_review}/{len(traps)} = {crr_review / len(traps):.2f}")
    where = Counter(review[r["id"]][1] for r in rows if not review[r["id"]][0])
    print("  Где потеряли правильный ответ:", ", ".join(f"{w} — {where.get(w, 0)}" for w in WHERE))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--score", action="store_true", help="не вызывать модель: метрики по сохранённому answers.jsonl")
    args = parser.parse_args()

    if not args.score:
        load_dotenv(ROOT / ".env")
        llm = LLMClient.from_env()
        if llm.settings.provider == "stub":
            sys.exit("LLM_PROVIDER=stub: модель не вызывается, ответы не оценить. Задайте ollama (README, «Запуск»).")
        if not llm.is_available():
            sys.exit(f"Сервер LLM не отвечает: {llm.settings.base_url}. Запустите Ollama (README, «Запуск»).")
        print(f"Модель {llm.settings.model}, температура {llm.settings.temperature}; "
              f"{len(load_jsonl(QUERIES))} вопросов и {len(load_jsonl(TRAPS))} ловушек\n", flush=True)
        rows = run(SearchPipeline.from_corpus(llm=llm))
        RESULTS_DIR.mkdir(exist_ok=True)
        ANSWERS.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
        print(f"\nЗаписано: {ANSWERS.relative_to(ROOT)}")
    elif not ANSWERS.is_file():
        sys.exit(f"Нет {ANSWERS.relative_to(ROOT)}: сначала прогон без --score.")
    report(load_jsonl(ANSWERS), sha16(ANSWERS))


if __name__ == "__main__":
    main()
