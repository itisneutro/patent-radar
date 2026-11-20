# Патентный радар

Инструмент первичного поиска аналогов изобретения: пользователь описывает идею обычными словами, система находит похожие патенты РФ в корпусе рефератов (собственная реализация BM25), а локальная LLM через Ollama кратко объясняет сходства и отличия со ссылками на номера патентов; результат не является юридическим заключением.

## Статус: Контрольная точка 2

Работает:

- **корпус** — 200 рефератов патентов РФ на изобретения, 8 тем по 25 (`data/corpus/patents.jsonl`); собран скриптом через API поисковой платформы Роспатента и автоматически сверен с двумя ответами API (`data/sample/README.md`);
- **поиск** — собственные предобработка (лемматизация pymorphy3, стоп-слова), инвертированный индекс и BM25 (`app/search/`); конфигурация выбрана экспериментами на benchmark (`spec/tech/rag.md`, раздел 13);
- **RAG-конвейер** `POST /search`: запрос → BM25 → порог `MIN_SCORE` и фильтры → рефераты первых 5 результатов → локальная LLM `qwen2.5:7b` через Ollama. Модель отвечает только по найденным рефератам: у каждого патента вердикт «Аналог.» или «Не аналог.»; если аналогов нет — «Аналогов в корпусе не найдено…»; если модель недоступна — выдача без пояснения (`spec/tech/architecture.md`);
- **benchmark** — 24 вопроса своими словами с разметкой релевантности и эталонными ответами, 5 вопросов-ловушек, 10 посторонних запросов для порога; прогон поиска (`benchmark/experiments.py`) и прогон ответов (`benchmark/evaluate_answers.py`);
- **интерфейс** (`frontend/`) — в режиме `api` на реальном корпусе, в режиме `mock` — на демонстрационных данных.

Темы корпуса (подкласс МПК — группы патентов):

| МПК | Тема |
|---|---|
| A01G | растения: автополив по датчикам, гидропоника, искусственное освещение |
| B62K | велосипеды: складные, трёхколёсные, самобалансирующиеся |
| C02F | очистка воды: ультрафиолет, опреснение, сточные воды |
| D06F | бельё: утюги с паром, сушильные машины, дозирование моющего средства |
| E06B | окна и двери: стеклопакеты, жалюзи и рольставни, противопожарные двери |
| F25D | холодильники: оттаивание и иней, быстрая заморозка, естественный холод |
| G01N | анализ: качество молока и воды, датчики горючих и опасных газов |
| H02J | электропитание: беспроводная зарядка, солнечные батареи, резервное питание |

Метрики КТ2 (`spec/tech/rag.md`, раздел 13; test — 8 вопросов и 5 ловушек, которые не участвовали в подборе):

| Метрика | dev | test |
|---|---|---|
| Recall@5 | 0.320 | 0.449 |
| Recall@10 | 0.547 | 0.683 |
| MRR | 0.752 | 0.768 |
| Accuracy (ответ полностью правильный) | 0.25 (4/16) | 0.00 (0/8) |
| Correct Rejection Rate (отказ на ловушках) | — | 0.80 (4/5) |

Accuracy — по предварительной разметке ответов ИИ-агентом, её проверяет команда (`benchmark/results/answers_review.md`). Разбор ошибок: из 21 неверного ответа 2 потеряны в поиске (в первых 5 нет релевантных), 19 — в ответе модели (утверждения не из реферата, противоречивый вердикт, лишний или пропущенный аналог), в базе и в контексте — 0 (`spec/tech/rag.md`, раздел 13.9).

Ограничения: корпус маленький (200 рефератов), BM25 не видит синонимов, локальная модель часто добавляет детали, которых нет в реферате, — поэтому ответ — первичный поиск, а реферат каждого патента открывается в карточке.

## Команда

| Участник | Роль | Зона ответственности |
|---|---|---|
| Абидов Бобур Ровшанович | BM25 и RAG | `data/`, `app/search/`, `benchmark/`, `spec/tech/rag.md`, `app/llm/prompts.py` |
| Васильев Николай Денисович | Интеграция (бэкенд) | `app/api/`, `app/llm/client.py`, `tests/`, `spec/tech/architecture.md`, общие файлы в корне (`README.md`, `AGENTS.md`, `CLAUDE.md`, `CHANGE_HISTORY.md`, `.gitignore`, `requirements.txt`, `.env.example`, `pytest.ini`), `app/__init__.py`, `app/llm/__init__.py` |
| Лазарева Вероника Игоревна | Продукт и интерфейс | `spec/product/`, `frontend/` |

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
├── Modelfile               # модель Ollama проекта patent-radar:7b: qwen2.5:7b с окном 8192
├── requirements.txt        # зависимости Python
├── pytest.ini              # настройки pytest
├── app/                    # бэкенд на Python
│   ├── __init__.py         # версия приложения
│   ├── api/                # FastAPI: main.py, schemas.py (контракт), pipeline.py (конвейер /search), answer.py (проверка ответа LLM)
│   ├── llm/
│   │   ├── __init__.py
│   │   ├── client.py       # клиент LLM: Ollama или другой OpenAI-совместимый сервер
│   │   └── prompts.py      # промпт для пояснений LLM и разбор вердикта
│   └── search/             # preprocess.py, index.py, bm25.py, engine.py, config.py (выбранная конфигурация)
├── benchmark/              # queries.jsonl, traps.jsonl, offtopic.jsonl, pooling.jsonl; experiments.py (тетрадка marimo), evaluate_answers.py
│   └── results/            # answers.jsonl (прогон ответов), answers_review.md (разметка ответов)
├── data/
│   ├── corpus/             # patents.jsonl (200 рефератов), groups.json (темы и группы)
│   ├── sample/             # README.md (формат записи и сбор корпуса), patents.jsonl (3 демо-записи)
│   └── tools/              # collect_corpus.py — сбор и сверка корпуса через API Роспатента
├── frontend/               # интерфейс: Vite + React + TypeScript + Tailwind
├── spec/
│   ├── product/            # product.md (продукт), scenarios.md (сценарии)
│   └── tech/               # rag.md (поиск и эксперименты), architecture.md (архитектура и API)
└── tests/                  # test_api.py, test_llm_client.py, test_search.py (pytest, без сети и Ollama)
```

## Документация

- [spec/product/product.md](spec/product/product.md) — пользователи, проблема, ценность и границы продукта.
- [spec/product/scenarios.md](spec/product/scenarios.md) — пользовательские сценарии и их проверка на реальном корпусе.
- [spec/tech/rag.md](spec/tech/rag.md) — документ корпуса, предобработка, BM25, эксперименты, benchmark и результаты КТ2.
- [spec/tech/architecture.md](spec/tech/architecture.md) — пайплайн, контракт API, выбор модели и окна контекста, переключатель провайдера LLM.
- [data/sample/README.md](data/sample/README.md) — формат записи патента, сбор корпуса через API Роспатента и сверка.
- [AGENTS.md](AGENTS.md) — правила работы для участников и ИИ-агентов.
- [CHANGE_HISTORY.md](CHANGE_HISTORY.md) — история изменений.

<!-- run:start -->
## Запуск

Команды выполняются из корня репозитория, если не сказано другое.

### Требования

- Python 3.11 или новее: `python3 --version` (в Windows — `py --version`).
- Node.js 20.19+ или 22.12+ для фронтенда: `node --version`.
- Ollama — для пояснений языковой модели: https://ollama.com/download. Без неё поиск работает, а пояснения нет (см. «Если что-то не работает»).
- Около 5 ГБ на диске и 8 ГБ оперативной памяти для модели `qwen2.5:7b`.
- Git.

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
```

Если `.venv` уже было создано старой версией Python, пересоздайте его: `python3.12 -m venv --clear .venv`.

Windows (PowerShell):

```powershell
py -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
```

Если PowerShell не даёт выполнить `Activate.ps1`, один раз выполните `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` или работайте в `cmd`: `.venv\Scripts\activate.bat`, затем `copy .env.example .env`. В каждом новом терминале окружение активируют заново: `source .venv/bin/activate` (Windows: `.venv\Scripts\Activate.ps1`).

### Языковая модель

Установите и запустите Ollama (приложение или `ollama serve`), затем один раз скачайте модель и создайте модель проекта:

```bash
ollama pull qwen2.5:7b
ollama create patent-radar:7b -f Modelfile
```

`patent-radar:7b` — та же `qwen2.5:7b` с окном контекста 8192 токена; места на диске сверх `qwen2.5:7b` она не занимает. Окно задано в `Modelfile`, потому что в окне Ollama по умолчанию (4096) длинный промпт поиска молча обрезается (`spec/tech/architecture.md`, раздел 6.2). В `.env` из `.env.example` уже стоят `LLM_PROVIDER=ollama` и `LLM_MODEL=patent-radar:7b`. Проверка, что модель есть: `ollama list`.

Для слабого ноутбука — `qwen2.5:3b`: `ollama pull qwen2.5:3b`, затем скопируйте `Modelfile`, замените в копии строку `FROM qwen2.5:7b` на `FROM qwen2.5:3b`, создайте модель `ollama create patent-radar:3b -f <копия>` и укажите `LLM_MODEL=patent-radar:3b` в `.env`. Пояснения у неё хуже (раздел 6.1 там же). Без модели вообще: `LLM_PROVIDER=stub` — поиск работает, вместо пояснения — текст заглушки.

### Запуск API

```bash
uvicorn app.api.main:app --reload
```

При старте API строит индекс по 200 рефератам (доли секунды). Сервер слушает http://127.0.0.1:8000 и с `--reload` перезапускается при изменении кода; остановка — Ctrl+C.

### Проверка

- http://127.0.0.1:8000/health — ответ `{"status":"ok","version":"0.2.0","mode":"bm25"}`.
- http://127.0.0.1:8000/docs — Swagger: `POST /search` → Try it out → в списке Examples выбрать пример («Автополив по влажности почвы», «Складной велосипед», «Фильтр по МПК A01G», «Фильтр МПК B65D — в корпусе таких нет: пустая выдача», «Слишком короткий запрос: ответ 422» и др.) → Execute.
- Запрос из терминала (macOS, Linux):

```bash
curl -s -X POST http://127.0.0.1:8000/search \
  -H "Content-Type: application/json" \
  -d '{"query": "Хочу, чтобы грядки на даче поливались сами: датчик в земле замечает, что почва пересохла, и включает воду, а если обещают дождь, полив не включается.", "top_k": 10}'
```

Ответ приходит через 9–26 секунд: столько языковая модель пишет пояснение (на Apple M5; на компьютере слабее — дольше). В ответе 10 патентов вида `RU<номер><код вида>` по убыванию `score` и `answer`: вводный абзац, по абзацу о каждом из первых 5 патентов (`[ID] Аналог. …` или `[ID] Не аналог. …`) и дисклеймер. Запрос `{"query": "Умный полив"}` вернёт 422: в нём меньше трёх слов. В Windows кириллица в командной строке может уйти на сервер в другой кодировке, поэтому там удобнее проверять через Swagger.

### Тесты

```bash
pytest
```

Тестам не нужны сеть, Ollama и запущенный сервер: API вызывается внутри процесса (TestClient), ответ модели подменяет `httpx.MockTransport`, поиск — настоящий BM25 на демо-корпусе и на корпусе `data/corpus/patents.jsonl`. Сверки с файлами фронтенда и корпуса пропускаются (skipped), если этих файлов нет.

### Фронтенд

Вместе с бэкендом (режим `api`, реальный корпус): в одном терминале запустите `uvicorn app.api.main:app --reload` (из корня репозитория), в другом:

```bash
cd frontend
npm install
npm run dev:api
```

Откройте http://localhost:5173. Интерфейс отправляет запросы на `/api/search`, а dev-сервер Vite передаёт `/api/*` бэкенду на http://127.0.0.1:8000 (префикс `/api` срезается). Если бэкенд не запущен, интерфейс показывает «Сервис недоступен».

Без бэкенда — `npm run dev` в папке `frontend/`: интерфейс работает на демонстрационных данных `frontend/src/mock/search.json` (режим `mock`).

### Как повторить проверку

Метрики поиска — тетрадка benchmark (Ollama не нужна, несколько секунд):

```bash
python benchmark/experiments.py
```

Скрипт печатает сводку: проверку корпуса и benchmark, блоки экспериментов A, B и C на dev, итог на test, порог `MIN_SCORE` и сверку с выбранной конфигурацией в `app/search/config.py`. Та же тетрадка интерактивно, в браузере: `marimo edit benchmark/experiments.py`. Цифры — в `spec/tech/rag.md`, разделы 13.1–13.7.

Метрики ответов — прогон 24 вопросов и 5 ловушек через тот же конвейер, что `POST /search` (нужна Ollama с моделью `patent-radar:7b`, около 10 минут):

```bash
python benchmark/evaluate_answers.py
```

Прогон записывает выдачу и ответ по каждому вопросу в `benchmark/results/answers.jsonl` и печатает Correct Rejection Rate — он считается автоматически. Accuracy считается по ручной разметке `benchmark/results/answers_review.md`; разметка привязана к своему прогону по SHA-256 файла `answers.jsonl`. Ответы модели меняются от прогона к прогону (температура 0.2), поэтому после нового прогона разметку делают заново, а метрики по сохранённому прогону и его разметке печатает команда без вызова модели:

```bash
python benchmark/evaluate_answers.py --score
```

Цифры и разбор ошибок — `spec/tech/rag.md`, раздел 13.9; сравнение моделей — `spec/tech/architecture.md`, раздел 6.1.

### Если что-то не работает

- После обновления с КТ1 в `.env` остались старые значения `LLM_MODEL=qwen2.5:7b` и `LLM_TIMEOUT_SECONDS=60` — они важнее значений по умолчанию. Скопируйте образец заново: `cp .env.example .env` (Windows: `Copy-Item .env.example .env`) или поправьте эти две строки.
- В «Сводке» и в `answer` — «Пояснение недоступно: языковая модель не ответила.» — Ollama не запущена или модель не создана. Проверьте `ollama list` (нужна `patent-radar:7b`) и `curl http://localhost:11434/v1/models`; причина — в журнале uvicorn (строка «Пояснение недоступно: …»).
- В журнале uvicorn — «сервер LLM обрезал промпт» — в `.env` указана модель без окна 8192 (например, `qwen2.5:7b`): создайте `patent-radar:7b` из `Modelfile` (раздел «Языковая модель»).
- Пояснение не успевает за 120 с на медленном компьютере — увеличьте `LLM_TIMEOUT_SECONDS` в `.env` или возьмите `qwen2.5:3b`.
- `ModuleNotFoundError: No module named 'app'` — uvicorn или pytest запущены не из корня репозитория.
- `command not found: uvicorn` или `pytest` — не активировано окружение `.venv`.
- `ERROR: Could not find a version that satisfies the requirement …` при `pip install` — окружение создано Python версии ниже 3.11: пересоздайте его (см. «Бэкенд»).
- `Address already in use` — порт 8000 занят другим процессом (например, вторым uvicorn). Остановите его: фронтенд в режиме `api` обращается именно к порту 8000.
<!-- run:end -->
