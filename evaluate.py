"""Сравнение result/ с эталоном gold/ и отчёт о заполненности."""
import json, sys
from pathlib import Path
from collections import Counter
NU = "не указано"
def flat(p): return {k: v for g in json.loads(p.read_text(encoding="utf-8")).values() for k, v in g.items()}
ok = tot = 0; bad = []
for g in sorted(Path("gold").glob("*.json")):
    a, b = flat(g), flat(Path("result") / g.name)
    for k in a:
        tot += 1
        x, y = a[k], b[k]
        same = x == y or (k == "rg_pc" and (y in x or x in y) and (x == NU) == (y == NU))
        try: same = same or float(x) == float(y)
        except ValueError: pass
        if same: ok += 1
        else: bad.append((g.stem, k, x, y))
print(f"совпало {ok}/{tot} = {ok/tot:.1%}")
for b in bad: print("  ", *b, sep=" | ")
fill = Counter(); n = 0
for p in Path("result").glob("*.json"):
    n += 1
    for k, v in flat(p).items(): fill[k] += v != NU
print("\nзаполнено из", n, ":", ", ".join(f"{k}={v}" for k, v in fill.items()))
