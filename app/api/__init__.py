"""HTTP API «Патентного радара» на FastAPI.

Модули:
    main     — приложение FastAPI и эндпоинты GET /health, POST /search;
    schemas  — Pydantic-модели запроса и ответа (контракт API);
    pipeline — конвейер POST /search: BM25 по корпусу, фильтры, порог, вызов LLM;
    answer   — проверка ответа LLM и сборка поля answer.

Контракт API: spec/tech/architecture.md, раздел «Контракт API».
"""
