"""Проверка устойчивости: неудобные файлы не должны ломать пакет и структуру JSON.
Запуск: python test_robustness.py"""
import json, subprocess, sys, tempfile
from pathlib import Path

here = Path(__file__).parent
sample = sorted((here / "documents").glob("*.md"))[0]
src = sample.read_text(encoding="utf-8")
tpl = json.loads((here / "template.json").read_text(encoding="utf-8"))

with tempfile.TemporaryDirectory() as tmp:
    d = Path(tmp) / "in"; (d / "sub").mkdir(parents=True)
    same = {  # должны дать тот же результат, что и исходный файл
        "bom.md": b"\xef\xbb\xbf" + src.encode("utf-8"),
        "cp1251.md": src.encode("cp1251", errors="replace"),
        "utf16.md": src.encode("utf-16"),
        "crlf.md": src.replace("\n", "\r\n").encode("utf-8"),
        "oneline.md": src.replace("\n", " ").encode("utf-8"),
        "noheaders.md": "\n".join(l for l in src.split("\n") if not l.strip().endswith(":")).encode("utf-8"),
        "upper.TXT": src.encode("utf-8"),
        "sub/nested.md": src.encode("utf-8"),
        "huge.md": (src * 200).encode("utf-8"),
    }
    other = {"empty.md": b"", "spaces.md": b"  \n\n", "garbage.md": bytes(range(256)) * 20,
             "english.md": b"Patient admitted with chest pain."}
    for name, data in {**same, **other, "original.md": src.encode("utf-8")}.items():
        (d / name).write_bytes(data)
    out = Path(tmp) / "out"
    p = subprocess.run([sys.executable, str(here / "run.py"), "--input", str(d), "--output", str(out),
                        "--evidence", str(Path(tmp) / "ev"), "--report", str(Path(tmp) / "rep.csv")],
                       capture_output=True, text=True)
    assert p.returncode == 0, p.stderr
    ref = json.loads((out / "original.json").read_text(encoding="utf-8"))
    bad = 0
    for name in list(same) + list(other):
        j = json.loads((out / (Path(name).stem + ".json")).read_text(encoding="utf-8"))
        ok = list(j) == list(tpl) and all(list(j[g]) == list(tpl[g]) and all(isinstance(v, str) and v for v in j[g].values()) for g in tpl)
        if name in same and j != ref:
            ok = False
        bad += not ok
        print(("ок   " if ok else "СБОЙ ") + name)
    print(f"пройдено {len(same) + len(other) - bad} из {len(same) + len(other)}")
