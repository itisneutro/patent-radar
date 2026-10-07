# Патентный радар

Инструмент первичного поиска аналогов изобретения: пользователь описывает идею обычными словами, система находит похожие патенты РФ в корпусе рефератов (собственная реализация BM25), а локальная LLM через Ollama кратко объясняет сходства и отличия со ссылками на номера патентов; результат не является юридическим заключением.

## Статус: Контрольная точка 1

Готово:

- спецификации: продукт и сценарии (`spec/product/`), поиск и план экспериментов (`spec/tech/rag.md`), архитектура и контракт API (`spec/tech/architecture.md`);
- кликабельный прототип интерфейса на заглушках (`frontend/`): экран запроса, выдача, карточка патента, состояние «Ничего не найдено»; данные — мок `frontend/src/mock/search.json`, составленный по контракту API;
- заготовки модулей поиска (`app/search/`: только докстринги и `NotImplementedError`), черновик промпта LLM (`app/llm/prompts.py`), формат benchmark и план экспериментов (`benchmark/`);
- заготовка API (`app/api/`): `GET /health` и `POST /search` с ответом-заглушкой по контракту; заготовка клиента LLM (`app/llm/client.py`); тесты (`tests/`).

Ещё не работает:

- поиск: BM25 не реализован, `POST /search` возвращает заранее подготовленную выдачу — записи `DEMO-001`, `DEMO-002`, `DEMO-003` (демонстрационные данные, не реальные патенты) или пустой список;
- LLM: не вызывается, пояснение в ответе составлено заранее.

План к КТ2: корпус рефератов в `data/corpus/`, собственный BM25, benchmark с метриками Recall@5, Recall@10 и MRR, пояснения локальной LLM через Ollama.

## Команда

| Участник | Роль | Зона ответственности |
|---|---|---|
| Бобур | BM25 и RAG | `data/`, `app/search/`, `benchmark/`, `spec/tech/rag.md`, `app/llm/prompts.py` |
| Коля | Интеграция (бэкенд) | `app/api/`, `app/llm/client.py`, `tests/`, `spec/tech/architecture.md`, общие файлы в корне (`README.md`, `AGENTS.md`, `CLAUDE.md`, `CHANGE_HISTORY.md`, `.gitignore`, `requirements.txt`, `.env.example`, `pytest.ini`), `app/__init__.py`, `app/llm/__init__.py` |
| Ника | Продукт и интерфейс | `spec/product/`, `frontend/` |

Изменения в чужой зоне — только по согласованию с владельцем (см. [AGENTS.md](AGENTS.md)).

## Структура репозитория

Стек: Python 3.11+ и FastAPI; React, Vite, TypeScript и Tailwind; LLM через Ollama (OpenAI-совместимый API); тетрадки marimo.

```text
patent-radar/
├── README.md               # описание проекта (этот файл)
├── AGENTS.md               # правила для участников и ИИ-агентов
├── CLAUDE.md               # одна строка @AGENTS.md: правила для Claude Code
├── CHANGE_HISTORY.md       # история изменений
├── .gitignore              # что не попадает в git
├── .env.example            # образец .env с настройками LLM (сам .env в git не попадает)
├── requirements.txt        # зависимости Python
├── pytest.ini              # настройки pytest
├── app/                    # бэкенд на Python
│   ├── __init__.py         # версия приложения
│   ├── api/                # FastAPI: main.py, schemas.py (контракт API), stub.py (заглушка КТ1)
│   ├── llm/
│   │   ├── __init__.py
│   │   ├── client.py       # клиент LLM: Ollama или другой OpenAI-совместимый сервер
│   │   └── prompts.py      # промпт для пояснений LLM
│   └── search/             # preprocess.py, index.py, bm25.py (на КТ1 — заготовки)
├── benchmark/              # queries.example.jsonl (формат запросов), experiments.py (тетрадка marimo)
├── data/
│   ├── corpus/             # корпус рефератов patents.jsonl (появится к КТ2)
│   └── sample/             # README.md (формат записи), patents.jsonl (3 демо-записи)
├── frontend/               # прототип интерфейса: Vite + React + TypeScript + Tailwind
├── spec/
│   ├── product/            # product.md (продукт), scenarios.md (сценарии)
│   └── tech/               # rag.md (поиск и эксперименты), architecture.md (архитектура и API)
└── tests/                  # test_api.py, test_llm_client.py (pytest, без сети и Ollama)
```

## Документация

- [spec/product/product.md](spec/product/product.md) — пользователи, проблема, ценность и границы продукта.
- [spec/product/scenarios.md](spec/product/scenarios.md) — основной и альтернативные пользовательские сценарии.
- [spec/tech/rag.md](spec/tech/rag.md) — документ корпуса, предобработка, BM25, план экспериментов и benchmark.
- [spec/tech/architecture.md](spec/tech/architecture.md) — пайплайн, контракт API, выбор LLM и переключатель провайдера.
- [data/sample/README.md](data/sample/README.md) — формат записи патента и сбор рефератов из открытых реестров ФИПС.
- [AGENTS.md](AGENTS.md) — правила работы для участников и ИИ-агентов.
- [CHANGE_HISTORY.md](CHANGE_HISTORY.md) — история изменений.

<!-- run:start -->
## Запуск

Инструкция по запуску появится на шаге `02_code` (Коля): бэкенд, тесты, фронтенд-прототип и тетрадка benchmark.
<!-- run:end -->
