"""Пакетная обработка эпикризов.

    python run.py --input documents --output result

Для каждого входного файла создаётся JSON с тем же базовым именем.
Ошибка в одном документе не останавливает обработку остальных.
"""
import argparse, csv, json, sys, time
from pathlib import Path
from extract import extract, NU
from validate import check, absent
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
    gap_rows, incomplete = [], 0
    stats = {"calls": 0, "asked": 0, "filled": 0, "replaced": 0, "errors": 0, "seconds": 0.0}
    for p in files:
        text = ""
        try:
            text = read_text(p)
            vals, ev = extract(text)
        except Exception as e:                      # документ не должен ронять пакет
            vals, ev, failed = {}, {}, failed + 1
            rows.append((p.stem, "документ", f"ошибка обработки: {e}"))
        if a.llm and vals:
            t1 = time.time()
            first = {k: str(vals.get(k) or NU) for g in tpl.values() for k in g}
            out_llm = llm.fill(vals, ev, text, review=[m.partition(": ")[0] for m in check(first, text)])
            stats["seconds"] += time.time() - t1
            stats["calls"] += bool(out_llm["sent"]); stats["asked"] += out_llm["asked"]
            stats["filled"] += out_llm["filled"]; stats["replaced"] += out_llm["replaced"]
            if out_llm["sent"]:
                log = evd / "llm_requests"
                log.mkdir(exist_ok=True)
                (log / f"{p.stem}.txt").write_text(out_llm["sent"], encoding="utf-8")
            if out_llm["error"]:
                stats["errors"] += 1
                rows.append((p.stem, "документ", f"YandexGPT недоступен, оставлен результат правил: {out_llm['error'][:150]}"))
        res = {g: {k: str(vals.get(k) or NU) for k in ks} for g, ks in tpl.items()}
        evi = {g: {k: {"value": res[g][k], "evidence": ev.get(k, "")} for k in ks} for g, ks in tpl.items()}
        (out / f"{p.stem}.json").write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
        (evd / f"{p.stem}.json").write_text(json.dumps(evi, ensure_ascii=False, indent=2), encoding="utf-8")
        if vals:
            flat = {k: v for g in res.values() for k, v in g.items()}
            for msg in check(flat, text):
                field, _, note = msg.partition(": ")
                rows.append((p.stem, field, note))
            gaps = absent(flat, text)
            if gaps:
                incomplete += 1
                gap_rows.append((p.stem, "; ".join(gaps)))

    with open(a.report, "w", newline="", encoding="utf-8-sig") as f:
        wr = csv.writer(f, delimiter=";")
        wr.writerow(["документ", "поле", "замечание"])
        wr.writerows(rows)
        for name, gaps in gap_rows:                  # справочно: этих данных нет в самом документе
            wr.writerow([name, "нет в документе", gaps])
    flagged = len({r[0] for r in rows})
    total = time.time() - t0
    rules = total - stats["seconds"]
    print(f"обработано {len(files)} документов за {total:.2f} с; "
          f"ошибок обработки: {failed}; на ручную проверку: {flagged} (см. {a.report})")
    if incomplete:
        print(f"документов, где части ключевых данных нет в самом тексте: {incomplete}")
    if a.llm:
        print(f"время: правила {rules:.2f} с, YandexGPT {stats['seconds']:.2f} с")
        print(f"YandexGPT: обращений {stats['calls']}, запрошено полей {stats['asked']}, "
              f"дозаполнено {stats['filled']}, заменено {stats['replaced']}, сбоев {stats['errors']}")
        print(f"что именно отправлено в модель: {evd / 'llm_requests'}")


if __name__ == "__main__":
    main()
