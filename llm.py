"""Запасной путь через YandexGPT (включается флагом --llm).

Модель вызывается для полей, которые правила оставили пустыми, хотя в тексте есть намёк
на значение, и для полей, отмеченных самопроверкой. В облако уходит не весь эпикриз, а только
строки с намёком на эти поля; ФИО, дата рождения, номера и фамилии врачей заменяются метками. Ответ принимается, только если модель привела цитату, которая дословно
есть в исходном тексте, и значение проходит проверку формата. Иначе остаётся «не указано».

Настройка — переменные окружения или файл .env рядом с программой:
    YC_API_KEY    — API-ключ сервисного аккаунта
    YC_FOLDER_ID  — идентификатор каталога
    YC_MODEL      — необязательно, по умолчанию yandexgpt
"""
import json, os, re, time, urllib.error, urllib.request
from pathlib import Path

from extract import ECG_RECORD

NU = "не указано"
URL = "https://llm.api.cloud.yandex.net/foundationModels/v1/completion"
NUMBER = r"\d+(?:\.\d+)?"

# поле: (намёк в тексте, что спрашиваем, формат ответа, проверка значения)
FIELDS = {
    "admission_date": (r"поступ|госпитализ", "дата поступления на эту госпитализацию", "ДД.ММ.ГГГГ", r"\d{2}\.\d{2}\.\d{4}"),
    "discharge_date": (r"выпис", "дата выписки", "ДД.ММ.ГГГГ", r"\d{2}\.\d{2}\.\d{4}"),
    "diagnosis_icd": (r"МКБ|\bI2\d", "код основного диагноза по МКБ-10", "например I21.1", r"[A-Z]\d{2}(?:\.\d)?"),
    "ckd": (r"ХБП|болезн\w+ почек", "хроническая болезнь почек и стадия", "например ХБП 3А", r"ХБП \d[АБ]?"),
    "hf": (r"ХСН|хроническ\w+ сердечн\w+ недостаточн", "хроническая сердечная недостаточность со стадией и классом", "например ХСН 2А, ФК 2", r"ХСН .{1,25}"),
    "killip": (r"Killip|Киллип", "класс Killip, прямо указанный в тексте", "цифра 1–4", r"[1-4]"),
    "bp": (r"\bАД\b|давлен", "артериальное давление при первичном осмотре", "верхнее/нижнее, например 140/90", r"\d{2,3}/\d{2,3}"),
    "bpm": (r"пульс|ЧСС|\bPs\b", "пульс или ЧСС при первичном осмотре (не из ЭКГ)", "целое число", r"\d{2,3}"),
    "rr": (r"ЧДД|дыхан", "частота дыхания при поступлении", "целое число", r"\d{1,2}"),
    "spo2": (r"SpO|сатурац|SaO", "сатурация при поступлении", "целое число", r"\d{2,3}"),
    "height": (r"рост", "рост в сантиметрах", "целое число", r"\d{3}"),
    "weight": (r"масс\w+ тела|\bвес\b", "масса тела в килограммах", "число", NUMBER),
    "bmi": (r"ИМТ|индекс массы", "индекс массы тела, только если он прямо записан", "число", NUMBER),
    "smoking": (r"кур(?:ит|ил|ящ|ильщ)|стаж курения", "статус курения", "Курит / Не курит / Бросил курить", r"Курит|Не курит|Бросил курить"),
    "ecg_bpm": (r"ЭКГ|электрокардиогр", "ЧСС в первой записи ЭКГ", "целое число", r"\d{2,3}"),
    "ecg_rythm": (r"ЭКГ|электрокардиогр", "ритм в первой записи ЭКГ", "например синусовый или фибрилляция предсердий", r"[а-яё ]{5,40}"),
    "echo_ef": (r"ФВ|фракци\w+ выброса|\bEF\b", "фракция выброса левого желудочка в процентах", "число", NUMBER),
    "echo_lvd": (r"КДР|диастолическ\w+ размер", "конечно-диастолический размер левого желудочка", "число", NUMBER),
    "echo_lvd_2": (r"\bЛП\b|лев\w+ предсерд", "размер левого предсердия", "число", NUMBER),
    "echo_mr": (r"регургитац|митральн", "степень митральной регургитации", "например Митральная регургитация 2 ст.", r"Митральная регургитация \d ст\."),
    "echo_zone": (r"кинез", "зона нарушенной сократимости миокарда", "фрагмент текста, например Гипокинез нижней стенки ЛЖ", None),
    "rg_date": (r"рентгеногр|рентгенолог|рентгеноскоп|рентген(?![а-яё])|\bRg\b|\bОГК\b", "дата рентгенографии грудной клетки", "ДД.ММ.ГГГГ", r"\d{2}\.\d{2}\.\d{4}"),
    "rg_pc": (r"рентгеногр|рентгенолог|рентгеноскоп|рентген(?![а-яё])|\bRg\b|\bОГК\b", "фраза заключения рентгена о застое или отёке лёгких", "фрагмент текста", None),
    "ca_date": (r"коронаро(?:ангио)?граф|КАГ", "дата коронарографии", "ДД.ММ.ГГГГ", r"\d{2}\.\d{2}\.\d{4}"),
    "ca_lad": (r"ПМЖВ|ПНА|межжелудочков|нисходящ", "сужение передней межжелудочковой артерии", "0 — менее 50 %, 1 — 50–89 %, 2 — 90 % и более или окклюзия", r"[012]"),
    "rca": (r"ПКА|прав\w+ коронарн", "сужение правой коронарной артерии", "0 — менее 50 %, 1 — 50–89 %, 2 — 90 % и более или окклюзия", r"[012]"),
    "card_trop": (r"тропонин", "первый результат тропонина", "положительный / отрицательный", r"положительный|отрицательный"),
    "crea": (r"креатинин", "первое значение креатинина за госпитализацию", "число", NUMBER),
    "glu": (r"глюкоз|гликеми", "первое значение глюкозы крови", "число", NUMBER),
    "hb": (r"гемоглобин|\bHb\b", "первое значение гемоглобина", "число", NUMBER),
    "ldl": (r"ЛПНП|ЛНП|LDL", "холестерин ЛПНП", "число", NUMBER),
    "leucocytes": (r"лейкоцит|WBC", "первое значение лейкоцитов", "число", NUMBER),
    "thrombocytes": (r"тромбоцит|PLT", "первое значение тромбоцитов", "число", NUMBER),
    "tot_chol": (r"общ\w+ холестерин|ОХС", "общий холестерин", "число", NUMBER),
    "aspirin": (r"аспирин|ацетилсалицил|АСК\b|кардиомагнил", "назначение аспирина при выписке", "препарат с дозой, название — АСК", None),
    "2_aag": (r"грел\b|грелор|брилинт|плавикс", "второй антиагрегант при выписке", "препарат с дозой, как в тексте", None),
    "anticoagulant": (r"ксабан|варфарин|дабигатран|антикоагулянт", "антикоагулянт при выписке", "препарат с дозой, как в тексте", None),
    "ace_ing_sartan": (r"прил\b|сартан|зартан", "ингибитор АПФ или сартан при выписке", "препарат с дозой, как в тексте", None),
    "bb": (r"олол\b|бета-блокатор|β-блокатор", "бета-блокатор при выписке", "препарат с дозой, как в тексте", None),
    "statin": (r"статин", "статин при выписке", "препарат с дозой, как в тексте", None),
}
NUMERIC_QUOTE = {k for k, v in FIELDS.items() if v[3] in (NUMBER, r"\d{2,3}", r"\d{1,2}", r"\d{3}", r"\d{2,3}/\d{2,3}")}

SYSTEM = ("Ты извлекаешь данные из кардиологического выписного эпикриза. Отвечай только JSON-объектом без пояснений. "
          "Для каждого запрошенного поля верни {\"value\": \"...\", \"quote\": \"...\"}, где quote — дословный фрагмент "
          "эпикриза, из которого взято значение. Ничего не вычисляй и не додумывай. Если значения в тексте нет, "
          "верни {\"value\": \"не указано\", \"quote\": \"\"}. Числа — без единиц, с десятичной точкой. "
          "Тебе дан не весь документ, а отдельные фрагменты; личные данные заменены метками в квадратных скобках — "
          "не включай метки в цитаты.")


def load_env():
    """Читает .env рядом с программой, не перезаписывая уже заданные переменные."""
    f = Path(__file__).with_name(".env")
    if f.exists():
        for line in f.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip("\"'"))


def configured():
    load_env()
    return bool(os.environ.get("YC_API_KEY") and os.environ.get("YC_FOLDER_ID"))


def yandex_call(system, user, timeout=60):
    """Один запрос к YandexGPT; возвращает текст ответа."""
    folder = os.environ["YC_FOLDER_ID"]
    body = {
        "modelUri": f"gpt://{folder}/{os.environ.get('YC_MODEL', 'yandexgpt')}/latest",
        "completionOptions": {"stream": False, "temperature": 0, "maxTokens": "1500"},
        "messages": [{"role": "system", "text": system}, {"role": "user", "text": user}],
    }
    req = urllib.request.Request(URL, data=json.dumps(body).encode("utf-8"), method="POST", headers={
        "Content-Type": "application/json", "Authorization": f"Api-Key {os.environ['YC_API_KEY']}", "x-folder-id": folder})
    last = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            return data["result"]["alternatives"][0]["message"]["text"]
        except urllib.error.HTTPError as e:
            last = f"HTTP {e.code}: {e.read().decode('utf-8', 'replace')[:200]}"
            if e.code not in (429, 500, 502, 503, 504):
                break
        except Exception as e:                       # сеть, тайм-аут, неожиданный формат
            last = f"{type(e).__name__}: {e}"
        time.sleep(2 * (attempt + 1))
    raise RuntimeError(last)


PRECISE = {
    "admission_date": r"(?:поступил\w*|госпитализ\w+|период лечения)\W{0,4}(?:с\s*)?\d{1,2}[./]\d",
    "discharge_date": r"(?:выписан\w*|выписки)\W{0,4}\d{1,2}[./]\d|\bпо\s+\d{2}\.\d{2}\.\d{4}",
    "bp": r"(?:\bАД\b|давлени\w+)\W{0,4}\d{2,3}\s*(?:/|\\| и | на )",
    "bpm": r"(?:пульс\w*|\bPs\b)\W{0,6}\d{2,3}",
    "rr": r"(?:ЧДД|\bЧД\b|частот\w+ дыхан\w+)[^\n.;]{0,20}\d",
    "ecg_bpm": r"(?:ЭКГ|электрокардиогра\w+)[^\n]{0,120}ЧСС\W{0,4}\d",
    "ecg_rythm": r"(?:ЭКГ|электрокардиогра\w+)[^\n]{0,80}(?:" + ECG_RECORD + ")",
    "rg_pc": r"заст[оя]\w* в (?:л[её]гк|мал)|от[её]к\w* л[её]гк|интерстициальн\w+ от[её]к",
    "smoking": r"кур(?:ит|ил|ящ|ильщ)\w*(?![^.\n]*исключ)|стаж курения",
}
NO_DIGIT = {"smoking", "ecg_rythm", "echo_zone", "rg_pc", "card_trop", "aspirin", "2_aag", "anticoagulant", "ace_ing_sartan", "bb", "statin"}


def hinted(key, text):
    """Есть ли в тексте признак того, что значение поля действительно записано."""
    if key in PRECISE:
        return bool(re.search(PRECISE[key], text, re.I))
    hint = FIELDS[key][0]
    if key in NO_DIGIT:
        return bool(re.search(hint, text, re.I))
    return bool(re.search(r"(?:" + hint + r")[^\n.;]{0,70}\d", text, re.I))


def missing_fields(values, text):
    """Поля, которые правила не заполнили, хотя в тексте есть намёк на значение."""
    out = [k for k in FIELDS if values.get(k) == NU and hinted(k, text)]
    if values.get("ca_fact") != "Y":                 # без выполненной коронарографии дату и сосуды не спрашиваем
        out = [k for k in out if k not in ("ca_date", "ca_lad", "rca")]
    return out


def _squash(s):
    return re.sub(r"\s+", " ", s).strip()


def _accept(key, value, quote, text):
    """Проверка ответа модели: цитата дословно в тексте, значение в нужном формате."""
    if not isinstance(value, str) or not isinstance(quote, str):
        return None
    value, quote = _squash(value), _squash(quote)
    if not value or value == NU or len(quote) < 3 or quote not in _squash(text):
        return None
    pattern = FIELDS[key][3]
    if pattern and not re.fullmatch(pattern, value):
        return None
    if key in NUMERIC_QUOTE:                        # число должно быть в цитате
        if not all(re.search(r"(?<![\d.,])" + re.escape(p) + r"(?![\d])", quote.replace(",", ".")) or
                   re.search(r"(?<![\d.,])" + re.escape(p.replace(".", ",")) + r"(?![\d])", quote) for p in value.split("/")):
            return None
    elif pattern is None and key not in ("aspirin",) and value not in _squash(text):
        return None                                  # текстовое значение должно быть фрагментом эпикриза
    return value, quote


# ---------------------------------------------------------------- защита персональных данных
LABEL = r"(?:Пациент(?:ка)?|Больн(?:ой|ая)|Ф\.?\s?И\.?\s?О\.?|ФИО)"
NAME_WORD = r"[А-ЯЁA-Z][а-яёa-z]+(?:-[А-ЯЁA-Z][а-яёa-z]+)?"
DATE_RX = r"\d{1,2}[./-]\d{1,2}[./-]\d{2,4}"


def patient_names(text):
    """Слова из ФИО пациента в шапке документа."""
    out = []
    for m in re.finditer(LABEL + r"\s*[:—–-]?\s*((?:" + NAME_WORD + r"\s*){1,4})", text):
        out += re.findall(NAME_WORD, m.group(1))
    return [w for w in dict.fromkeys(out) if w.lower() not in ("пациент", "пациентка", "больной", "больная")]


def mask(text, names=()):
    """Заменяет идентификаторы метками. Имена берутся из шапки всего документа, а не только из фрагмента."""
    for w in sorted(names, key=len, reverse=True):
        tail = r"\w{0,3}" if len(w) > 3 else ""
        text = re.sub(r"(?<![А-Яа-яЁёA-Za-z])" + re.escape(w) + tail + r"(?![А-Яа-яЁёA-Za-z])", "[ПАЦИЕНТ]", text)
    text = re.sub(r"(?:\[ПАЦИЕНТ\][\s,]*){2,}", "[ПАЦИЕНТ] ", text)
    rules = [
        (r"((?:д\.\s?р\.|дата рождения|год рождения|родил\w+)\s*[:—–-]?\s*)(?:" + DATE_RX + r"|\d{4})(?:\s*г\.?р?\.?)?", r"\1[ДАТА РОЖДЕНИЯ]"),
        (DATE_RX + r"\s*г\.?\s?р\.", "[ДАТА РОЖДЕНИЯ]"),
        (r"((?:истори\w+ болезни|медицинск\w+ карт\w+|карт\w+|№ истории болезни)\s*(?:№|N|#)?\s*)\d[\d/-]*", r"\1[НОМЕР]"),
        (r"(№\s*)\d{4,}", r"\1[НОМЕР]"),
        (r"((?:[Лл]ечащий врач|[Вв]рач|[Зз]ав\w*\.? отделением|[Кк]ардиолог)\s*[:—–-]\s*)" + NAME_WORD + r"(?:\s+[А-ЯЁ]\.\s?[А-ЯЁ]\.|(?:\s+" + NAME_WORD + r"){1,2})?", r"\1[ВРАЧ]"),
        (NAME_WORD + r"\s+[А-ЯЁ]\.\s?[А-ЯЁ]\.(?![а-яё])", "[ФИО]"),
        (r"((?:[Аа]дрес\w*|[Пп]роживает|[Мм]есто жительства|[Мм]есто работы)(?: регистрации| проживания)?\s*[:—–-]?\s*(?:по адресу\s*:?\s*)?)[^\n;]{3,160}", r"\1[АДРЕС]"),
        (r"(?:\+7|8)[\s(-]*\d{3}[\s)-]*\d{3}[\s-]*\d{2}[\s-]*\d{2}", "[ТЕЛЕФОН]"),
        (r"\b\d{3}-\d{3}-\d{3}[\s-]\d{2}\b", "[СНИЛС]"),
        (r"((?:полис\w*|СНИЛС|паспорт\w*)\s*(?:ОМС|ДМС)?\s*(?:№|N)?\s*[:—–-]?\s*)[\d\s-]{6,}", r"\1[НОМЕР]"),
        (r"[\w.+-]+@[\w-]+\.[\w.-]+", "[ПОЧТА]"),
    ]
    for rx, rep in rules:
        text = re.sub(rx, rep, text)
    return text


def fragment(text, keys, limit=1200):
    """Только те строки эпикриза, где есть намёк на запрошенные поля (с заголовком раздела)."""
    lines = text.split("\n")
    pick = set()
    for k in keys:
        size = 0
        for i, l in enumerate(lines):
            if not re.search(FIELDS[k][0], l, re.I):
                continue
            block = [i]
            if len(l.strip()) < 70 and not re.search(r"\d", l):      # строка-заголовок: берём абзац под ней
                j = i + 1
                while j < len(lines) and lines[j].strip() and j - i <= 3:
                    block.append(j)
                    j += 1
            size += sum(len(lines[b]) for b in block)
            pick.update(block)
            if size > limit:
                break
    out = []
    for i in sorted(pick):
        l = lines[i].strip()
        if len(l) > limit:                                            # документ одной строкой: предложения с намёком
            sents = re.split(r"(?<=[.!?;])\s+(?=[А-ЯЁA-Z\d])", l)
            hit = [n for n, s in enumerate(sents) if any(re.search(FIELDS[k][0], s, re.I) for k in keys)]
            keep = sorted({m for n in hit for m in (n - 1, n, n + 1) if 0 <= m < len(sents)})
            l = " ".join(sents[m] for m in keep)[:limit * 3]
        if l:
            out.append(l)
    return "\n".join(out)


def fill(values, evidence, text, call=yandex_call, review=()):
    """Дозаполняет пустые поля и перепроверяет поля из `review` (отмеченные самопроверкой).

    В модель уходит не весь эпикриз, а только строки с намёком на эти поля, с замаскированными
    идентификаторами. Возвращает словарь: asked, filled, replaced, error, sent (что было отправлено)."""
    ask = missing_fields(values, text)
    recheck = [k for k in review if k in FIELDS and k not in ask and values.get(k) not in (None, NU)]
    res = {"asked": len(ask) + len(recheck), "filled": 0, "replaced": 0, "error": None, "sent": ""}
    if not ask and not recheck:
        return res
    names = patient_names(text)
    part = mask(fragment(text, ask + recheck), names)
    spec = "\n".join(f"- {k}: {FIELDS[k][1]}; формат: {FIELDS[k][2]}" for k in ask + recheck)
    user = f"Поля:\n{spec}\n\nФрагменты эпикриза:\n{part}"
    res["sent"] = user
    if not part.strip():
        return res
    try:
        raw = call(SYSTEM, user)
        m = re.search(r"\{.*\}", raw, re.S)
        answer = json.loads(m.group(0)) if m else {}
    except Exception as e:
        res["error"] = str(e)
        return res
    for k in ask + recheck:
        item = answer.get(k) if isinstance(answer, dict) else None
        if not isinstance(item, dict):
            continue
        ok = _accept(k, item.get("value"), item.get("quote"), text)
        if not ok or ok[0] == values.get(k):
            continue
        if k in recheck:
            evidence[k] = ok[1] + f" [значение заменено по ответу YandexGPT; было: {values[k]}]"
            res["replaced"] += 1
        else:
            evidence[k] = ok[1] + " [значение получено от YandexGPT]"
            res["filled"] += 1
        values[k] = ok[0]
    return res


if __name__ == "__main__":                           # проверка связи: python llm.py
    if not configured():
        raise SystemExit("Не заданы YC_API_KEY и YC_FOLDER_ID (переменные окружения или файл .env)")
    try:
        print("Ответ модели:", yandex_call("Отвечай одним словом.", "Напиши слово «работает»."))
        print("Связь с YandexGPT есть.")
    except Exception as e:
        raise SystemExit(f"Запрос не прошёл: {e}")
