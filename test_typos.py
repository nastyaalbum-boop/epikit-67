"""Проверка запасного шага: в ключевые слова вносятся случайные опечатки,
результат сравнивается с результатом по исходному тексту.
Запуск: python test_typos.py"""
import glob, random, re
from extract import extract, _extract
from typo import STEMS, fix

random.seed(7)
ABC = "абвгдежзиклмнопрстуфхцчшщыьэюя"


def damage(word):
    i = random.randrange(1, len(word) - 1)
    kind = random.choice("drst")
    if kind == "d":
        return word[:i] + word[i + 1:]                          # пропуск буквы
    if kind == "r":
        return word[:i] + word[i] + word[i:]                    # удвоение
    if kind == "s":
        return word[:i] + random.choice(ABC) + word[i + 1:]     # замена
    return word[:i - 1] + word[i] + word[i - 1] + word[i + 1:]  # перестановка


def spoil(text, share):
    def repl(m):
        w = m.group(0)
        low = w.lower()
        stem = next((s for s in STEMS if low.startswith(s)), None)
        if not stem or random.random() > share:
            return w
        return damage(w[:len(stem)]) + w[len(stem):]
    return re.sub(r"[А-Яа-яЁё]{6,}", repl, text)


for share, label in ((0.1, "10 % ключевых слов с опечаткой"), (1.0, "все ключевые слова с опечаткой")):
    total = plain = fallback = 0
    for p in sorted(glob.glob("documents/*.md")):
        src = open(p, encoding="utf-8").read()
        ref = _extract(src)[0]
        bad = spoil(src, share)
        a, b = _extract(bad)[0], extract(bad)[0]
        for k in ref:
            total += 1
            plain += a[k] == ref[k]
            fallback += b[k] == ref[k]
    print(f"{label}: без исправления {plain / total:.1%}, с исправлением {fallback / total:.1%}")

# ложные срабатывания: исправлений в исходных текстах быть не должно
changed = sum(fix(open(p, encoding="utf-8").read()) != open(p, encoding="utf-8").read() for p in glob.glob("documents/*.md"))
print("исходных документов, изменённых исправлением:", changed)
