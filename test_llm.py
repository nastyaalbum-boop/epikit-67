"""Проверка режима --llm без обращения к сети: модель заменена заглушкой.
Запуск: python test_llm.py"""
import json
from extract import extract
from validate import check
import llm

DOC = ("Кардиологическое отделение. История болезни № 700999.\n"
       "Пациент: Иван Петрович Сидоров, д.р. 12.03.1950, возраст 71 год. Адрес: г. Москва, ул. Лесная, д. 5.\n"
       "Поступил 01.02.2021. Выписан 09.02.2021.\n"
       "Основной диагноз: ИБС. Острый инфаркт миокарда нижней стенки с подъёмом ST. Код МКБ-10 I21.1.\n"
       "Объективно: тоны сердца ритмичные, пульс 80 в минуту, АД 130/80 мм рт. ст.\n"
       "Фракция выброса ЛЖ по Симпсону оценена в 41 процент.\n"
       "Креатинин: показатель при первом определении в стационаре составил 104.\n"
       "Лечащий врач: Кузнецова А.В. Телефон отделения +7 (495) 123-45-67.\n")
ok = total = 0
sent = []


def check_(name, cond):
    global ok, total
    total += 1
    ok += bool(cond)
    print(("ок   " if cond else "СБОЙ ") + name)


def stub(answer):
    def call(system, user):
        sent.append(user)
        return answer if isinstance(answer, str) else json.dumps(answer, ensure_ascii=False)
    return call


v, e = extract(DOC)
check_("правила не нашли ФВ и креатинин", v["echo_ef"] == llm.NU and v["crea"] == llm.NU)
ask = llm.missing_fields(v, DOC)
check_("модель спрашивают только о пустых полях с намёком в тексте", "echo_ef" in ask and "crea" in ask and "bp" not in ask and "ldl" not in ask)

good = {"echo_ef": {"value": "41", "quote": "Фракция выброса ЛЖ по Симпсону оценена в 41 процент"},
        "crea": {"value": "104", "quote": "показатель при первом определении в стационаре составил 104"}}
v1, e1 = dict(v), dict(e)
r = llm.fill(v1, e1, DOC, call=stub(good))
check_("верный ответ с цитатой принят", v1["echo_ef"] == "41" and v1["crea"] == "104" and r["filled"] == 2 and "YandexGPT" in e1["crea"])

body = sent[-1].split("Фрагменты эпикриза:")[1]
check_("в модель уходит фрагмент, а не весь документ", "Поступил" not in body and "пульс" not in body and len(body) < len(DOC) / 2)
check_("в запросе нет ФИО, даты рождения, номеров, врача и телефона",
       not any(x in sent[-1] for x in ("Сидоров", "Иван", "Петрович", "12.03.1950", "700999", "Кузнецова", "123-45-67", "Лесная")))

whole = llm.mask(DOC, llm.patient_names(DOC))
check_("маскировка всего документа убирает все идентификаторы",
       not any(x in whole for x in ("Сидоров", "Иван", "Петрович", "12.03.1950", "700999", "Кузнецова", "123-45-67", "Лесная"))
       and "АД 130/80" in whole and "01.02.2021" in whole)

fake = {"echo_ef": {"value": "55", "quote": "ФВ ЛЖ 55%"},
        "crea": {"value": "99", "quote": "показатель при первом определении в стационаре составил 104"}}
v2, e2 = dict(v), dict(e)
llm.fill(v2, e2, DOC, call=stub(fake))
check_("выдуманная цитата отклонена", v2["echo_ef"] == llm.NU)
check_("значение, которого нет в цитате, отклонено", v2["crea"] == llm.NU)

v3, e3 = dict(v), dict(e)
check_("ответ не в формате JSON не ломает обработку", llm.fill(v3, e3, DOC, call=stub("Извините, я не могу помочь."))["filled"] == 0 and v3 == v)


def down(system, user):
    raise RuntimeError("HTTP 503")


v4, e4 = dict(v), dict(e)
r = llm.fill(v4, e4, DOC, call=down)
check_("сбой сети: остаётся результат правил, ошибка возвращается", v4 == v and r["error"])

# перепроверка поля, отмеченного самопроверкой
BAD = ("Поступил 14.12.2021. Выписан 24.12.2021. Код МКБ-10 I21.4.\n"
       "Основной диагноз: ИБС. Острый инфаркт миокарда без подъёма ST.\n"
       "АД 130/80 мм рт. ст., пульс 80 в минуту. ЭКГ от 14.12.2021: синусовый ритм, ЧСС 80 уд/мин. Тропониновый тест положительный.\n"
       "Рентгенограмма ОГК от 14.12.2021: Данных за венозный застой в лёгких не получено.\n")
vb, eb = extract(BAD)
vb["rg_date"] = "11.09.1845"                                    # имитируем ошибку правила
flat = {k: str(x) for k, x in vb.items()}
flagged = [m.partition(": ")[0] for m in check(flat, BAD)]
check_("самопроверка отметила неверную дату рентгена", "rg_date" in flagged)
r = llm.fill(vb, eb, BAD, call=stub({"rg_date": {"value": "14.12.2021", "quote": "Рентгенограмма ОГК от 14.12.2021"}}), review=flagged)
check_("модель заменила отмеченное значение, прежнее сохранено в пометке", vb["rg_date"] == "14.12.2021" and r["replaced"] == 1 and "было: 11.09.1845" in eb["rg_date"])
vb2, eb2 = extract(BAD)
vb2["rg_date"] = "11.09.1845"
llm.fill(vb2, eb2, BAD, call=stub({"rg_date": {"value": "не указано", "quote": ""}}), review=flagged)
check_("если модель не подтвердила замену, значение остаётся и уходит на ручную проверку", vb2["rg_date"] == "11.09.1845")

full = open("documents/train-0003.md", encoding="utf-8").read()
vf, ef = extract(full)
n = len(sent)
llm.fill(vf, ef, full, call=stub("{}"))
check_("на обычном документе модель не вызывается", len(sent) == n)
print(f"пройдено {ok} из {total}")
