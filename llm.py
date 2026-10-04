"""Запасной путь через YandexGPT (включается флагом --llm).

Модель вызывается только для полей, которые правила оставили пустыми, хотя в тексте есть
намёк на значение. Ответ принимается, только если модель привела цитату, которая дословно
есть в исходном тексте, и значение проходит проверку формата. Иначе остаётся «не указано».

Настройка — переменные окружения или файл .env рядом с программой:
    YC_API_KEY    — API-ключ сервисного аккаунта
    YC_FOLDER_ID  — идентификатор каталога
    YC_MODEL      — необязательно, по умолчанию yandexgpt
"""
import json, os, re, time, urllib.error, urllib.request
from pathlib import Path

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
    "rg_date": (r"рентген|\bRg\b|ОГК", "дата рентгенографии грудной клетки", "ДД.ММ.ГГГГ", r"\d{2}\.\d{2}\.\d{4}"),
    "rg_pc": (r"рентген|\bRg\b|ОГК", "фраза заключения рентгена о застое или отёке лёгких", "фрагмент текста", None),
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
          "верни {\"value\": \"не указано\", \"quote\": \"\"}. Числа — без единиц, с десятичной точкой.")


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


def missing_fields(values, text):
    """Поля, которые правила не заполнили, хотя в тексте есть намёк на значение."""
    out = [k for k, (hint, *_) in FIELDS.items() if values.get(k) == NU and re.search(hint, text, re.I)]
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


def fill(values, evidence, text, call=yandex_call):
    """Дозаполняет пустые поля. Возвращает (сколько полей спрошено, сколько принято, ошибка или None)."""
    ask = missing_fields(values, text)
    if not ask:
        return 0, 0, None
    spec = "\n".join(f"- {k}: {FIELDS[k][1]}; формат: {FIELDS[k][2]}" for k in ask)
    user = f"Поля:\n{spec}\n\nЭпикриз:\n{text}"
    try:
        raw = call(SYSTEM, user)
        m = re.search(r"\{.*\}", raw, re.S)
        answer = json.loads(m.group(0)) if m else {}
    except Exception as e:
        return len(ask), 0, str(e)
    done = 0
    for k in ask:
        item = answer.get(k) if isinstance(answer, dict) else None
        if not isinstance(item, dict):
            continue
        ok = _accept(k, item.get("value"), item.get("quote"), text)
        if ok:
            values[k], evidence[k] = ok[0], ok[1] + " [значение получено от YandexGPT]"
            done += 1
    return len(ask), done, None


if __name__ == "__main__":                           # проверка связи: python llm.py
    if not configured():
        raise SystemExit("Не заданы YC_API_KEY и YC_FOLDER_ID (переменные окружения или файл .env)")
    try:
        print("Ответ модели:", yandex_call("Отвечай одним словом.", "Напиши слово «работает»."))
        print("Связь с YandexGPT есть.")
    except Exception as e:
        raise SystemExit(f"Запрос не прошёл: {e}")
