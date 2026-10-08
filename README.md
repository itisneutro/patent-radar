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

На КТ1 бэкенд отвечает заглушкой на демонстрационных данных: поиск BM25 и языковая модель пока не работают. Команды выполняются из корня репозитория, если не сказано другое.

### Требования

- Python 3.11 или новее: `python3 --version` (в Windows — `py --version`).
- Node.js 20.19+ или 22.12+ для фронтенда: `node --version`.
- Git.
- Ollama на КТ1 не нужна: `/search` языковую модель не вызывает.

### Клонирование

```bash
git clone https://github.com/itisneutro/patent-radar.git
cd patent-radar
```

### Бэкенд

Сначала проверьте версию: `python3 --version`. Если она ниже 3.11 (системный `python3` в macOS — 3.9, в Ubuntu 22.04 — 3.10), установите Python 3.12: в macOS — с https://www.python.org или командой `brew install python@3.12`, в Ubuntu 22.04 — `sudo add-apt-repository ppa:deadsnakes/ppa`, затем `sudo apt install python3.12 python3.12-venv`. Тогда в первой команде ниже пишите `python3.12` вместо `python3`. В Debian и Ubuntu для `venv` нужен пакет `python3-venv` (для Python 3.12 — `python3.12-venv`).

macOS и Linux:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.api.main:app --reload
```

Если `.venv` уже было создано старой версией Python, пересоздайте его: `python3.12 -m venv --clear .venv`.

Windows (PowerShell):

```powershell
py -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
uvicorn app.api.main:app --reload
```

Если PowerShell не даёт выполнить `Activate.ps1`, один раз выполните `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` или работайте в `cmd`: `.venv\Scripts\activate.bat`, затем `copy .env.example .env`.

Сервер слушает http://127.0.0.1:8000 и с `--reload` перезапускается при изменении кода; остановка — Ctrl+C. В каждом новом терминале окружение активируют заново: `source .venv/bin/activate` (Windows: `.venv\Scripts\Activate.ps1`).

### Проверка

- http://127.0.0.1:8000/health — ответ `{"status":"ok","version":"0.1.0","mode":"stub"}`.
- http://127.0.0.1:8000/docs — Swagger: `POST /search` → Try it out → в списке Examples выбрать пример («Основной демо-запрос: 3 результата», «Фильтр по МПК G01N: DEMO-001, DEMO-003», «Ничего не найдено: пустая выдача», «Слишком короткий запрос: ответ 422» и др.) → Execute.
- Запрос из терминала (macOS, Linux):

```bash
curl -s -X POST http://127.0.0.1:8000/search \
  -H "Content-Type: application/json" \
  -d '{"query": "Хочу, чтобы грядки на даче поливались сами: датчик в земле замечает, что почва пересохла, и включает воду, а если обещают дождь, полив не включается.", "top_k": 10}'
```

В ответе три демо-патента в порядке DEMO-002, DEMO-001, DEMO-003 и `answer`, который начинается со слов «Демонстрационные данные». Запрос `{"query": "Умный полив"}` вернёт 422: в нём меньше трёх слов. В Windows кириллица в командной строке может уйти на сервер в другой кодировке, поэтому там удобнее проверять через Swagger.

### Тесты

```bash
pytest
```

Тестам не нужны сеть, Ollama и запущенный сервер: API вызывается внутри процесса (TestClient), клиент LLM проверяется на `httpx.MockTransport`. Сверки с `frontend/src/mock/search.json` и `data/sample/patents.jsonl` пропускаются (skipped), если этих файлов нет.

### Фронтенд

```bash
cd frontend
npm install
npm run dev
```

Откройте http://localhost:5173. В этом режиме интерфейс работает на моке `frontend/src/mock/search.json`, бэкенд не нужен.

Вместе с бэкендом: в одном терминале запустите `uvicorn app.api.main:app --reload` (из корня репозитория), в другом:

```bash
cd frontend
npm run dev:api
```

Интерфейс отправляет запросы на `/api/search`, а dev-сервер Vite передаёт `/api/*` бэкенду на http://127.0.0.1:8000 (префикс `/api` срезается). Если бэкенд не запущен, интерфейс показывает «Сервис недоступен».

### Тетрадка benchmark

```bash
python benchmark/experiments.py
marimo edit benchmark/experiments.py
```

Первая команда выполняет тетрадку как обычный скрипт и печатает сводку, вторая открывает её в браузере (остановка — Ctrl+C). На КТ1 в тетрадке проверка формата benchmark и план экспериментов; метрики Recall@5, Recall@10 и MRR появятся на КТ2 вместе с BM25 и benchmark.

### LLM (понадобится на КТ2)

1. Установите Ollama: https://ollama.com/download.
2. Скачайте модель: `ollama pull qwen2.5:7b` (около 4,7 ГБ). Для слабого ноутбука — `ollama pull qwen2.5:3b` и `LLM_MODEL=qwen2.5:3b` в `.env`.
3. В `.env` оставьте `LLM_PROVIDER=ollama`. Проверка, что Ollama отвечает: `curl http://localhost:11434/v1/models`.
4. Без модели: `LLM_PROVIDER=stub`. Другие локальные серверы (LM Studio, llama.cpp server) подключаются через `LLM_PROVIDER=openai_compatible`; переменные описаны в `.env.example` и `spec/tech/architecture.md`.

### Если что-то не работает

- `ModuleNotFoundError: No module named 'app'` — uvicorn или pytest запущены не из корня репозитория.
- `command not found: uvicorn` или `pytest` — не активировано окружение `.venv`.
- `ERROR: Could not find a version that satisfies the requirement …` при `pip install` — окружение создано Python версии ниже 3.11: пересоздайте его (см. «Бэкенд»).
- `Address already in use` — порт 8000 занят другим процессом (например, вторым uvicorn). Остановите его: фронтенд в режиме `api` обращается именно к порту 8000.
<!-- run:end -->
