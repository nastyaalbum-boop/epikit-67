"""Исправление опечаток в ключевых медицинских словах (запасной шаг).

Слово исправляется, только если оно отличается от ключевого слова одной буквой
(пропуск, лишняя, замена, перестановка соседних) и само не является обычным словом.
"""
import re
from pathlib import Path

# основы ключевых слов, по которым работают правила (не короче 7 букв)
STEMS = """креатинин гемоглобин лейкоцит тромбоцит холестерин тропонин глюкоз
поступил выписан госпитализ коронарограф рентгенограф рентгенограмм сатураци регургитаци митральн
гипокинез фибрилляци предсерди синусов элеваци блокад тромболизис тромболитич гипертоническ
сахарн диабет стенокарди инфаркт окклюзи стеноз основн сопутств диагноз
клопидогрел тикагрелор прасугрел бисопролол метопролол карведилол небиволол аторвастатин розувастатин
симвастатин периндоприл рамиприл эналаприл лизиноприл лозартан валсартан телмисартан кандесартан
апиксабан ривароксабан дабигатран варфарин ацетилсалицилов""".split()
STEMS = [s for s in STEMS if len(s) >= 6]
# обычные слова, похожие на ключевые, — не трогаем даже без словаря
SAFE = ("поступлен", "поступа", "выписн", "выписк", "выписыв", "диагности", "основан", "стенок", "блокато", "инфаркты")
LATIN = {"killip": "Killip"}
HOMO = str.maketrans("ABCEHKMOPTXaceopxy", "АВСЕНКМОРТХасеорху")   # латиница, похожая на кириллицу

_vocab_file = Path(__file__).with_name("vocab.txt")
VOCAB = set(_vocab_file.read_text(encoding="utf-8").split()) if _vocab_file.exists() else set()


def _dist1(a, b):
    """Расстояние Дамерау — Левенштейна ровно 1."""
    la, lb = len(a), len(b)
    if a == b or abs(la - lb) > 1:
        return False
    if la == lb:
        d = [i for i in range(la) if a[i] != b[i]]
        return len(d) == 1 or (len(d) == 2 and d[1] == d[0] + 1 and a[d[0]] == b[d[1]] and a[d[1]] == b[d[0]])
    if la > lb:
        a, b = b, a
    return any(b[:i] + b[i + 1:] == a for i in range(len(b)))


def _fix_word(word):
    low = word.lower()
    if len(low) < 5 or low in VOCAB or any(low.startswith(s) for s in STEMS) or any(low.startswith(s) for s in SAFE):
        return word
    for stem in STEMS:
        if low[0] not in stem[:2]:
            continue
        for n in (len(stem) + 1, len(stem) - 1, len(stem)):     # лишняя буква, пропуск, замена/перестановка
            if n <= len(low) and _dist1(low[:n], stem):
                fixed = stem + low[n:]
                return fixed.upper() if word.isupper() else fixed.capitalize() if word[0].isupper() else fixed
    return word


def fix(text):
    """Возвращает текст с исправленными ключевыми словами."""
    def cyr(m):
        return _fix_word(m.group(0))

    def mixed(m):                       # «ЧCC» с латинскими буквами внутри кириллического слова
        w = m.group(0)
        return w.translate(HOMO) if re.search(r"[А-Яа-яЁё]", w) and re.search(r"[A-Za-z]", w) else w

    text = re.sub(r"[A-Za-zА-Яа-яЁё]{2,}", mixed, text)
    text = re.sub(r"[А-Яа-яЁё]{5,}", cyr, text)

    def lat(m):
        w = m.group(0)
        for k, v in LATIN.items():
            if w.lower() != k and _dist1(w.lower(), k):
                return v
        return w
    return re.sub(r"[A-Za-z]{5,7}", lat, text)
