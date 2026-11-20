r"""Предобработка текста для BM25 — одна и та же для документов и запросов.

Шаги (порядок важен; подробно — spec/tech/rag.md, раздел 4):

1. normalize          — Unicode NFC и нижний регистр.
2. extract_ipc_codes  — коды МПК ДО токенизации, один токен без пробела: "a01g25/16".
3. tokenize           — слова и числа; дефис внутри слова сохраняется ("wi-fi").
4. lemmatize          — pymorphy3: parse(token)[0].normal_form, только кириллические токены.
5. fold_yo            — "ё" -> "е" ПОСЛЕ лемматизации (pymorphy3 отдаёт леммы с "ё").
6. remove_stopwords   — общие и патентные стоп-слова (списки ниже, леммы через "е").

preprocess(text, config) выполняет шаги 1–6; коды МПК добавляются в конец списка токенов.
Токены документа индекса = preprocess(title) + preprocess(abstract).

Статус КТ2: реализовано. Примеры в докстрингах — doctest-проверки (tests/test_search.py),
сверенные с выводом pymorphy3 2.0.6 (словарь pymorphy3-dicts-ru 2.4.417150.4580142).

Ограничения методички: поиск — только собственная реализация; rank-bm25, Whoosh,
Elasticsearch, TfidfVectorizer из scikit-learn и другие готовые поисковые индексы не
используются. Для лемматизации разрешён pymorphy3. Он импортируется лениво,
внутри функций, поэтому модуль импортируется без внешних зависимостей.
"""

from __future__ import annotations

import functools
import re
import unicodedata
from collections.abc import Iterable, Sequence
from collections.abc import Set as AbstractSet
from dataclasses import dataclass

IPC_RE = re.compile(
    r"\b([a-hавсен])(\d{2})([a-zавсенкмортх])\s*(\d{1,4})/(\d{2,6})\b"
    r"(?:\s*\(\d{4}\.\d{2}\))?"
)
"""Код МПК в тексте после normalize: раздел, класс, подкласс, группа/подгруппа, версия."""
LOOKALIKES = str.maketrans("авсенкмортх", "abcehkmoptx")
"""Кириллические буквы-двойники в коде МПК -> латинские."""
WORD_RE = re.compile(r"[^\W_]+(?:-[^\W_]+)*")
"""Слово или число; дефис внутри слова сохраняется."""
CYRILLIC_RE = re.compile(r"[а-яё]+(?:-[а-яё]+)*")
"""Токен из кириллических букв и дефисов — только такие токены лемматизируются."""

Token = str
"""Токен после предобработки: лемма, словоформа, число или код МПК ("a01g25/16")."""

GENERAL_STOPWORDS: frozenset[str] = frozenset(
    {
        # предлоги
        "без", "в", "для", "до", "за", "из", "к", "между", "на", "над", "о", "около",
        "от", "перед", "по", "под", "после", "при", "про", "с", "у", "через",
        # союзы
        "а", "если", "и", "или", "как", "когда", "либо", "но", "однако", "так",
        "также", "тем", "то", "тоже", "чем", "что", "чтобы",
        # частицы
        "бы", "вот", "даже", "еще", "же", "именно", "ли", "лишь", "не", "ни",
        "только", "уже",
        # местоимения
        "ваш", "весь", "все", "вы", "ее", "каждый", "какой", "который", "кто", "мой",
        "мы", "наш", "он", "она", "они", "оно", "свой", "себя", "такой", "твой", "тот",
        "ты", "это", "этот", "я",
        # вспомогательные глаголы
        "быть", "мочь",
    }
)
"""Общие стоп-слова: 78 лемм через «е», ровно как в spec/tech/rag.md (раздел 4.5).

Хранятся леммы — то, что возвращает pymorphy3: «во», «со», «об» он приводит к «в»,
«с», «о»; «тем» — союз «тем»; «её» — притяжательное «её» -> «ее»; «все» -> «всё» -> «все».
"""

PATENT_STOPWORDS: frozenset[str] = frozenset(
    {
        "отличаться", "содержать", "выполнить", "характеризоваться", "снабдить",
        "установить", "установленный", "расположить", "обеспечивать", "обеспечить",
        "предназначить", "включать", "относиться", "являться", "позволять",
        "заключаться", "осуществляться", "осуществлять", "изобретение", "технический",
        "результат", "причем", "возможность",
    }
)
"""Патентные стоп-слова: базовый список из 23 лемм, ровно как в spec/tech/rag.md (4.5).

Служебные обороты формулы изобретения («Изобретение относится к…», «…, содержащая…,
отличающаяся тем, что… выполнен с возможностью…», «Технический результат — …»): они
есть почти в каждом реферате и не различают документы. «установленный» и «установить»
нужны оба: pymorphy3 даёт «установленный» -> «установленный» (ADJF), но «установлен» ->
«установить». «способ», «устройство», «система» сюда НЕ входят (опыт C3).
"""


@dataclass(frozen=True)
class PreprocessConfig:
    """Флаги предобработки для опытов блока A (spec/tech/rag.md, раздел 8).

    Шаги 1–3 и 5 (NFC и нижний регистр, коды МПК, токенизация, «ё» -> «е»)
    выполняются всегда; флаги включают шаг 4 и списки шага 6.

    Attributes:
        lemmatize: лемматизировать кириллические токены pymorphy3 (шаг 4).
        general_stopwords: удалять общие стоп-слова (GENERAL_STOPWORDS).
        patent_stopwords: удалять патентные стоп-слова (PATENT_STOPWORDS).

    Конфигурации блока A (k1 = 1.2, b = 0.75):
        A1 = PreprocessConfig(lemmatize=False, general_stopwords=False, patent_stopwords=False)
        A2 = PreprocessConfig(lemmatize=True, general_stopwords=False, patent_stopwords=False)
        A3 = PreprocessConfig(lemmatize=False, general_stopwords=True, patent_stopwords=True)
        A4 = PreprocessConfig(lemmatize=True, general_stopwords=True, patent_stopwords=False)
        A5 = PreprocessConfig()  # полный конвейер — значение по умолчанию
    """

    lemmatize: bool = True
    general_stopwords: bool = True
    patent_stopwords: bool = True


def normalize(text: str) -> str:
    """Шаг 1: Unicode NFC и нижний регистр.

    NFC склеивает «разложенные» буквы (й = и + U+0306, ё = е + U+0308), которые бывают
    в тексте, скопированном из PDF и с веб-страниц; без этого слово рвётся при
    токенизации: «беспроводной» в разложенном виде даёт токен «беспроводнои».

    Args:
        text: исходный текст — название, реферат или запрос.

    Returns:
        Текст в форме NFC и в нижнем регистре.

    Example:
        >>> normalize("Датчик влажности ПОЧВЫ")
        'датчик влажности почвы'
    """
    return unicodedata.normalize("NFC", text).lower()


def extract_ipc_codes(text: str) -> tuple[list[Token], str]:
    r"""Шаг 2: извлекает коды МПК и превращает каждый в один токен без пробелов.

    Выполняется ДО токенизации, иначе «a01g 25/16» распадётся на «a01g», «25», «16».
    Работает с текстом после normalize (нижний регистр). На месте букв кода допускаются
    кириллические буквы-двойники (А, В, С, Е, Н, К, М, О, Р, Т, Х), они заменяются
    латинскими; версия редакции в скобках вида «(2006.01)» отбрасывается вместе с кодом.
    Найденный код в тексте заменяется пробелом.

    Токен = (раздел + класс + подкласс).translate(LOOKALIKES) + группа + "/" + подгруппа
    (выражение IPC_RE — в начале модуля).

    Args:
        text: текст после normalize.

    Returns:
        Пара (коды, текст без кодов). Коды — в порядке появления, повторы сохраняются
        (влияют на tf).

    Example:
        >>> codes, rest = extract_ipc_codes("датчик по мпк g01n 33/24 и а01g 25/16 (2006.01)")  # «а» в а01g — кириллическая
        >>> codes
        ['g01n33/24', 'a01g25/16']
        >>> tokenize(rest)
        ['датчик', 'по', 'мпк', 'и']
    """
    codes: list[Token] = []

    def replace(match: re.Match) -> str:
        section, klass, subclass, group, subgroup = match.groups()
        codes.append((section + klass + subclass).translate(LOOKALIKES) + group + "/" + subgroup)
        return " "

    return codes, IPC_RE.sub(replace, text)


def tokenize(text: str) -> list[Token]:
    r"""Шаг 3: разбивает текст на слова и числа, дефис внутри слова сохраняется.

    Выражение: WORD_RE = re.compile(r"[^\W_]+(?:-[^\W_]+)*").

    [^\W_] — буква или цифра любого алфавита (\w без подчёркивания). Класс символов
    тот же, что в проверке запроса в API (не меньше 3 слов), но там дефис разделяет
    слова («Wi-Fi» — два слова), а токенизатор сохраняет слово с дефисом одним токеном:
    «кремний-органическое», «wi-fi». Знаки препинания, тире «—», кавычки и скобки —
    разделители.

    Args:
        text: текст после normalize и extract_ipc_codes.

    Returns:
        Токены в порядке появления.

    Example:
        >>> tokenize("покрытие кремний-органическое, связь по wi-fi — 12 часов")
        ['покрытие', 'кремний-органическое', 'связь', 'по', 'wi-fi', '12', 'часов']
    """
    return WORD_RE.findall(text)


def lemmatize(tokens: Sequence[Token]) -> list[Token]:
    r"""Шаг 4: лемматизация pymorphy3.

    Лемматизируются только токены из кириллических букв и дефисов
    (re.fullmatch(r"[а-яё]+(?:-[а-яё]+)*", token)); коды МПК, числа и латиница
    возвращаются без изменений. Контекст не учитывается: берётся первый, самый
    вероятный разбор parse(token)[0].normal_form. Причастия приводятся к инфинитиву
    («отличающийся» -> «отличаться»). Неоднозначные случаи — spec/tech/rag.md, 4.4:
    «установленный» -> «установленный», «полив» -> «полить» (деепричастие, score 0.4).

    Реализация:
    - один pymorphy3.MorphAnalyzer() на процесс, создаётся при первом вызове
      (import pymorphy3 — внутри функции);
    - лемма одного токена кэшируется functools.lru_cache;
    - «ё» здесь не заменяется — это шаг fold_yo.

    Args:
        tokens: токены после tokenize.

    Returns:
        Леммы и нетронутые некириллические токены, в том же порядке.

    Example (вывод pymorphy3 2.0.6):
        >>> lemmatize(["отличающийся", "поливались", "воду", "a01g25/16", "wi-fi", "12"])
        ['отличаться', 'поливаться', 'вода', 'a01g25/16', 'wi-fi', '12']
        >>> lemmatize(["установленный", "установлен", "причем"])
        ['установленный', 'установить', 'причём']
    """
    return [_lemma(token) if CYRILLIC_RE.fullmatch(token) else token for token in tokens]


def fold_yo(tokens: Sequence[Token]) -> list[Token]:
    """Шаг 5: заменяет «ё» на «е» — после лемматизации.

    pymorphy3 понимает «е» на месте «ё», но нормальные формы возвращает с «ё»
    («причем» -> «причём», «емкостные» -> «ёмкостный»). После fold_yo «причём» и
    «причем» дают один токен. Без лемматизации шаг идёт сразу после токенизации.

    Args:
        tokens: токены после lemmatize (или после tokenize при lemmatize=False).

    Returns:
        Токены без буквы «ё».

    Example:
        >>> fold_yo(["причём", "ёмкостный", "датчик"])
        ['причем', 'емкостный', 'датчик']
    """
    return [token.replace("ё", "е") for token in tokens]


def expand_wordforms(lemmas: Iterable[str]) -> frozenset[str]:
    """Расширяет леммы всеми словоформами — для стоп-слов без лемматизации (опыт A3).

    Для каждой леммы берутся ВСЕ разборы
    MorphAnalyzer().parse(lemma), у которых normal_form (с «ё» -> «е») совпадает с
    леммой, и объединяются их lexeme (тоже с «ё» -> «е»); сама лемма входит в результат.
    Одного parse(lemma)[0] мало: у «мочь» первый разбор — существительное («мочи»,
    «мочью»), а формы глагола («может», «могут») дают другие разборы. У «отличаться»
    lexeme — 69 форм, включая причастия.

    Args:
        lemmas: леммы через «е» (например, GENERAL_STOPWORDS | PATENT_STOPWORDS).

    Returns:
        Множество словоформ через «е».

    Example (вывод pymorphy3 2.0.6):
        >>> forms = expand_wordforms(["отличаться", "в", "мочь"])
        >>> sorted(f for f in forms if f in {"отличающийся", "отличается", "во", "может"})
        ['во', 'может', 'отличается', 'отличающийся']
    """
    morph = _analyzer()
    forms: set[str] = set()
    for lemma in lemmas:
        forms.add(lemma)
        for parse in morph.parse(lemma):
            if parse.normal_form.replace("ё", "е") == lemma:
                forms.update(form.word.replace("ё", "е") for form in parse.lexeme)
    return frozenset(forms)


def stopwords_for(config: PreprocessConfig) -> frozenset[str]:
    """Собирает стоп-список под конфигурацию.

    Объединяет GENERAL_STOPWORDS и/или PATENT_STOPWORDS по флагам config. При
    lemmatize=True возвращает леммы как есть; при lemmatize=False — expand_wordforms(...),
    потому что токены тогда остаются словоформами. Строится один раз на конфигурацию.

    Args:
        config: флаги предобработки.

    Returns:
        Множество токенов, которые удаляет remove_stopwords.

    Example:
        >>> "отличаться" in stopwords_for(PreprocessConfig())
        True
        >>> "отличающийся" in stopwords_for(PreprocessConfig(lemmatize=False))
        True
        >>> stopwords_for(PreprocessConfig(general_stopwords=False, patent_stopwords=False))
        frozenset()
    """
    return _stopwords_for(config.lemmatize, config.general_stopwords, config.patent_stopwords)


def remove_stopwords(tokens: Sequence[Token], stopwords: AbstractSet[str]) -> list[Token]:
    """Шаг 6: удаляет токены из стоп-списка, порядок остальных сохраняется.

    Args:
        tokens: токены после fold_yo.
        stopwords: результат stopwords_for(config).

    Returns:
        Токены без стоп-слов.

    Example:
        >>> remove_stopwords(["отличаться", "тем", "что", "контроллер"], stopwords_for(PreprocessConfig()))
        ['контроллер']
    """
    return [token for token in tokens if token not in stopwords]


def preprocess(text: str, config: PreprocessConfig = PreprocessConfig()) -> list[Token]:
    """Полный конвейер: шаги 1–6, коды МПК — в конце списка.

    Применяется одинаково к документам (название и реферат по отдельности) и к
    запросам: иначе термины запроса не совпадут с терминами индекса.

    Args:
        text: название, реферат или запрос.
        config: флаги предобработки; по умолчанию полный конвейер (A5).

    Returns:
        Токены для индекса или для запроса BM25.

    Example (A5, вывод pymorphy3 2.0.6; первая фраза — основной демо-запрос):
        >>> preprocess("Хочу, чтобы грядки на даче поливались сами: датчик в земле замечает, "
        ...            "что почва пересохла, и включает воду, а если обещают дождь, полив не включается.")
        ['хотеть', 'грядка', 'дача', 'поливаться', 'сам', 'датчик', 'земля', 'замечать', 'почва', 'пересохнуть', 'вода', 'обещать', 'дождь', 'полить', 'включаться']
        >>> preprocess("Датчик по МПК G01N 33/24 (2006.01)")
        ['датчик', 'мпк', 'g01n33/24']
    """
    codes, rest = extract_ipc_codes(normalize(text))
    tokens = tokenize(rest)
    if config.lemmatize:
        tokens = lemmatize(tokens)
    tokens = fold_yo(tokens)
    tokens = remove_stopwords(tokens, stopwords_for(config))
    return tokens + codes


@functools.lru_cache(maxsize=1)
def _analyzer():
    """Один MorphAnalyzer на процесс: при создании он загружает словари."""
    import pymorphy3

    return pymorphy3.MorphAnalyzer()


@functools.lru_cache(maxsize=200_000)
def _lemma(token: Token) -> Token:
    """Лемма одного токена: первый, самый вероятный разбор pymorphy3."""
    return _analyzer().parse(token)[0].normal_form


@functools.lru_cache(maxsize=None)
def _stopwords_for(lemmatize: bool, general: bool, patent: bool) -> frozenset[str]:
    """Стоп-список строится один раз на сочетание флагов."""
    words: set[str] = set()
    if general:
        words |= GENERAL_STOPWORDS
    if patent:
        words |= PATENT_STOPWORDS
    if not words:
        return frozenset()
    return frozenset(words) if lemmatize else expand_wordforms(sorted(words))
