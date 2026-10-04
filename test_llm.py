"""Проверка режима --llm без обращения к сети: модель заменена заглушкой.
Запуск: python test_llm.py"""
import json
from extract import extract
import llm

DOC = ("Поступил 01.02.2021. Выписан 09.02.2021.\n"
       "Основной диагноз: ИБС. Острый инфаркт миокарда нижней стенки с подъёмом ST. Код МКБ-10 I21.1.\n"
       "Объективно: тоны сердца ритмичные, пульс 80 в минуту, АД 130/80 мм рт. ст.\n"
       "Фракция выброса ЛЖ по Симпсону оценена в 41 процент.\n"
       "Креатинин: показатель при первом определении в стационаре составил 104.\n")
ok = 0
total = 0


def check(name, cond):
    global ok, total
    total += 1
    ok += bool(cond)
    print(("ок   " if cond else "СБОЙ ") + name)


v, e = extract(DOC)
check("правила не нашли ФВ и креатинин", v["echo_ef"] == llm.NU and v["crea"] == llm.NU)
ask = llm.missing_fields(v, DOC)
check("модель спрашивают только о пустых полях с намёком в тексте", "echo_ef" in ask and "crea" in ask and "bp" not in ask and "ldl" not in ask)

good = lambda s, u: json.dumps({"echo_ef": {"value": "41", "quote": "Фракция выброса ЛЖ по Симпсону оценена в 41 процент"},
                                "crea": {"value": "104", "quote": "показатель при первом определении в стационаре составил 104"}}, ensure_ascii=False)
v1, e1 = dict(v), dict(e)
asked, got, err = llm.fill(v1, e1, DOC, call=good)
check("верный ответ с цитатой принят", v1["echo_ef"] == "41" and v1["crea"] == "104" and "YandexGPT" in e1["crea"])

fake = lambda s, u: json.dumps({"echo_ef": {"value": "55", "quote": "ФВ ЛЖ 55%"},
                                "crea": {"value": "99", "quote": "показатель при первом определении в стационаре составил 104"}}, ensure_ascii=False)
v2, e2 = dict(v), dict(e)
llm.fill(v2, e2, DOC, call=fake)
check("выдуманная цитата отклонена", v2["echo_ef"] == llm.NU)
check("значение, которого нет в цитате, отклонено", v2["crea"] == llm.NU)

junk = lambda s, u: "Извините, я не могу помочь."
v3, e3 = dict(v), dict(e)
check("ответ не в формате JSON не ломает обработку", llm.fill(v3, e3, DOC, call=junk)[1] == 0 and v3 == v)


def down(s, u):
    raise RuntimeError("HTTP 503")


v4, e4 = dict(v), dict(e)
asked, got, err = llm.fill(v4, e4, DOC, call=down)
check("сбой сети: остаётся результат правил, ошибка возвращается", v4 == v and err)

full = open("documents/train-0003.md", encoding="utf-8").read()
vf, ef = extract(full)
calls = []
llm.fill(vf, ef, full, call=lambda s, u: calls.append(1) or "{}")
check("на обычном документе модель спрашивают только о полях, которых нет в тексте", len(calls) <= 1)
print("полей с намёком без значения в train-0003:", llm.missing_fields(extract(full)[0], full))
print(f"пройдено {ok} из {total}")
