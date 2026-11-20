"""Поле answer: проверка ответа языковой модели и сборка текста по контракту (КТ2).

Формат answer — spec/tech/architecture.md, раздел 4.5: простой текст, абзацы через
пустую строку; вводный абзац без ссылок; абзацы «[ID] …» о патентах в порядке выдачи;
последний абзац — дисклеймер. Вводный абзац и дисклеймер — фиксированные тексты
отсюда, их пишет API, а не модель. Проверка ответа модели — раздел 8:

1. Абзац начинается с «[ID]» (перед ним могут стоять маркер списка или выделение
   Markdown — они убираются). Строка, которая начинается с «[ID]», открывает новый
   абзац, даже если пустой строки перед ней нет.
2. Абзац о патенте, которого не было в промпте, удаляется целиком. Чужие ссылки
   внутри оставшихся абзацев убираются. Повторный абзац о том же патенте удаляется.
3. Текст без «[ID]» в начале: до первого абзаца о патенте — отбрасывается (вводный
   абзац пишет API), после — присоединяется к предыдущему абзацу о патенте (модель
   иногда переносит пояснение на новую строку после вердикта).
4. Абзацы о патентах выстраиваются в порядке выдачи.
5. Если у всех абзацев вердикт «Не аналог.» (app/llm/prompts.py), вводный абзац
   сообщает, что аналогов в корпусе не найдено. Если не осталось ни одного абзаца
   о патентах — ответ считается непригодным, как при недоступной модели.
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final

from app.llm.prompts import verdict

#: Последний абзац любого непустого answer; его добавляет API, а не LLM.
ANSWER_DISCLAIMER: Final = (
    "Это первичный поиск аналогов, а не юридическое заключение о новизне или патентоспособности."
)

#: answer при пустой выдаче; LLM в этом случае не вызывается.
NO_RESULTS_ANSWER: Final = (
    "Похожих патентов в корпусе не найдено. Опишите идею иначе: назначение, из чего "
    "состоит и как работает, — или ослабьте фильтры по году и МПК."
)

#: Вводный абзац, когда модель нашла хотя бы один аналог (или не дала вердикта).
ANSWER_INTRO: Final = (
    "Языковая модель сравнила вашу идею с рефератами первых найденных патентов: ниже "
    "для каждого — аналог это или нет, что общего и чем отличается."
)

#: Вводный абзац, когда у всех патентов из промпта вердикт «Не аналог.».
NO_ANALOGS_INTRO: Final = (
    "Аналогов в корпусе не найдено: по оценке языковой модели, ни один из первых "
    "найденных патентов не совпадает с вашей идеей по назначению. Ниже — для чего "
    "они предназначены."
)

#: Первый абзац answer, когда пояснения нет: модель недоступна или ответ не прошёл проверку.
LLM_UNAVAILABLE_ANSWER: Final = (
    "Пояснение недоступно: языковая модель не ответила. Список похожих патентов ниже."
)

#: Начало вводного абзаца, если в выдаче есть демо-записи (AGENTS.md, раздел 7).
DEMO_NOTE: Final = (
    "Демонстрационные данные: записи DEMO-… придуманы для прототипа и не описывают "
    "реальные патенты."
)

#: Ссылка на патент в тексте: [ID]. То же выражение — в tests/test_api.py.
CITATION: Final = re.compile(r"\[([^\[\]\s]+)\]")

#: Начало абзаца о патенте: необязательные маркер списка и выделение, затем [ID] и знак после него.
_LEAD: Final = re.compile(r"^(?:[-*•]\s+|\d+[.)]\s+)?[*_]*\[([^\[\]\s]+)\][*_]*\s*[:.—–-]?\s*")

#: Выделение Markdown, которое модель иногда добавляет вопреки промпту.
_EMPHASIS: Final = re.compile(r"\*\*|__")

#: Пробел перед знаком препинания, который остаётся на месте убранной ссылки.
_SPACE_BEFORE_PUNCTUATION: Final = re.compile(r"\s+([.,;:!?)])")


@dataclass(frozen=True)
class CheckedAnswer:
    """Результат проверки ответа модели.

    Attributes:
        paragraphs: абзацы о патентах в порядке выдачи, каждый начинается с «[ID] ».
        verdicts: вердикт каждого абзаца: True — «Аналог.», False — «Не аналог.», None — нет.
        removed_ids: id из ответа модели, которых не было в промпте (их ссылки убраны).
    """

    paragraphs: tuple[str, ...]
    verdicts: tuple[bool | None, ...]
    removed_ids: tuple[str, ...]


def check_reply(reply: str, context_ids: Sequence[str]) -> CheckedAnswer:
    """Проверяет ответ модели по правилам из докстринга модуля.

    Args:
        reply: текст ответа модели.
        context_ids: id патентов, переданных в промпт, в порядке выдачи.

    Example:
        >>> checked = check_reply(
        ...     "Сравнение:\\n\\n**[DEMO-002]** Аналог. Полив по датчику.\\n"
        ...     "[DEMO-009] Аналог. Такого патента в промпте нет.\\n\\n"
        ...     "[DEMO-001] Не аналог.\\n\\nЭто датчик почвы [DEMO-009].",
        ...     ["DEMO-001", "DEMO-002"],
        ... )
        >>> checked.paragraphs
        ('[DEMO-001] Не аналог. Это датчик почвы.', '[DEMO-002] Аналог. Полив по датчику.')
        >>> checked.verdicts, checked.removed_ids
        ((False, True), ('DEMO-009',))
    """
    allowed = list(context_ids)
    removed: list[str] = []
    found: dict[str, list[str]] = {}
    current: list[str] | None = None
    for block in _split_blocks(reply):
        lead = _LEAD.match(block)
        if lead is None:
            if current is not None:
                current.append(block)
            continue
        patent_id = lead.group(1)
        rest = block[lead.end():]
        if patent_id not in allowed:
            removed.append(patent_id)
            current = None
        elif patent_id in found:
            current = None
        else:
            current = [rest]
            found[patent_id] = current

    paragraphs: list[str] = []
    verdicts: list[bool | None] = []
    for patent_id in sorted(found, key=allowed.index):
        text = " ".join(" ".join(found[patent_id]).split())
        foreign = [cited for cited in CITATION.findall(text) if cited not in allowed]
        if foreign:
            removed.extend(foreign)
            text = CITATION.sub(lambda m: m.group(0) if m.group(1) in allowed else "", text)
            text = _SPACE_BEFORE_PUNCTUATION.sub(r"\1", " ".join(text.split()))
        if not text:
            continue
        paragraphs.append(f"[{patent_id}] {text}")
        verdicts.append(verdict(text))
    return CheckedAnswer(tuple(paragraphs), tuple(verdicts), tuple(dict.fromkeys(removed)))


def compose(intro: str, paragraphs: Sequence[str] = (), demo: bool = False) -> str:
    """Собирает answer: вводный абзац, абзацы о патентах и дисклеймер через пустую строку.

    demo=True — в выдаче есть демо-записи: вводный абзац начинается с DEMO_NOTE.
    """
    if demo:
        intro = f"{DEMO_NOTE} {intro}"
    return "\n\n".join([intro, *paragraphs, ANSWER_DISCLAIMER])


def _split_blocks(reply: str) -> list[str]:
    """Делит ответ на блоки: по пустым строкам и перед каждой строкой, которая начинается с [ID]."""
    blocks: list[str] = []
    lines: list[str] = []
    for raw_line in reply.replace("\r\n", "\n").split("\n"):
        line = _EMPHASIS.sub("", raw_line).strip()
        line = re.sub(r"^#+\s*", "", line)
        if not line or (_LEAD.match(line) and lines):
            if lines:
                blocks.append(" ".join(lines))
            lines = [line] if line else []
            continue
        lines.append(line)
    if lines:
        blocks.append(" ".join(lines))
    return blocks
