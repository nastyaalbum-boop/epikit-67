"""Пакетная обработка эпикризов.

    python run.py --input documents --output result

Для каждого входного файла создаётся JSON с тем же базовым именем.
Ошибка в одном документе не останавливает обработку остальных.
"""
import argparse, csv, json, sys, time
from pathlib import Path
from extract import extract, NU
from validate import check
import llm

HERE = Path(__file__).parent
ENCODINGS = ("utf-8-sig", "utf-16", "cp1251")


def decode_bytes(raw):
    """Байты файла -> текст с автоопределением кодировки."""
    for enc in ENCODINGS:
        try:
            text = raw.decode(enc)
        except UnicodeError:
            continue
        if enc == "utf-16" and not raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
            continue
        return text
    return raw.decode("utf-8", errors="replace")


def read_text(path):
    return decode_bytes(path.read_bytes())


def main():
    ap = argparse.ArgumentParser(description="Извлечение 50 признаков из выписных эпикризов")
    ap.add_argument("--input", default="documents", help="папка с эпикризами (.md, .txt)")
    ap.add_argument("--output", default="result", help="папка для JSON")
    ap.add_argument("--evidence", default="evidence", help="папка для JSON с цитатами")
    ap.add_argument("--report", default="review_report.csv", help="список анкет для ручной проверки")
    ap.add_argument("--llm", action="store_true", help="дозаполнять пустые поля через YandexGPT (нужны YC_API_KEY и YC_FOLDER_ID)")
    a = ap.parse_args()
    if a.llm and not llm.configured():
        sys.exit("Для --llm задайте YC_API_KEY и YC_FOLDER_ID в переменных окружения или в файле .env")

    tpl = json.loads((HERE / "template.json").read_text(encoding="utf-8"))
    src = Path(a.input)
    if not src.is_dir():
        sys.exit(f"Папка не найдена: {src}")
    files = sorted(p for p in src.rglob("*") if p.is_file() and p.suffix.lower() in (".md", ".txt"))
    if not files:
        sys.exit(f"В папке {src} нет файлов .md или .txt")
    out, evd = Path(a.output), Path(a.evidence)
    out.mkdir(parents=True, exist_ok=True)
    evd.mkdir(parents=True, exist_ok=True)

    t0, rows, failed = time.time(), [], 0
    stats = {"calls": 0, "asked": 0, "filled": 0, "errors": 0, "seconds": 0.0}
    for p in files:
        try:
            vals, ev = extract(read_text(p))
        except Exception as e:                      # документ не должен ронять пакет
            vals, ev, failed = {}, {}, failed + 1
            rows.append((p.stem, "документ", f"ошибка обработки: {e}"))
        if a.llm and vals:
            t1 = time.time()
            asked, got, err = llm.fill(vals, ev, read_text(p))
            stats["seconds"] += time.time() - t1
            stats["calls"] += bool(asked); stats["asked"] += asked; stats["filled"] += got
            if err:
                stats["errors"] += 1
                rows.append((p.stem, "документ", f"YandexGPT недоступен, оставлен результат правил: {err[:150]}"))
        res = {g: {k: str(vals.get(k) or NU) for k in ks} for g, ks in tpl.items()}
        evi = {g: {k: {"value": res[g][k], "evidence": ev.get(k, "")} for k in ks} for g, ks in tpl.items()}
        (out / f"{p.stem}.json").write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
        (evd / f"{p.stem}.json").write_text(json.dumps(evi, ensure_ascii=False, indent=2), encoding="utf-8")
        if vals:
            flat = {k: v for g in res.values() for k, v in g.items()}
            for msg in check(flat):
                field, _, text = msg.partition(": ")
                rows.append((p.stem, field, text))

    with open(a.report, "w", newline="", encoding="utf-8-sig") as f:
        wr = csv.writer(f, delimiter=";")
        wr.writerow(["документ", "поле", "замечание"])
        wr.writerows(rows)
    flagged = len({r[0] for r in rows})
    total = time.time() - t0
    rules = total - stats["seconds"]
    print(f"обработано {len(files)} документов за {total:.2f} с; "
          f"ошибок обработки: {failed}; на ручную проверку: {flagged} (см. {a.report})")
    if a.llm:
        print(f"время: правила {rules:.2f} с, YandexGPT {stats['seconds']:.2f} с")
        print(f"YandexGPT: обращений {stats['calls']}, запрошено полей {stats['asked']}, "
              f"принято {stats['filled']}, сбоев {stats['errors']}")


if __name__ == "__main__":
    main()
