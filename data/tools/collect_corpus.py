"""Сбор корпуса рефератов патентов РФ через API поисковой платформы Роспатента.

Результат — data/corpus/patents.jsonl в формате data/sample/README.md. Состав
корпуса задаёт data/corpus/groups.json: темы (подклассы МПК), группы близких
патентов внутри тем, поисковый запрос группы и выбранные номера.

Источник — ИС «Поисковая платформа» Роспатента, API v0.2
(https://searchplatform.rospatent.gov.ru/patsearch/v0.2/), массив
ru_since_1994: официальный программный доступ к публикациям Роспатента.
Ключ API (JWT) выдаётся зарегистрированному пользователю в разделе
«Разработчикам» веб-интерфейса платформы. Скрипт читает его только из
переменной окружения ROSPATENT_TOKEN и никуда не записывает и не выводит.

Страницы открытого реестра ФИПС скрипт не открывает: robots.txt ФИПС
запрещает роботам раздел /registers-doc-view/. Адрес страницы документа в
поле source строится по шаблону, выборочная сверка с реестром — вручную в
браузере (команда spotcheck печатает адреса и поля для сверки).

Сырые ответы API кешируются в ../kt2-raw/ (каталог рядом с репозиторием,
в git не попадает). Повторный запуск берёт ответы из кеша и в сеть не ходит;
ключ нужен, только если ответа ещё нет в кеше. Между запросами к API —
пауза не меньше 1 с.

Команды (из корня репозитория):

    python data/tools/collect_corpus.py search
    python data/tools/collect_corpus.py build
    python data/tools/collect_corpus.py spotcheck
    python data/tools/collect_corpus.py selftest

search — кандидаты по поисковым запросам групп из groups.json: выдача API,
отбор по правилам корпуса, рефераты первых кандидатов; результат — в
../kt2-raw/candidates/ для ручного отбора номеров в groups.json.
build — корпус по номерам из groups.json с проверкой правил и отчётом.
spotcheck — по 2 записи на тему: адрес страницы ФИПС и поля для сверки.
selftest — проверка функций нормализации на встроенных примерах, без сети.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import re
import statistics
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
GROUPS_PATH = REPO_ROOT / "data" / "corpus" / "groups.json"
CORPUS_PATH = REPO_ROOT / "data" / "corpus" / "patents.jsonl"
DEFAULT_RAW_DIR = REPO_ROOT.parent / "kt2-raw"

API_URL = "https://searchplatform.rospatent.gov.ru/patsearch/v0.2"
DATASET = "ru_since_1994"
KINDS = ("C1", "C2")
FIPS_URL = "https://new.fips.ru/registers-doc-view/fips_servlet?DB=RUPAT&DocNumber={number}&TypeFile=html"
MIN_PAUSE_SECONDS = 1.0
FIELDS = ("id", "title", "abstract", "ipc", "year", "source")

# --- нормализация (data/sample/README.md, «Правила нормализации») ---------------

IPC_FULLNAME_RE = re.compile(r"([A-H]\d{2}[A-Z])\s*(\d{1,4})\s*/\s*(\d{2,6})")
ID_RE = re.compile(r"RU[0-9]+C[12]")
WORD_RE = re.compile(r"[^\W_]+")

# Служебная приписка в конце реферата: «3 ил.», «2 з.п. ф-лы, 3 ил.»,
# «2 с. и 1 з.п. ф-лы. 1 ил., 2 табл.», «1 н. и 5 з.п. ф-лы», «2 пр.» и т. п.
_TAIL_ITEM = (
    r"\d+\s*(?:(?:н|с)\.?\s*(?:и|,)\s*\d+\s*)?"
    r"(?:з\.?\s*п\.?|н\.?\s*п\.?|с\.?\s*п\.?|н\.|с\.)?\s*ф\s*-?\s*л[аы]\.?"
    r"|\d+\s*(?:ил|табл|пр|фиг)\b\.?"
)
TAIL_RE = re.compile(rf"(?:\s*(?:{_TAIL_ITEM})\s*[,.;]?)+\s*$")
# остатки приписки, которые TAIL_RE не распознал, — повод посмотреть вручную
TAIL_LEFTOVER_RE = re.compile(r"(?:\bз\.\s*п\.|\bн\.\s*п\.|\bф\s*-\s*л[аы]\b|\d+\s*ил\.|\d+\s*табл\.)")

ST96_PAT = "http://www.wipo.int/standards/XMLSchema/ST96/Patent"
ST96_COM = "http://www.wipo.int/standards/XMLSchema/ST96/Common"

_BLOCK_TAG_RE = re.compile(r"</?(?:p|div|br|li|ul|ol|tr|td|th|table|h\d)\b[^>]*>", re.I)
_TAG_RE = re.compile(r"<[^>]+>")
_PNUM_RE = re.compile(r"<span\b[^>]*>\s*\[\d+\]\s*</span>", re.I)
_TRAILING_IMG_RE = re.compile(r"(?:\s*<img\b[^>]*>)+(?=(?:\s*</[^>]+>)*\s*$)", re.I)
_RICH_RE = re.compile(r"<(?:\w+:)?(?:math|table)\b|<tbl:|<mml:", re.I)


def ipc_codes(ipc_entries: list[dict]) -> tuple[list[str], list[str]]:
    """Коды МПК в виде «A01G 25/16», без версий и повторов, в порядке API; и неразобранные коды.

    Первым API отдаёт основной код — первый код (51) документа; остальные
    коды API (и исходный XML ST96) упорядочивает по возрастанию, поэтому на
    странице ФИПС дополнительные коды могут стоять в другом порядке.
    Неполный код (например, только подкласс «G01N») в запись не попадает,
    а возвращается вторым списком: такая запись в корпус не идёт.
    """
    codes: list[str] = []
    bad: list[str] = []
    for entry in ipc_entries or []:
        value = str(entry.get("fullname", "")).strip()
        m = IPC_FULLNAME_RE.fullmatch(value)
        if not m:
            bad.append(value)
            continue
        code = f"{m.group(1)} {m.group(2)}/{m.group(3)}"
        if code not in codes:
            codes.append(code)
    return codes, bad


def strip_tail(text: str) -> tuple[str, str]:
    """Убирает приписку «… з.п. ф-лы, … ил.» в конце реферата; возвращает (текст, приписка)."""
    m = TAIL_RE.search(text)
    if not m or m.start() == 0:
        return text, ""
    # запятая или точка с запятой перед припиской — разделитель приписки, а не часть текста
    return text[: m.start()].rstrip().rstrip(",;:").rstrip(), text[m.start():].strip()


def abstract_text(xml: str) -> tuple[str, str, list[str]]:
    """Текст реферата из разметки ST96: (текст, срезанная приписка, проблемы).

    Номер абзаца «[N]» и рисунок после текста реферата убираются, переносы строк
    и повторяющиеся пробелы заменяются одним пробелом. Реферат с формулой или
    рисунком внутри текста, с MathML или таблицей текстом без потерь не передать —
    такие записи помечаются проблемой и в корпус не идут.
    """
    issues: list[str] = []
    data_format = re.search(r'\bpat:dataFormat="([^"]+)"', xml or "")
    data_format = data_format.group(1) if data_format else ""
    s = _PNUM_RE.sub(" ", xml or "")
    if _RICH_RE.search(s):
        issues.append("формула MathML или таблица в реферате")
    s = _TRAILING_IMG_RE.sub("", s)
    if re.search(r"<img\b", s, re.I):
        issues.append("рисунок или формула-картинка внутри текста реферата")
    s = _BLOCK_TAG_RE.sub(" ", s)
    s = _TAG_RE.sub("", s)
    s = " ".join(html.unescape(s).split())
    s, tail = strip_tail(s)
    if not s:
        issues.append("пустой реферат")
    elif TAIL_LEFTOVER_RE.search(s[-60:]):
        issues.append("в конце реферата осталась нераспознанная приписка")
    if data_format not in ("", "original") and not tail:
        # «docdba» — копия реферата из базы DOCDB: длинные рефераты в ней обрезаны
        # на полуслове (на КТ2 найдено сверкой с ФИПС). Полный реферат кончается
        # припиской «… ил.», «… ф-лы»; без неё такой реферат в корпус не берём.
        issues.append(f"реферат {data_format} без приписки в конце — возможно обрезан")
    if s and not tail and not re.search(r"[.!?)»\"]$", s):
        issues.append("реферат обрывается без точки — возможно обрезан")
    return s, tail, issues


def st96_abstract_markup(xml: bytes) -> str | None:
    """Исходный реферат на русском из XML документа ST96 — в виде простой разметки для abstract_text.

    В ответе GET /docs поле abstract.ru бывает копией реферата из базы DOCDB
    (dataFormat="docdba"): длинный реферат в ней обрезан, подстрочные индексы
    выброшены («CO2» → «CO»). Полный исходный реферат (dataFormat="original")
    есть в XML документа, который API отдаёт по адресу из поля ex_xml.
    Абзацы com:P → <p>, com:Br → <br/>, рисунки com:Image → <img/>, MathML и
    таблицы → метки, по которым abstract_text отклонит реферат; текст
    подстрочных и надстрочных индексов сохраняется.
    """
    import xml.etree.ElementTree as ET

    root = ET.fromstring(xml)
    for element in root.iter(f"{{{ST96_PAT}}}Abstract"):
        if element.get(f"{{{ST96_COM}}}languageCode") != "ru":
            continue
        if element.get(f"{{{ST96_PAT}}}dataFormat") != "original":
            continue
        parts: list[str] = ['<div pat:dataFormat="original">']

        def walk(node, top: bool = False) -> None:
            namespace, _, tag = node.tag[1:].partition("}") if node.tag.startswith("{") else ("", "", node.tag)
            if "MathML" in namespace or tag == "math":
                parts.append("<math/>")
            elif "tables" in namespace or tag == "table":
                parts.append("<table/>")
            elif tag in ("Image", "Figure", "InlineFigure"):
                parts.append("<img/>")
            else:
                if tag == "P":
                    parts.append("<p>")
                elif tag == "Br":
                    parts.append("<br/>")
                parts.append(html.escape(node.text or ""))
                for child in node:
                    walk(child)
                if tag == "P":
                    parts.append("</p>")
            if not top:
                parts.append(html.escape(node.tail or ""))

        walk(element, top=True)
        parts.append("</div>")
        return "".join(parts)
    return None


def st96_fields(xml: bytes) -> dict:
    """Библиографические поля из XML документа ST96: номер, вид, год, название (ru), коды МПК.

    Коды МПК — элементы IPCRClassification в порядке атрибута sequenceNumber.
    Нужны команде verify как второй, независимый от GET /docs ответ API.
    """
    import xml.etree.ElementTree as ET

    ns = {"pat": ST96_PAT, "com": ST96_COM}
    root = ET.fromstring(xml)
    # идентификация документа: в старой разметке — прямо в корне, в новой — только в
    # BibliographicData/PatentPublicationIdentification (берём исходную, не docdb/epodoc)
    source = root
    if not root.findtext("pat:PublicationNumber", namespaces=ns):
        for element in root.iter(f"{{{ST96_PAT}}}PatentPublicationIdentification"):
            if element.get(f"{{{ST96_PAT}}}dataFormat") in (None, "original") and element.findtext(
                "pat:PublicationNumber", namespaces=ns
            ):
                source = element
                break
    date = source.findtext("com:PublicationDate", namespaces=ns) or root.get(f"{{{ST96_COM}}}documentPublicationDate") or ""
    titles = [
        " ".join("".join(t.itertext()).split())
        for t in root.iter(f"{{{ST96_PAT}}}InventionTitle")
        if t.get(f"{{{ST96_COM}}}languageCode") == "ru"
    ]
    titles = [t for t in titles if t]
    ranked = []
    for element in root.iter(f"{{{ST96_PAT}}}IPCRClassification"):
        text = element.findtext("pat:PatentClassificationText", namespaces=ns)
        if not text:
            # новая разметка: код разбит на элементы Section, Class, Subclass, MainGroup, Subgroup
            parts = [(element.findtext(f"pat:{tag}", namespaces=ns) or "").strip()
                     for tag in ("Section", "Class", "Subclass", "MainGroup", "Subgroup")]
            text = f"{parts[0]}{parts[1]}{parts[2]}{parts[3]}/{parts[4]}"
        m = IPC_FULLNAME_RE.search(text)
        code = f"{m.group(1)} {m.group(2)}/{m.group(3)}" if m else text.strip()
        ranked.append((int(element.get(f"{{{ST96_COM}}}sequenceNumber") or 0), code))
    codes: list[str] = []
    for _, code in sorted(ranked):
        if code not in codes:
            codes.append(code)
    return {
        "office": source.findtext("com:IPOfficeCode", namespaces=ns) or "",
        "number": (source.findtext("pat:PublicationNumber", namespaces=ns) or "").lstrip("0"),
        "kind": source.findtext("com:PatentDocumentKindCode", namespaces=ns) or "",
        "year": int(date[:4]) if date[:4].isdigit() else None,
        "title": titles[0] if titles else "",
        "ipc": codes,
    }


def sentence_case(title: str, abstract: str) -> tuple[str, list[str], list[str]]:
    """Название по правилу 5: (название, сохранённые аббревиатуры, подозрительные слова).

    Если в названии есть строчные буквы, оно уже набрано обычным образом и
    остаётся как опубликовано. Если всё набрано прописными, остаётся заглавной
    только первая буква; слово остаётся прописным (или в смешанном написании,
    как «pH»), если оно так же написано в реферате. Короткие слова из одних
    согласных и латиница, которых нет в реферате, возвращаются как подозрительные:
    возможно, это аббревиатуры, их проверяют вручную.
    """
    title = " ".join(title.split())
    # «набрано прописными» решаем по кириллическим словам: обозначения вроде «Mg2+» или
    # «АТФазы» внутри прописного названия бывают со строчными буквами
    cyrillic_words = [w for w in WORD_RE.findall(title) if re.search(r"[А-Яа-яЁё]", w)]
    caps_words = [w for w in cyrillic_words if not any(ch.islower() for ch in w)]
    if not cyrillic_words or len(caps_words) < 0.7 * len(cyrillic_words):
        return title, [], []
    forms: dict[str, str] = {}
    for word in WORD_RE.findall(abstract):
        if len(word) >= 2 and not word.islower() and not word[1:].islower():
            forms.setdefault(word.upper(), word)
    kept: list[str] = []
    suspicious: list[str] = []
    # слова в кавычках — название или марка («ДКС»): остаются как в документе
    quoted = [m.span(1) for m in re.finditer(r'["«]([^"»]+)["»]', title)]

    def replace(match: re.Match) -> str:
        word = match.group(0)
        if any(ch.islower() for ch in word):
            # слово уже набрано не прописными («Mg2», «АТФазы») — как в документе
            return word
        if any(start <= match.start() < end for start, end in quoted):
            kept.append(word)
            return word
        if word in forms:
            kept.append(forms[word])
            return forms[word]
        low = word.lower()
        if re.fullmatch(r"[бвгджзйклмнпрстфхцчшщ]{2,5}|[a-z]+\d*|\d+[a-z]+", low):
            suspicious.append(low)
        return low

    out = WORD_RE.sub(replace, title)
    for i, ch in enumerate(out):
        if ch.isalpha():
            out = out[:i] + ch.upper() + out[i + 1:]
            break
    return out, kept, suspicious


def publication_year(date: str) -> int:
    """Год из даты публикации вида «2003.11.27» или «20031127»."""
    m = re.match(r"(\d{4})", str(date))
    if not m:
        raise ValueError(f"дата публикации не разобрана: {date!r}")
    return int(m.group(1))


@dataclass
class Record:
    """Запись корпуса и сведения для проверки отбора."""

    data: dict
    first_subclass: str
    kind: str
    office: str
    tail: str = ""
    issues: list[str] = field(default_factory=list)
    kept_abbr: list[str] = field(default_factory=list)
    suspicious: list[str] = field(default_factory=list)
    raw_title: str = ""
    abstract_source: str = "docs"


def docs_abstract_format(doc: dict) -> str:
    """Значение dataFormat реферата в ответе GET /docs: «original» или «docdba»."""
    m = re.search(r'\bpat:dataFormat="([^"]+)"', (doc.get("abstract") or {}).get("ru", "") or "")
    return m.group(1) if m else ""


def to_record(doc: dict, original_abstract: str | None = None, original_title: str | None = None) -> Record:
    """Запись корпуса из ответа GET /docs/<id> (поля — как опубликованы, плюс нормализация).

    original_abstract — исходный реферат из XML документа (st96_abstract_markup);
    если он передан, поле abstract берётся из него, а не из abstract.ru ответа /docs.
    original_title — название из XML документа; если передано, берётся вместо biblio.ru.title
    (в /docs у части названий пропущены пробелы на месте переноса строки: «ВОДИ», «РАБОТЫЭТОГО»).
    """
    common = doc.get("common", {})
    office = str(common.get("publishing_office", ""))
    kind = str(common.get("kind", ""))
    number = str(common.get("document_number", "")).lstrip("0")
    ipc, bad_ipc = ipc_codes(common.get("classification", {}).get("ipc", []))
    markup = original_abstract if original_abstract is not None else (doc.get("abstract") or {}).get("ru", "")
    abstract, tail, issues = abstract_text(markup)
    if bad_ipc:
        issues.append(f"неполный код МПК в документе: {bad_ipc}")
    raw_title = original_title or str((doc.get("biblio", {}).get("ru") or {}).get("title", ""))
    title, kept, suspicious = sentence_case(raw_title, abstract)
    if not title:
        issues.append("пустое название")
    if not ipc:
        issues.append("нет кодов МПК")
    data = {
        "id": f"{office}{number}{kind}",
        "title": title,
        "abstract": abstract,
        "ipc": ipc,
        "year": publication_year(common.get("publication_date", "")),
        "source": FIPS_URL.format(number=number),
    }
    return Record(
        data=data,
        first_subclass=ipc[0][:4] if ipc else "",
        kind=kind,
        office=office,
        tail=tail,
        issues=issues,
        kept_abbr=kept,
        suspicious=suspicious,
        raw_title=raw_title,
        abstract_source="xml" if original_abstract is not None else "docs",
    )


def rule_problems(record: Record, subclass: str) -> list[str]:
    """Нарушения правил корпуса: патент РФ на изобретение, первый код (51) — из подкласса темы."""
    problems = list(record.issues)
    if record.office != "RU" or record.kind not in KINDS or not ID_RE.fullmatch(record.data["id"]):
        problems.append(f"не патент РФ на изобретение C1/C2: {record.data['id']}")
    if record.first_subclass != subclass:
        problems.append(f"первый код МПК {record.data['ipc'][:1]} не из подкласса {subclass}")
    return problems


# --- клиент API с кешем и паузой --------------------------------------------------


class ApiError(RuntimeError):
    """Ошибка обращения к API; сообщение не содержит ключа."""


class RospatentClient:
    """Запросы к API поисковой платформы: кеш сырых ответов и пауза между запросами."""

    def __init__(self, raw_dir: Path, pause: float = 1.2, offline: bool = False) -> None:
        self.raw_dir = raw_dir
        self.pause = max(pause, MIN_PAUSE_SECONDS)
        self.offline = offline
        self._last_request = 0.0
        self._http = None
        self.network_requests = 0
        self.retries = 0

    def _client(self):
        if self._http is None:
            token = os.environ.get("ROSPATENT_TOKEN", "").strip()
            if not token:
                raise ApiError(
                    "нет ответа в кеше, а переменная окружения ROSPATENT_TOKEN не задана: "
                    "ключ API выдаётся в разделе «Разработчикам» поисковой платформы Роспатента"
                )
            import httpx

            self._http = httpx.Client(
                base_url=API_URL,
                timeout=60,
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            )
        return self._http

    def _send(self, method: str, path: str, body: dict | None = None) -> str:
        if self.offline:
            raise ApiError(f"режим --offline: ответа на {method} {path} нет в кеше")
        import httpx

        client = self._client()
        backoff = (10.0, 30.0)
        for attempt in range(len(backoff) + 1):
            wait = self._last_request + self.pause - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            try:
                response = client.request(method, path, json=body)
                error = None
            except (httpx.TransportError, httpx.TimeoutException) as exc:
                response, error = None, f"{type(exc).__name__}: {exc}"
            finally:
                self._last_request = time.monotonic()
                self.network_requests += 1
            if response is not None and response.status_code not in (502, 503, 504):
                break
            if attempt == len(backoff):
                reason = error or f"HTTP {response.status_code}"
                raise ApiError(f"{method} {path}: сбой после {attempt + 1} попыток ({reason}); сбор остановлен")
            self.retries += 1
            time.sleep(backoff[attempt])
        if response.status_code == 429:
            raise ApiError(
                "API ограничило число запросов (HTTP 429, Retry-After: "
                f"{response.headers.get('Retry-After', 'не указан')}); сбор остановлен"
            )
        if response.status_code in (401, 403):
            raise ApiError(f"ключ ROSPATENT_TOKEN не принят (HTTP {response.status_code})")
        if response.status_code != 200:
            raise ApiError(f"{method} {path}: HTTP {response.status_code}: {response.text[:300]}")
        return response.text

    def search(self, body: dict) -> dict:
        """POST /search с кешем по содержимому запроса."""
        key = hashlib.sha256(json.dumps(body, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:20]
        path = self.raw_dir / "search" / f"{key}.json"
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))["response"]
        text = self._send("POST", "/search", body)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({"request": body, "response": json.loads(text)}, ensure_ascii=False), encoding="utf-8"
        )
        return json.loads(text)

    def doc(self, doc_id: str) -> dict:
        """GET /docs/<id> с кешем: сырой ответ сохраняется как есть."""
        if not re.fullmatch(r"[A-Z]{2}[0-9A-Z]+_\d{8}", doc_id):
            raise ApiError(f"неожиданный идентификатор документа: {doc_id!r}")
        path = self.raw_dir / "docs" / f"{doc_id}.json"
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
        text = self._send("GET", f"/docs/{doc_id}")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return json.loads(text)

    def xml(self, doc: dict) -> bytes | None:
        """XML документа ST96 (медиаданные документа) по адресу из поля ex_xml ответа /docs, с кешем."""
        media_path = str(doc.get("ex_xml") or "")
        doc_id = str(doc.get("id") or "")
        if not media_path.startswith("/media/") or not re.fullmatch(r"[A-Z]{2}[0-9A-Z]+_\d{8}", doc_id):
            return None
        path = self.raw_dir / "xml" / f"{doc_id}.xml"
        if path.exists():
            return path.read_bytes()
        text = self._send("GET", media_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return text.encode("utf-8")


def load_record(client: RospatentClient, doc_id: str, original_abstract: bool) -> Record:
    """Запись по идентификатору документа API; при original_abstract — реферат из исходного XML.

    Если GET /docs отдаёт реферат не в исходном виде (docdba), берётся
    исходный реферат из XML документа; если его там нет — реферат /docs
    с проверками abstract_text. Название берётся из XML документа.
    """
    doc = client.doc(doc_id)
    if not original_abstract:
        return to_record(doc)
    xml = client.xml(doc)
    if not xml:
        return to_record(doc)
    title = st96_fields(xml)["title"] or None
    markup = st96_abstract_markup(xml) if docs_abstract_format(doc) != "original" else None
    return to_record(doc, markup, title)


def search_body(group: dict, limit: int) -> dict:
    """Запрос POST /search для группы: фильтры по стране, виду и группе МПК.

    Обычно — смысловой запрос на естественном языке (поле query → qn): API
    ставит первыми самые близкие по смыслу документы группы. В маленьких
    группах смысловой запрос находит единицы документов, поэтому для них в
    groups.json задаётся поле q — запрос на языке поисковой платформы
    (например, «IC=B62K15» — все документы с кодом группы), и кандидаты
    просматриваются целиком.
    """
    body: dict = {"q": group["q"]} if group.get("q") else {"qn": group["query"]}
    body.update(
        {
            "limit": limit,
            "datasets": [DATASET],
            "filter": {
                "country": {"values": ["RU"]},
                "kind": {"values": list(KINDS)},
                "classification.ipc_group": {"values": list(group["ipc_groups"])},
            },
        }
    )
    return body


def hit_first_subclass(hit: dict) -> str:
    entries = hit.get("common", {}).get("classification", {}).get("ipc", [])
    m = IPC_FULLNAME_RE.fullmatch(str(entries[0].get("fullname", "")).strip()) if entries else None
    return m.group(1) if m else ""


def doc_id_of(record_id: str, client: RospatentClient) -> str:
    """Идентификатор документа в API по номеру записи: из индекса кандидатов или по файлу в кеше /docs.

    Идентификатор документа — номер, код вида и дата публикации
    (RU<номер><код вида>_ГГГГММДД); дату знает только API, поэтому номер
    сначала должен встретиться в выдаче команды search.
    """
    index = load_doc_index(client.raw_dir)
    if record_id in index:
        return index[record_id]
    cached = sorted((client.raw_dir / "docs").glob(f"{record_id}_*.json"))
    if len(cached) == 1:
        return cached[0].stem
    raise ApiError(f"{record_id}: документа нет в кеше кандидатов — сначала команда search")


def load_doc_index(raw_dir: Path) -> dict[str, str]:
    path = raw_dir / "candidates" / "doc_index.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def save_doc_index(raw_dir: Path, index: dict[str, str]) -> None:
    path = raw_dir / "candidates" / "doc_index.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dict(sorted(index.items())), ensure_ascii=False, indent=1), encoding="utf-8")


def load_groups() -> dict:
    return json.loads(GROUPS_PATH.read_text(encoding="utf-8"))


# --- команды ----------------------------------------------------------------------


def cmd_search(args: argparse.Namespace) -> None:
    client = RospatentClient(args.raw_dir, args.pause, args.offline)
    plan = load_groups()
    index = load_doc_index(args.raw_dir)
    out_dir = args.raw_dir / "candidates"
    out_dir.mkdir(parents=True, exist_ok=True)
    only = set(args.group or [])
    for topic in plan["topics"]:
        for group in topic["groups"]:
            if only and group["key"] not in only:
                continue
            result = client.search(search_body(group, args.limit))
            hits = result.get("hits", [])
            rows = []
            fetched = 0
            for rank, hit in enumerate(hits, start=1):
                first = hit_first_subclass(hit)
                row = {
                    "rank": rank,
                    "doc_id": hit.get("id"),
                    "first_subclass": first,
                    "title_raw": (hit.get("biblio", {}).get("ru") or {}).get("title", ""),
                    "similarity_norm": hit.get("similarity_norm"),
                }
                if first == topic["subclass"] and fetched < args.docs:
                    record = to_record(client.doc(hit["id"]))
                    fetched += 1
                    index[record.data["id"]] = hit["id"]
                    row.update(
                        {
                            "record": record.data,
                            "problems": rule_problems(record, topic["subclass"]),
                            "tail": record.tail,
                            "kept_abbr": record.kept_abbr,
                            "suspicious": record.suspicious,
                        }
                    )
                rows.append(row)
            with (out_dir / f"{group['key']}.jsonl").open("w", encoding="utf-8") as f:
                for row in rows:
                    f.write(json.dumps(row, ensure_ascii=False) + "\n")
            save_doc_index(args.raw_dir, index)
            usable = sum(1 for r in rows if "record" in r and not r["problems"])
            print(
                f"{group['key']:<8} всего {result.get('total')}, в выдаче {len(hits)}, "
                f"первый код из {topic['subclass']}: {sum(r['first_subclass'] == topic['subclass'] for r in rows)}, "
                f"рефератов загружено {fetched}, годных {usable}"
            )
    save_doc_index(args.raw_dir, index)
    print(f"запросов к API в этом запуске: {client.network_requests}; кандидаты — {out_dir}")


def build_records(client: RospatentClient) -> tuple[list[dict], list[str], list[dict]]:
    plan = load_groups()
    records: list[dict] = []
    errors: list[str] = []
    report: list[dict] = []
    seen: set[str] = set()
    for topic in plan["topics"]:
        for group in topic["groups"]:
            for record_id in group["ids"]:
                if record_id in seen:
                    errors.append(f"{record_id}: повтор (уже есть в корпусе)")
                    continue
                seen.add(record_id)
                record = load_record(client, doc_id_of(record_id, client), original_abstract=True)
                if record.data["id"] != record_id:
                    errors.append(f"{record_id}: в документе номер {record.data['id']}")
                problems = rule_problems(record, topic["subclass"])
                errors += [f"{record_id}: {p}" for p in problems]
                records.append(record.data)
                report.append(
                    {
                        "id": record_id,
                        "topic": topic["subclass"],
                        "group": group["key"],
                        "raw_title": record.raw_title,
                        "title": record.data["title"],
                        "kept_abbr": record.kept_abbr,
                        "suspicious": record.suspicious,
                        "tail": record.tail,
                        "abstract_source": record.abstract_source,
                    }
                )
    return records, errors, report


def cmd_build(args: argparse.Namespace) -> None:
    client = RospatentClient(args.raw_dir, args.pause, args.offline)
    records, errors, report = build_records(client)
    if errors:
        print("Ошибки — корпус не записан:")
        for e in errors:
            print("  -", e)
        sys.exit(1)
    CORPUS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with CORPUS_PATH.open("w", encoding="utf-8") as f:
        for data in records:
            f.write(json.dumps({k: data[k] for k in FIELDS}, ensure_ascii=False) + "\n")
    plan = load_groups()
    print(f"записано {len(records)} записей в {CORPUS_PATH.relative_to(REPO_ROOT)}")
    for topic in plan["topics"]:
        sizes = [len(g["ids"]) for g in topic["groups"]]
        print(f"  {topic['subclass']}: {sum(sizes)} ({' + '.join(map(str, sizes))})")
    lengths = [len(r["abstract"]) for r in records]
    years = [r["year"] for r in records]
    print(
        f"рефераты: от {min(lengths)} до {max(lengths)} символов, медиана {statistics.median(lengths):.0f}; "
        f"годы публикации: {min(years)}–{max(years)}; запросов к API: {client.network_requests}"
    )
    from_xml = sum(r["abstract_source"] == "xml" for r in report)
    print(f"рефератов из исходного XML документа (в /docs — копия DOCDB): {from_xml}; из /docs: {len(report) - from_xml}")
    converted = [r for r in report if r["raw_title"] != r["title"]]
    print(f"названий, приведённых из прописных (правило 5): {len(converted)}")
    for r in converted:
        if r["kept_abbr"] or r["suspicious"]:
            print(f"  {r['id']}: «{r['title']}» | оставлены прописными: {r['kept_abbr']} | проверить: {r['suspicious']}")


def cmd_spotcheck(args: argparse.Namespace) -> None:
    """По 2 записи на тему (детерминированно по SHA-256 номера) — для ручной сверки с ФИПС."""
    plan = load_groups()
    corpus = {r["id"]: r for r in map(json.loads, CORPUS_PATH.read_text(encoding="utf-8").splitlines())}
    print("| Тема | Номер | Страница ФИПС | (54) Название | (51) МПК | (45) Год | (57) Реферат: начало … конец |")
    print("|---|---|---|---|---|---|---|")
    for topic in plan["topics"]:
        ids = [i for g in topic["groups"] for i in g["ids"]]
        chosen = sorted(ids, key=lambda i: hashlib.sha256(i.encode()).hexdigest())[:2]
        for record_id in sorted(chosen):
            r = corpus[record_id]
            ab = r["abstract"]
            print(
                f"| {topic['subclass']} | {r['id']} | {r['source']} | {r['title']} | {', '.join(r['ipc'])} | "
                f"{r['year']} | {ab[:90]} … {ab[-70:]} |"
            )


def _same_text(a: str, b: str) -> bool:
    return " ".join(a.split()) == " ".join(b.split())


def _same_title(a: str, b: str) -> bool:
    """Название сравнивается без учёта регистра: в корпусе оно приведено по правилу 5."""
    return " ".join(a.split()).upper() == " ".join(b.split()).upper()


def cmd_verify(args: argparse.Namespace) -> None:
    """Сверка каждой записи корпуса с двумя ответами API: GET /docs и XML документа ST96.

    Поля: номер, вид, название, коды МПК (набор, первый код, порядок), год, реферат.
    Печатает сводку и расхождения; полный отчёт — в ../kt2-raw/verify_report.json.
    Страницы реестра ФИПС не открываются (robots.txt ФИПС).
    """
    client = RospatentClient(args.raw_dir, args.pause, args.offline)
    corpus = [json.loads(s) for s in CORPUS_PATH.read_text(encoding="utf-8").splitlines() if s.strip()]
    checks = ("номер", "вид", "название", "МПК: набор", "МПК: первый код", "МПК: порядок", "год", "реферат")
    stats = {c: {"корпус = /docs": 0, "корпус = XML": 0, "/docs = XML": 0} for c in checks}
    report = []
    for rec in corpus:
        doc = client.doc(doc_id_of(rec["id"], client))
        common = doc.get("common", {})
        from_docs = to_record(doc)
        xml = client.xml(doc)
        x = st96_fields(xml) if xml else None
        markup = st96_abstract_markup(xml) if xml else None
        xml_abstract = abstract_text(markup)[0] if markup else None
        docs_format = docs_abstract_format(doc)
        raw_title = str((doc.get("biblio", {}).get("ru") or {}).get("title", ""))
        values = {
            "номер": (rec["id"], from_docs.data["id"], f"{x['office']}{x['number']}{x['kind']}" if x else None),
            "вид": (rec["id"][-2:], str(common.get("kind", "")), x["kind"] if x else None),
            "название": (rec["title"], raw_title, x["title"] if x else None),
            "МПК: набор": (sorted(rec["ipc"]), sorted(from_docs.data["ipc"]), sorted(x["ipc"]) if x else None),
            "МПК: первый код": (rec["ipc"][0], from_docs.data["ipc"][0], x["ipc"][0] if x and x["ipc"] else None),
            "МПК: порядок": (rec["ipc"], from_docs.data["ipc"], x["ipc"] if x else None),
            "год": (rec["year"], from_docs.data["year"], x["year"] if x else None),
            "реферат": (rec["abstract"], from_docs.data["abstract"], xml_abstract),
        }
        row = {"id": rec["id"], "docs_abstract_format": docs_format, "differences": []}
        for check, (in_corpus, in_docs, in_xml) in values.items():
            equal = _same_title if check == "название" else (_same_text if check == "реферат" else (lambda a, b: a == b))
            pairs = {
                "корпус = /docs": equal(in_corpus, in_docs),
                "корпус = XML": in_xml is not None and equal(in_corpus, in_xml),
                "/docs = XML": in_xml is not None and equal(in_docs, in_xml),
            }
            for name, ok in pairs.items():
                stats[check][name] += ok
            if not all(pairs.values()):
                row["differences"].append({"поле": check, **{k: v for k, v in pairs.items()}})
        report.append(row)
    out = args.raw_dir / "verify_report.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    n = len(corpus)
    print(f"Сверка {n} записей корпуса с GET /docs и XML документа (запросов к API: {client.network_requests})")
    print("| Поле | корпус = /docs | корпус = XML | /docs = XML |")
    print("|---|---|---|---|")
    for check in checks:
        s = stats[check]
        print(f"| {check} | {s['корпус = /docs']} из {n} | {s['корпус = XML']} из {n} | {s['/docs = XML']} из {n} |")
    formats = {}
    for row in report:
        formats[row["docs_abstract_format"]] = formats.get(row["docs_abstract_format"], 0) + 1
    print("формат реферата в /docs:", formats)
    for row in report:
        if row["differences"]:
            print(row["id"], row["docs_abstract_format"], "|", "; ".join(
                f"{d['поле']}: " + ", ".join(k for k in ("корпус = /docs", "корпус = XML", "/docs = XML") if not d[k]) + " — нет"
                for d in row["differences"]))
    print("отчёт:", out)


def cmd_selftest(_: argparse.Namespace) -> None:
    """Проверка нормализации на встроенных примерах (без сети)."""
    cases_tail = {
        "Текст реферата. 3 ил.": ("Текст реферата.", "3 ил."),
        "Текст. 2 з.п. ф-лы, 3 ил.": ("Текст.", "2 з.п. ф-лы, 3 ил."),
        "Текст. 2 с. и 1 з.п. ф-лы. 1 ил., 2 табл.": ("Текст.", "2 с. и 1 з.п. ф-лы. 1 ил., 2 табл."),
        "Текст. 1 н. и 5 з.п. ф-лы, 2 ил.": ("Текст.", "1 н. и 5 з.п. ф-лы, 2 ил."),
        "Текст. 1 табл., 2 пр.": ("Текст.", "1 табл., 2 пр."),
        "Текст. 5 з.п. ф-лы": ("Текст.", "5 з.п. ф-лы"),
        "Нагрев до 120 градусов.": ("Нагрев до 120 градусов.", ""),
    }
    for src, expected in cases_tail.items():
        assert strip_tail(src) == expected, (src, strip_tail(src))
    xml = (
        '<pat:Abstract><div><span style="x">[12]</span><p>Изобретение относится к поливу. '
        "Датчик\nвлажности C<sub>2</sub> &amp; клапан. 2 з.п. ф-лы, 1 ил."
        '<img src="/media/x/00000003.TIF/png"/></p></div></pat:Abstract>'
    )
    text, tail, issues = abstract_text(xml)
    assert text == "Изобретение относится к поливу. Датчик влажности C2 & клапан.", text
    assert tail == "2 з.п. ф-лы, 1 ил." and not issues, (tail, issues)
    _, _, issues = abstract_text('<p>по формуле<br/><img src="f.JPG"/><br/> где n - число. 1 ил.</p>')
    assert issues == ["рисунок или формула-картинка внутри текста реферата"], issues
    assert strip_tail("Текст. 6 з.п. ф - лы, 7 ил.") == ("Текст.", "6 з.п. ф - лы, 7 ил.")
    assert strip_tail("Текст. 1 з.п. ф-лы, 3 ил,") == ("Текст.", "1 з.п. ф-лы, 3 ил,")
    assert strip_tail("повысить качество очистки, 3 ил.") == ("повысить качество очистки", "3 ил.")
    assert strip_tail("В течение 2 пробных циклов.") == ("В течение 2 пробных циклов.", "")
    st96 = (
        f'<pat:Doc xmlns:pat="{ST96_PAT}" xmlns:com="{ST96_COM}">'
        '<pat:Abstract com:languageCode="ru" pat:dataFormat="docdba"><com:P>Обрезанный текст</com:P></pat:Abstract>'
        '<pat:Abstract com:languageCode="ru" pat:dataFormat="original"><com:P com:pNumber="5">Подача CO<com:Sub>2</com:Sub>'
        " &amp; азота.<com:Br/>Вторая строка. 2 ил.<com:Image><com:FileName>00000001.TIF</com:FileName></com:Image>"
        "</com:P></pat:Abstract></pat:Doc>"
    ).encode()
    text, tail, issues = abstract_text(st96_abstract_markup(st96))
    assert (text, tail, issues) == ("Подача CO2 & азота. Вторая строка.", "2 ил.", []), (text, tail, issues)
    title, kept, suspicious = sentence_case("УСТРОЙСТВО ДЛЯ УФ-ОБЕЗЗАРАЖИВАНИЯ ВОДЫ С КОНТРОЛЕМ PH", "Вода, УФ-лампа, pH среды.")
    assert title == "Устройство для УФ-обеззараживания воды с контролем pH", title
    assert kept == ["УФ", "pH"] and not suspicious, (kept, suspicious)
    assert sentence_case("Способ полива", "")[0] == "Способ полива"
    title, kept, _ = sentence_case("СПОСОБ ОПРЕДЕЛЕНИЯ ТОКСИЧНОСТИ, ПРИМЕНЕНИЕ Mg2+-АТФазы МОЗГА", "токсичность среды")
    assert title == "Способ определения токсичности, применение Mg2+-АТФазы мозга", title
    assert sentence_case('ПРОТИВОПОЖАРНАЯ ДВЕРЬ "АБВ"', "Полотно двери.")[0] == 'Противопожарная дверь "АБВ"'
    assert ipc_codes([{"fullname": "A01G25/16"}, {"fullname": "G01N33/24"}, {"fullname": "A01G25/16"}]) == (
        ["A01G 25/16", "G01N 33/24"],
        [],
    )
    assert ipc_codes([{"fullname": "A01G25/16"}, {"fullname": "G01N"}]) == (["A01G 25/16"], ["G01N"])
    assert publication_year("2003.11.27") == 2003 and publication_year("20031127") == 2003
    print("selftest: OK")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--raw-dir", type=Path, default=DEFAULT_RAW_DIR, help="кеш сырых ответов API (вне репозитория)")
    parser.add_argument("--pause", type=float, default=1.2, help="пауза между запросами к API, с (не меньше 1)")
    parser.add_argument("--offline", action="store_true", help="только кеш, без запросов к API")
    sub = parser.add_subparsers(dest="command", required=True)
    p_search = sub.add_parser("search", help="кандидаты по поисковым запросам групп")
    p_search.add_argument("--group", action="append", help="только эта группа (ключ из groups.json); можно повторять")
    p_search.add_argument("--limit", type=int, default=60, help="сколько документов брать из выдачи API")
    p_search.add_argument("--docs", type=int, default=14, help="сколько рефератов загружать на группу")
    sub.add_parser("build", help="корпус по номерам из groups.json")
    sub.add_parser("spotcheck", help="адреса ФИПС и поля для ручной сверки")
    sub.add_parser("verify", help="сверка корпуса с GET /docs и XML документа")
    sub.add_parser("selftest", help="проверка нормализации без сети")
    args = parser.parse_args(argv)
    handlers = {"search": cmd_search, "build": cmd_build, "spotcheck": cmd_spotcheck, "verify": cmd_verify, "selftest": cmd_selftest}
    try:
        handlers[args.command](args)
    except ApiError as error:
        sys.exit(f"Ошибка API: {error}")


if __name__ == "__main__":
    main()
