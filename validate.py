"""Самопроверка анкеты: возвращает список замечаний «проверить вручную»."""
from datetime import datetime

NU = "не указано"
RANGES = {  # поле: (минимум, максимум, название)
    "bpm": (30, 220, "пульс"), "ecg_bpm": (30, 250, "ЧСС на ЭКГ"), "rr": (8, 50, "ЧДД"),
    "spo2": (50, 100, "сатурация"), "height": (120, 220, "рост"), "weight": (30, 250, "масса тела"),
    "bmi": (12, 70, "ИМТ"), "echo_ef": (10, 85, "фракция выброса"), "echo_lvd": (30, 90, "КДР ЛЖ"),
    "echo_lvd_2": (20, 80, "размер ЛП"), "crea": (20, 1500, "креатинин"), "glu": (1, 40, "глюкоза"),
    "hb": (40, 220, "гемоглобин"), "ldl": (0.3, 12, "ЛПНП"), "leucocytes": (1, 60, "лейкоциты"),
    "thrombocytes": (20, 1000, "тромбоциты"), "tot_chol": (1, 15, "общий холестерин"),
}


def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _d(v):
    try:
        return datetime.strptime(v, "%d.%m.%Y")
    except (TypeError, ValueError):
        return None


def check(v):
    w = []
    for k in ("admission_date", "discharge_date", "diagnosis_icd", "bp"):
        if v.get(k, NU) == NU:
            w.append(f"{k}: ключевое поле не найдено")
    adm, dis = _d(v.get("admission_date")), _d(v.get("discharge_date"))
    if adm and dis:
        if dis < adm:
            w.append("discharge_date: выписка раньше поступления")
        elif (dis - adm).days > 90:
            w.append("discharge_date: госпитализация дольше 90 дней")
    for k, name in (("rg_date", "рентгена"), ("ca_date", "коронарографии")):
        d = _d(v.get(k))
        if v.get(k, NU) != NU and not d:
            w.append(f"{k}: дата {name} не распознана")
        elif d and adm and dis and not (adm <= d <= dis):
            w.append(f"{k}: дата {name} вне периода госпитализации")
    for k, (lo, hi, name) in RANGES.items():
        x = _f(v.get(k))
        if v.get(k, NU) != NU and (x is None or not lo <= x <= hi):
            w.append(f"{k}: {name} {v[k]} вне допустимых пределов {lo}–{hi}")
    bp = v.get("bp", NU)
    if bp != NU:
        try:
            s, d = (int(x) for x in bp.split("/"))
            if not (50 <= s <= 280 and 20 <= d <= 160 and s > d):
                w.append(f"bp: давление {bp} выглядит неправдоподобно")
        except ValueError:
            w.append(f"bp: давление {bp} не в формате верхнее/нижнее")
    h, m, b = _f(v.get("height")), _f(v.get("weight")), _f(v.get("bmi"))
    if h and m and b and abs(m / (h / 100) ** 2 - b) > 1.5:
        w.append(f"bmi: ИМТ {v['bmi']} не сходится с ростом {v['height']} и весом {v['weight']}")
    t, el, icd = v.get("type_acs"), v.get("ecg_elevation"), v.get("diagnosis_icd", "")
    if t == "STEMI" and el == "0":
        w.append("ecg_elevation: в диагнозе подъём ST, на ЭКГ элевация не найдена")
    if t in ("NSTEMI", "NA") and el == "1":
        w.append("ecg_elevation: на ЭКГ элевация ST, в диагнозе её нет")
    if (t == "STEMI" and icd in ("I21.4",)) or (t != "NA" and icd.startswith("I20")) or (t == "NA" and icd.startswith("I21")):
        w.append(f"type_acs: тип {t} не согласуется с кодом МКБ {icd}")
    loc = {"I21.0": "A", "I21.1": "I", "I21.2": "L"}.get(icd)
    if loc and v.get("mi_localisation") != loc:
        w.append(f"mi_localisation: {v.get('mi_localisation')} не согласуется с кодом МКБ {icd}")
    fact, lad, rca = v.get("ca_fact"), v.get("ca_lad", NU), v.get("rca", NU)
    if fact == "Y" and lad == NU and rca == NU:
        w.append("ca_lad: коронарография выполнена, но состояние сосудов не найдено")
    if fact == "Y" and v.get("ca_date", NU) == NU:
        w.append("ca_date: коронарография выполнена, но дата не найдена")
    if fact != "Y" and (lad != NU or rca != NU):
        w.append("ca_fact: сосуды описаны, а факт коронарографии не «Y»")
    if v.get("ecg_rythm", NU) == NU:
        w.append("ecg_rythm: запись ЭКГ не найдена")
    if v.get("card_trop", NU) == NU:
        w.append("card_trop: результат тропонина не найден")
    return w
