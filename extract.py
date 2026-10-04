"""Извлечение 50 признаков из выписных эпикризов (ОКС) правилами.

extract(text) -> (values, evidence): значение каждого поля и цитата из текста,
которая его подтверждает. Правила рассчитаны на разные формулировки и сокращения.
"""
import re

NU = "не указано"
NUM = r"(\d+(?:[.,]\d+)?)"
MONTHS = {"января": 1, "февраля": 2, "марта": 3, "апреля": 4, "мая": 5, "июня": 6, "июля": 7,
          "августа": 8, "сентября": 9, "октября": 10, "ноября": 11, "декабря": 12}
DATE = (r"(\d{1,2}[./-]\d{1,2}[./-]\d{2,4}|\d{4}-\d{2}-\d{2}|\d{1,2}\s+(?:" + "|".join(MONTHS) + r")\s+\d{4})")
ROMAN = {"I": "1", "II": "2", "III": "3", "IV": "4"}

# сегменты, описывающие НЕ первое измерение
LATER = r"контрол|повторн|в динамике|перед выпиской|при выписке|на момент выписки|к выписке"
NEG = r"отрица\w+|\bнет\b|не выявлен|не зарегистр|не установлен|не подтвержд|исключ[её]н|отсутству|не получено|не отмеча|не определя"


def norm_date(s):
    """Любая запись даты -> ДД.ММ.ГГГГ."""
    s = s.strip()
    m = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", s)
    if m:
        return f"{m.group(3)}.{m.group(2)}.{m.group(1)}"
    m = re.fullmatch(r"(\d{1,2})\s+([а-я]+)\s+(\d{4})", s)
    if m:
        return f"{int(m.group(1)):02d}.{MONTHS[m.group(2)]:02d}.{m.group(3)}"
    d, mo, y = re.split(r"[./-]", s)
    if len(y) == 2:
        y = "20" + y
    return f"{int(d):02d}.{int(mo):02d}.{y}"


def num(s):
    return s.replace(",", ".")


SENT_END = re.compile(r"\.\s+(?=[А-ЯЁA-Z\d])|\n")       # «мм рт. ст., ЧСС» не разрывает предложение
CLAUSE_END = re.compile(r"\.\s+(?=[А-ЯЁA-Z\d])|\n|;")


def _span(text, pos, rx):
    a = 0
    for m in rx.finditer(text):
        if m.end() > pos:
            break
        a = m.end()
    m = rx.search(text, pos)
    return text[a:m.start() + 1 if m and text[m.start()] == "." else (m.start() if m else len(text))].strip()


def clause(text, pos):
    """Фрагмент между ближайшими разделителями (конец предложения, ';', перевод строки)."""
    return _span(text, pos, CLAUSE_END).rstrip(".")


def sentence(text, pos):
    return _span(text, pos, SENT_END)


def first(pattern, text, flags=0, skip=None):
    """Первое совпадение, чьё предложение не относится к повторным измерениям."""
    fallback = None
    for m in re.finditer(pattern, text, flags):
        if skip and re.search(skip, sentence(text, m.start()), re.I):
            fallback = fallback or m
            continue
        return m
    return fallback


def flag(pattern, scope, neg=NEG):
    """1 — признак прямо указан, 0 — отрицание или нет упоминания."""
    for m in re.finditer(pattern, scope):
        c = clause(scope, m.start())
        if re.search(neg, c, re.I):
            continue
        return "1", c
    return "0", ""


# ---------------------------------------------------------------- словари
LAD = r"(?:ПМЖВ|ПМЖА|ПНА|LAD|[Пп]ередн\w+ (?:межжелудочков\w+|нисходящ\w+) (?:ветв\w+|артери\w+))"
RCA = r"(?:ПКА|RCA|[Пп]рав\w+ коронарн\w+ артери\w+)"
ECG_RECORD = (r"синусов\w+ ритм|ритм\w*\s*[:—–-]?\s*синусов|фибрилляц|мерцательн|трепетани|ЧСС\W{0,4}\d{2,3}"
              r"|(?:эктопическ|узлов|предсердн|идиовентрикулярн|несинусов|желудочков)\w* ритм|ритм\w* (?:ЭКС|кардиостимулятора)")
# слово «рентген…» как исследование, а не фамилия («Рентгенов»)
XRAY = r"(?:[Рр]ентгенограф\w+|[Рр]ентгенограмм\w+|[Рр]ентгенологическ\w+|[Рр]ентгеноскоп\w+|[Рр]ентген(?![а-яё])|\bRg\b|R-граф\w+|\bОГК\b)"
KAG = r"(?:[Кк]оронаро(?:ангио)?графи\w+|КАГ|КВГ|[Кк]оронаровентрикулографи\w+)"

MEDS = {
    "aspirin": r"\bАСК\b|ацетилсалицил|аспирин|кардиомагнил|тромбо[\s-]?асс|ацекардол|кардиаск",
    "2_aag": r"клопидогрел|тикагрелор|прасугрел|брилинт|плавикс|зилт|эффиент|лопирел",
    "anticoagulant": r"\w+ксабан|варфарин|дабигатран|ксарелто|эликвис|прадакс|эноксапарин|фондапаринукс|гепарин",
    "ace_ing_sartan": r"\w+прила?\b|\w+[сз]артана?\b|престариум|диротон|лориста|валз\b",
    "bb": r"бисопролол|метопролол|карведилол|небиволол|атенолол|бетаксолол|\w+олола?\b|конкор|беталок|эгилок",
    "statin": r"\w+статина?\b|крестор|липримар|аторис|роксера|мертенил",
}
DISCHARGE = r"при выписке|после выписки|рекомендовано|рекомендации|амбулаторн|продолжить при[её]м"

LABS = {
    "crea": r"креатинин\w*",
    "glu": r"(?:глюкоз\w+|гликеми\w+)",
    "hb": r"(?:гемоглобин\w*|\bHb\b|\bHGB\b)",
    "ldl": r"(?:(?:ХС|холестерин)[- ]?)?(?:ЛПНП|ЛНП|LDL)",
    "leucocytes": r"(?:лейкоцит\w+|\bWBC\b)",
    "thrombocytes": r"(?:тромбоцит\w+|\bPLT\b)",
    "tot_chol": r"(?:общ\w+ холестерин\w*|холестерин\w* общ\w+|\bОХС\b|\bОХ\b|ХС общ\w+)",
}
# между названием показателя и числом: скобки, 1–2 слова, знаки
LAB_GAP = r"(?:\s*\([^)\d]*\))?(?:\s+[а-яё]+){0,2}?\s*[:=—–-]?\s*"


def vessel(name, text):
    for m in re.finditer(name + r"\s*[:—–-]?\s*([^;\n]*?)(?=;|\.\s|\.$|\n|$)", text, re.M):
        d = m.group(1).lower()
        pcts = [float(num(p)) for p in re.findall(NUM + r"\s*%", d)]
        if re.search(r"окклюз", d):
            v = "2"
        elif pcts:
            n = max(pcts)
            v = "0" if n < 50 else "1" if n < 90 else "2"
        elif re.search(r"\bнет\b|без |интактн|не выявлен|не изменен|проходим|не сужен", d):
            v = "0"
        else:
            continue
        return v, m.group(0).strip()
    return NU, ""


ABBR = ["ИМТ", "ЧДД", "ЧСС", "ФВ", "КДР", "ХСН", "ХБП", "ХОБЛ", "ЭКГ", "МКБ", "ПМЖВ", "ПНА", "ПКА", "КАГ", "АСК",
        "ЛПНП", "ЛНП", "ОХС", "ФК", "ТЛТ", "ОГК", "ЛЖ", "SpO2", "Killip", "ЭхоКГ"]
ABBR_RX = re.compile(r"(?<![А-Яа-яЁёA-Za-z])(?:" + "|".join(ABBR) + r")(?![А-Яа-яЁёA-Za-z])", re.I)
ABBR_MAP = {a.lower(): a for a in ABBR}
NUM_ABBR = re.compile(r"(?<![А-Яа-яЁёA-Za-z])(ад|лп)(?=\s*[:—–=-]?\s*\d)", re.I)      # «ад 120/80», «лп 44 мм»


def canon(text):
    """«имт», «Имт», «чдд» -> «ИМТ», «ЧДД». Замена той же длины, позиции в тексте сохраняются."""
    text = ABBR_RX.sub(lambda m: m.group(0) if m.group(0).isupper() and m.group(0).lower() not in ("spo2", "killip", "эхокг")
                       else ABBR_MAP[m.group(0).lower()], text)
    return NUM_ABBR.sub(lambda m: m.group(0).upper(), text)


def _extract(text):
    """Разбор по тексту с приведёнными сокращениями; цитаты возвращаются в исходном написании."""
    norm = canon(text)
    r, ev = _rules(norm)
    if norm != text:
        for k, q in ev.items():
            note = re.search(r"\s*\[[^\]]*\]\s*$", q)
            body = q[:note.start()] if note else q
            i = norm.find(body) if body else -1
            if i >= 0:
                ev[k] = text[i:i + len(body)] + (note.group(0) if note else "")
    return r, ev


def _rules(text):
    text = text.replace(" ", " ").replace(" ", " ").replace("\r", "")
    r, ev = {}, {}

    def put(key, value, quote=""):
        r[key], ev[key] = value, quote

    def grab(key, pattern, scope=None, flags=0, conv=None, skip=None):
        m = first(pattern, text if scope is None else scope, flags, skip)
        if m:
            v = m.group(1)
            put(key, conv(v) if conv else v, m.group(0).strip())
        else:
            put(key, NU)

    # ================= даты эпизода
    grab("admission_date", r"(?:[Пп]оступил[аи]?|[Гг]оспитализирован[аы]?|[Дд]ата (?:поступления|госпитализации))\s*[:—–-]?\s*" + DATE, conv=norm_date)
    grab("discharge_date", r"(?:[Вв]ыписан[аы]?|[Дд]ата выписки)\s*[:—–-]?\s*" + DATE, conv=norm_date)
    m = re.search(r"\bс\s*" + DATE + r"\s*(?:г\.?\s*)?(?:по|до|—|–|-)\s*(?:" + DATE + r"|не указан\w*|[—_-]+|\?)", text)
    if m:
        if r["admission_date"] == NU:
            put("admission_date", norm_date(m.group(1)), m.group(0))
        if r["discharge_date"] == NU and m.group(2):
            put("discharge_date", norm_date(m.group(2)), m.group(0))

    # ================= диагноз
    lines = text.split("\n")
    dx_lines = []
    for i, l in enumerate(lines):
        if re.search(r"диагноз|[Сс]опутств|[Фф]онов|[Оо]сложнени|МКБ", l):
            dx_lines.append(l)
            # заголовок на отдельной строке — берём абзац под ним
            if re.fullmatch(r"\s*[^.]{0,60}:\s*", l):
                j = i + 1
                while j < len(lines) and lines[j].strip():
                    if lines[j] not in dx_lines:
                        dx_lines.append(lines[j])
                    j += 1
    dx = "\n".join(dict.fromkeys(dx_lines)) or text
    main = next((l for l in dx.split("\n") if re.search(r"[Оо]сновн", l)),
                next((l for l in dx.split("\n") if re.search(r"МКБ|инфаркт|стенокарди|коронарн", l)), dx))

    m = re.search(r"[Оо]сновн\w+(?: диагноз\w*| заболевани\w+)?\s*[:.—–-]", main)
    if m:                       # обрезаем до конца формулировки основного диагноза
        rest = main[m.start():]
        e = re.search(r"МКБ[^.\n]{0,12}?[A-Z]\d{2}(?:\.\d)?|[Сс]опутств|[Фф]онов|[Оо]сложнени", rest[10:])
        main = rest[:10 + (e.end() if e and e.group(0).startswith("МКБ") else e.start())] if e else rest[:400]

    put("art_hyper", *flag(r"[Гг]ипертоническая болезнь|\bГБ\b|(?<![её]гочная )[Аа]ртериальная гипертензия|\bАГ\b|[Ээ]ссенциальная гипертензия", dx))
    put("atr_fibril", *flag(r"[Фф]ибрилляци\w+ предсердий|[Тт]репетани\w+ предсердий|\bФП\b|\bТП\b|[Мм]ерцательн\w+ аритми\w+", dx))
    put("copd", *flag(r"ХОБЛ|[Хх]роническ\w+ обструктивн\w+", dx))
    put("dm", *flag(r"[Сс]ахарн\w+ диабет\w*|\bСД\b|\bСД\s?[12]\b", dx))

    m = re.search(r"(?:ХБП|[Хх]роническ\w+ болезн\w+ почек)\s*[СCcс]?\s?(\d)\s?([АБабAB]?)", dx)
    if m:
        letter = m.group(2).upper().replace("A", "А").replace("B", "Б")
        put("ckd", f"ХБП {m.group(1)}{letter}", m.group(0))
    else:
        put("ckd", NU)

    m = re.search(r"(?:ХСН|[Хх]роническ\w+ сердечн\w+ недостаточност\w+)[^;\n]*?ФК\s*(?:\d|[IV]+)", dx) or \
        re.search(r"(?:ХСН|[Хх]роническ\w+ сердечн\w+ недостаточност\w+)\s*(?:\d|[IV]+)\s?[АБаб]?(?:\s*ст\w*)?", dx)
    put("hf", m.group(0).rstrip(" .") if m else NU, m.group(0) if m else "")

    grab("diagnosis_icd", r"(?:МКБ(?:[- ]?(?:10|X))?|ICD(?:-10)?)\s*[:—–-]?\s*([A-Z]\d{2}(?:\.\d)?)")
    if r["diagnosis_icd"] == NU:
        grab("diagnosis_icd", r"\b(I2[0-5](?:\.\d)?)\b", scope=dx)

    m = re.search(r"(?:Killip|Киллип)\w*\s*[:—–-]?\s*(?:класс\w*\s*)?(IV|III|II|I|[1-4])\b", text) or \
        re.search(r"\b(IV|III|II|I|[1-4])\s*класс\w*\s*(?:по\s*)?(?:Killip|Киллип)", text)
    put("killip", ROMAN.get(m.group(1), m.group(1)) if m else NU, sentence(text, m.start()) if m else "")

    put("tlt", *flag(r"[Тт]ромболизис\w*|[Тт]ромболитическ\w+|\bТЛТ\b|[Аа]лтеплаз\w+|[Тт]енектеплаз\w+|[Фф]ортелизин\w*|[Пп]роурокиназ\w+|[Сс]трептокиназ\w+",
                     text, neg=NEG + r"|не проводи|не выполня|не применя|без тромболи|противопоказан"))

    ml = main.lower()
    icd = r["diagnosis_icd"]
    if re.search(r"без (?:подъ[её]ма|элеваци\w+)(?: сегмента)? st|бп\s?st|nstemi|non-st", ml):
        t = "NSTEMI"
    elif re.search(r"(?:подъ[её]мом|элеваци\w+)(?: сегмента)? st|п\s?st\b|\bstemi", ml):
        t = "STEMI"
    elif "инфаркт" in ml and icd in ("I21.0", "I21.1", "I21.2", "I21.3"):
        t = "STEMI"
    elif "инфаркт" in ml and icd == "I21.4":
        t = "NSTEMI"
    else:
        t = "NA"
    put("type_acs", t, main.strip())
    loc = "N"
    if "инфаркт" in ml:
        loc = "A" if re.search(r"передн|перегородочн", ml) else "I" if re.search(r"нижн|задн|диафрагмальн", ml) \
            else "L" if "боков" in ml else "N"
    loc_quote = main.strip()
    if loc == "N":                                   # в тексте стенка не названа — определяем по коду МКБ-10
        by_icd = {"I21.0": "A", "I21.1": "I", "I21.2": "L", "I22.0": "A", "I22.1": "I"}.get(icd)
        if by_icd:
            loc, loc_quote = by_icd, ev.get("diagnosis_icd", icd) + " [локализация определена по коду МКБ-10]"
    put("mi_localisation", loc, loc_quote)

    # ================= осмотр при поступлении
    not_primary = LATER + r"|дома|адаптирован|привычн|рабоч\w+ АД|максимальн|до \d{3}/"
    BP = r"(?:АД|[Аа]ртериальное давление)\s*[:—–-]?\s*(\d{2,3})\s*(?:/|\\| и )\s*(\d{2,3})"
    m = first(BP, text, skip=not_primary)
    if m:
        s = sentence(text, m.start())
        put("bp", f"{m.group(1)}/{m.group(2)}", m.group(0))
        p = re.search(r"(?:[Пп]ульс|\bPs\b|\bPS\b|ЧСС)\D{0,15}?(\d{2,3})(?:\s*в\s*мин\w*)?", s)
        if p:
            put("bpm", p.group(1), p.group(0))
    else:
        put("bp", NU)
    if "bpm" not in r:
        grab("bpm", r"(?:[Пп]ульс|\bPs\b|\bPS\b)\s*[:—–-]?\s*(\d{2,3})", skip=not_primary + r"|ЭКГ")
    grab("rr", r"(?:ЧДД|ЧД\b|[Чч]астота дыхани\w+|[Чч]астота дыхательных движений)\s*[:—–-]?\s*(\d{1,2})", skip=not_primary)
    grab("spo2", r"(?:SpO2|SpO₂|SaO2|[Сс]атураци\w+(?: кислорода)?(?: крови)?)\s*[:—–-]?\s*(\d{2,3})", skip=not_primary)
    grab("height", r"[Рр]ост\s*[:—–-]?\s*(\d{3})")
    grab("weight", r"(?:[Мм]асса тела|[Вв]ес|[Мм]асса)\s*[:—–-]?\s*" + NUM + r"\s*кг", conv=num)
    grab("bmi", r"(?:ИМТ|[Ии]ндекс массы тела)\s*[:—–=-]?\s*" + NUM, conv=num)

    put("smoking", NU)
    for m in re.finditer(r"(?<![а-яё])(не курит|никогда не курил\w*|курение отрицает|некурящ\w+|бросил\w* курить|прекратил\w* курить|курил\w* ранее|"
                         r"бывш\w+ курильщик|курит|курильщик|стаж курения|курение)", text, re.I):
        s = clause(text, m.start())
        if re.search(r"исключ|отказ\w* от|прекратить|рекоменд", s, re.I):
            continue                                   # «курение исключить» — рекомендация
        w = m.group(1).lower()
        # три фиксированных статуса (подтверждено наставником)
        if re.match(r"не курит|никогда|курение отрицает|некурящ", w) or (w == "курение" and re.search(NEG, s, re.I)):
            v = "Не курит"
        elif re.match(r"бросил|прекратил|курил\w* ранее|бывш", w):
            v = "Бросил курить"
        else:
            v = "Курит"
        put("smoking", v, s)
        break

    # ================= ЭКГ (первая запись)
    # запись ЭКГ узнаём по названному ритму или ЧСС с числом; фразы «контроль ритма», «мониторинг ЭКГ» не подходят
    ecg = ""
    for i, l in enumerate(lines):
        if re.search(r"ЭКГ|[Ээ]лектрокардиогра", l) and not re.search(r"^\s*(?:" + LATER + ")", l, re.I):
            block = l if re.search(ECG_RECORD, l, re.I) else (lines[i + 1] if i + 1 < len(lines) else "")
            if re.search(ECG_RECORD, block, re.I):
                ecg = block
                break
    if not ecg or len(ecg) > 600:
        # длинная строка или документ без переводов строк: берём три предложения от упоминания ЭКГ
        for m in re.finditer(r"(?:ЭКГ|[Ээ]лектрокардиогра\w+)[^\n]{0,80}?(?:" + ECG_RECORD + ")", text, re.I):
            if re.search(r"мониторинг|контрол|наблюдени\w+ за ритм|" + LATER, text[m.start():m.end() + 12], re.I):
                continue
            ends = [e.end() for e in SENT_END.finditer(text, m.end())][:3]
            ecg = text[m.start():ends[-1] if ends else len(text)]
            break
    low = ecg.lower()
    if re.search(r"синусов", low):
        ry = "синусовый"
    elif re.search(r"фибрилляц|мерцательн|\bфп\b", low):
        ry = "фибрилляция предсердий"
    elif "трепетани" in low:
        ry = "трепетание предсердий"
    else:
        m = re.search(r"((?:эктопическ|узлов|предсердн|идиовентрикулярн|несинусов|желудочков)[а-яё]*) ритм|ритм\w* (экс|кардиостимулятора)", low)
        ry = (m.group(1) or ("ритм " + m.group(2).upper() if m.group(2) == "экс" else "ритм " + m.group(2))) if m else NU
    rq = re.search(r"синусов\w+(?: ритм\w*)?|ритм\w*\s*[:—–-]?\s*синусов\w+|фибрилляци\w+(?: предсердий)?|мерцательн\w+ аритми\w+|трепетани\w+(?: предсердий)?|\bФП\b|ритм\w*\s*[:—–-]?\s*[а-яё]+|[а-яё]+ ритм\w*", ecg, re.I)
    put("ecg_rythm", ry, rq.group(0) if rq and ry != NU else "")
    m = re.search(r"ЧСС\D{0,12}?(\d{2,3})(?:\s*(?:уд\w*\.?\s*(?:/|в)\s*мин\w*|в\s*мин\w*))?", ecg)
    put("ecg_bpm", m.group(1) if m else NU, m.group(0) if m else "")
    put("ecg_elevation", "0")
    for m in re.finditer(r"[Ээ]леваци\w+|[Пп]одъ[её]м\w*", ecg):
        c = clause(ecg, m.start())
        if "ST" in c and not re.search(NEG + r"|\bбез\b", c, re.I):
            put("ecg_elevation", "1", c)
            break
    if r["ecg_elevation"] == "0":
        m = re.search(r"[^.\n]*ST[^.\n]*", ecg)
        ev["ecg_elevation"] = m.group(0).strip() if m else ""
    put("ecg_avb", *flag(r"(?:АВ|AV|А-В|A-V)[\s-]?блокад\w+|[Аа]триовентрикулярн\w+ блокад\w+", text))
    if r["atr_fibril"] == "0" and ry in ("фибрилляция предсердий", "трепетание предсердий"):
        put("atr_fibril", "1", ecg.strip()[:200])

    # ================= ЭхоКГ
    grab("echo_ef", r"(?:ФВ|[Фф]ракци\w+ выброса|\bEF\b)(?:\s*ЛЖ)?(?:\s*\([^)]*\))?\s*[:—–=-]?\s*" + NUM + r"\s*%", conv=num)
    grab("echo_lvd", r"(?:КДР|[Кк]онечн\w+[- ]диастолическ\w+ размер)(?:\s*ЛЖ)?\s*[:—–=-]?\s*" + NUM, conv=num)
    grab("echo_lvd_2", r"(?:\bЛП\b|[Лл]ев\w+ предсерди\w+)\s*[:—–=-]?\s*" + NUM + r"\s*(?:мм|см)", conv=num)
    m = re.search(r"(?:[Мм]итральн\w+ регургитаци\w+|\bМР\b|[Рр]егургитаци\w+ на (?:митральном клапане|МК)|[Нн]едостаточность (?:митрального клапана|МК))"
                  r"\D{0,15}?(\d|I{1,3}V?)\s*(?:-?й\s*)?(?:ст|степ)\w*\.?", text)
    put("echo_mr", f"Митральная регургитация {ROMAN.get(m.group(1), m.group(1))} ст." if m else NU, m.group(0) if m else "")
    m = re.search(r"(?:[Гг]ипо|[Аа]|[Дд]ис)кинез\w*[^.;\n]*", text)
    put("echo_zone", m.group(0).strip() if m else NU, m.group(0).strip() if m else "")

    # ================= рентген
    put("rg_date", NU)
    put("rg_pc", NU)
    m = None
    for cand in re.finditer(XRAY + r"[^\n]*?" + DATE + r"\s*(?:г\.?)?[.:)]?\s*([^\n]*)", text):
        between = text[cand.start():cand.start(1)]           # от слова «рентген…» до даты
        if not re.search(r"д\.\s?р\.|рожден|возраст", between):
            m = cand                                 # не строка с фамилией и датой рождения пациента
            break
    if m:
        put("rg_date", norm_date(m.group(1)), m.group(0)[:90])
        c = re.search(r"[^.]*(?:заст[оо]\w*|от[её]к\w*|гиперволеми\w+)[^.]*", m.group(2))
        if c:
            put("rg_pc", re.sub(r"^\s*Заключение:\s*", "", c.group(0)).strip(), c.group(0).strip())

    # ================= коронарография
    refuse = re.search(r"[^.\n]*(?:отказ\w*[^.\n]{0,40}" + KAG + "|" + KAG + r"[^.\n]{0,60}отказ)[^.\n]*", text)
    done = re.search(KAG + r"\s*(?:\(|от|—|–|-|:)?\s*" + DATE, text) or \
        re.search(DATE + r"[^.\n]{0,40}(?:выполнен|провед[её]н)\w*[^.\n]{0,30}" + KAG, text) or \
        re.search(KAG + r"[^.\n]{0,30}(?:выполнен|провед[её]н)\w*[^.\n]{0,15}?" + DATE, text)
    done = done or re.search(DATE + r"\s*(?:г\.?)?[.:,]?\s*" + KAG, text)
    done_nodate = None
    for m in re.finditer(r"(?:[Вв]ыполнен|[Пп]ровед[её]н)\w*\s+(?:\w+\s+)?" + KAG + "|" + KAG + r"\s+(?:была\s+)?(?:выполнен|провед[её]н)\w*", text):
        if not re.search(r"\bне\b|отказ|планир|рекоменд", clause(text, m.start()), re.I):
            done_nodate = m
            break
    has_vessels = re.search(LAD + r"\s*[:—–-]|" + RCA + r"\s*[:—–-]", text)
    for k in ("ca_date", "ca_lad", "rca"):
        put(k, NU)
    if refuse and not has_vessels:
        put("ca_fact", "R", refuse.group(0).strip())
    elif done or has_vessels or done_nodate:
        put("ca_fact", "Y", (done or has_vessels or done_nodate).group(0))
        if done:
            d = next(g for g in done.groups() if g)
            put("ca_date", norm_date(d), done.group(0))
        put("ca_lad", *vessel(LAD, text))
        put("rca", *vessel(RCA, text))
    else:
        put("ca_fact", "N")

    # ================= анализы: первый результат текущей госпитализации
    sents = [s for l in lines for s in re.split(r"(?<=[.!?])\s+(?=[А-ЯЁA-Z])", l)]
    early = "\n".join(s for s in sents if not re.search(LATER, s, re.I))
    m = re.search(r"тропонин\w*(?:\s+(?:тест|I|T|Т|hs|вч))*[^;.\n]{0,40}?(положительн|отрицательн|повышен|в (?:пределах )?норм)", early, re.I) or \
        re.search(r"тропонин\w*(?:\s+(?:тест|I|T|Т))*[^;.\n]{0,40}?(положительн|отрицательн|повышен|в (?:пределах )?норм)", text, re.I)
    if m:
        put("card_trop", "положительный" if m.group(1).lower() in ("положительн", "повышен") else "отрицательный", m.group(0))
    else:
        put("card_trop", NU)
    for key, name in LABS.items():
        m = re.search(name + LAB_GAP + NUM, early, re.I) or re.search(name + LAB_GAP + NUM, text, re.I)
        put(key, num(m.group(1)) if m else NU, m.group(0) if m else "")

    # ================= терапия при выписке
    items = [(m.start(), m.group(1)) for m in re.finditer(r"^\s*(?:\d+[.)]|[-•–*])\s*([^\n]+)$", text, re.M)]
    marks = [m.start() for m in re.finditer(DISCHARGE, text, re.I)]
    tail_from = marks[0] if marks else 0
    tail_items = [i for p, i in items if p >= tail_from] or [i for _, i in items]
    if not any(re.search(p, i, re.I) for p in MEDS.values() for i in tail_items):
        # списка нет — препараты перечислены в строку
        tail = text[tail_from:]
        parts = re.split(r"[;\n]|,\s+(?=[А-ЯЁA-Z])|\.\s+(?=[А-ЯЁA-Z])|\s+\d{1,2}[.)]\s+(?=[А-ЯЁA-Z])", tail)
        parts = [re.sub(r"^[^:]{0,60}:\s*(?:\d{1,2}[.)]\s*)?", "", p.strip()) for p in parts]
        parts = [re.split(r"(?<=[а-яё])\s+(?=[А-ЯЁ][а-яё]+\s)", p)[0] for p in parts]   # хвост следующего предложения
        tail_items = [p for p in parts if re.search(r"\d", p)] + parts      # сначала фрагменты с дозой
    for key, pat in MEDS.items():
        hit = next((i.strip().rstrip(".;,") for i in tail_items if re.search(pat, i, re.I)), None)
        if hit and key == "aspirin":
            put(key, re.sub(r"[Аа]цетилсалицилов\w+ кислот\w+", "АСК", hit), hit)
        else:
            put(key, hit or NU, hit or "")
    return r, ev


EMPTY = {"type_acs": "NA", "mi_localisation": "N", "ca_fact": "N"}


def extract(text):
    """Основной проход, затем запасной — по тексту с исправленными опечатками в ключевых словах.
    Значение из запасного прохода берётся, если оно отличается и не пустое."""
    from typo import fix
    r, ev = _extract(text)
    fixed = fix(text)
    if fixed != text:
        r2, ev2 = _extract(fixed)
        for k, v in r2.items():
            empty = (NU, "0", EMPTY.get(k))
            if v != r[k] and not (v in empty and r[k] not in empty):
                r[k], ev[k] = v, (ev2.get(k, "") + " [исправлена опечатка в исходном тексте]").strip()
        if r["ca_fact"] != "Y":
            for k in ("ca_date", "ca_lad", "rca"):
                r[k], ev[k] = NU, ""
    return r, ev
