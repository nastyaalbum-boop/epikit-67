"""Веб-интерфейс для пакетной обработки эпикризов.

    python app.py            # откроется http://127.0.0.1:8000

Работает на стандартной библиотеке Python. Сервер слушает только этот компьютер.
"""
import argparse, base64, csv, io, json, threading, time, uuid, webbrowser, zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import llm
from extract import NU, extract
from run import decode_bytes
from validate import check

HERE = Path(__file__).parent
TPL = json.loads((HERE / "template.json").read_text(encoding="utf-8"))
KEYS = [k for ks in TPL.values() for k in ks]
SUFFIXES = (".md", ".txt")
JOBS = {}
LOCK = threading.Lock()


class Job:
    def __init__(self):
        self.id = uuid.uuid4().hex[:12]
        self.files = {}            # имя -> байты
        self.order = []
        self.docs = {}             # имя -> результат
        self.rows = []
        self.state = "uploading"   # uploading | running | done | stopped
        self.llm = False
        self.stop = False
        self.started = self.finished = None
        self.llm_seconds = 0.0
        self.stats = {"llm_calls": 0, "llm_asked": 0, "llm_filled": 0, "llm_errors": 0, "errors": 0}
        self.fill = {k: 0 for k in KEYS}
        self.skipped = 0

    def add(self, name, raw):
        """Добавляет файл; архив .zip распаковывается."""
        if name.lower().endswith(".zip"):
            try:
                with zipfile.ZipFile(io.BytesIO(raw)) as z:
                    for info in z.infolist():
                        inner = info.filename
                        try:                                   # имена с кириллицей в архивах без флага UTF-8
                            if not info.flag_bits & 0x800:
                                inner = inner.encode("cp437").decode("cp866")
                        except UnicodeError:
                            pass
                        if info.is_dir() or "__MACOSX" in inner or Path(inner).name.startswith("."):
                            continue
                        if inner.lower().endswith(SUFFIXES):
                            self._put(inner, z.read(info))
                        else:
                            self.skipped += 1
            except zipfile.BadZipFile:
                self.skipped += 1
        elif name.lower().endswith(SUFFIXES):
            self._put(name, raw)
        else:
            self.skipped += 1

    def _put(self, name, raw):
        stem = Path(name.replace("\\", "/")).stem
        base, n = stem, 2
        while stem in self.files:                              # одинаковые имена в разных папках
            stem, n = f"{base}-{n}", n + 1
        self.files[stem] = raw
        self.order.append(stem)

    def run(self):
        self.state, self.started = "running", time.time()
        self.order.sort()
        for name in self.order:
            if self.stop:
                self.state = "stopped"
                break
            doc = {"name": name, "error": None, "warnings": [], "llm_fields": []}
            try:
                text = decode_bytes(self.files[name])
                vals, ev = extract(text)
                if self.llm:
                    before = dict(vals)
                    t = time.time()
                    asked, got, err = llm.fill(vals, ev, text)
                    self.llm_seconds += time.time() - t
                    self.stats["llm_calls"] += bool(asked)
                    self.stats["llm_asked"] += asked
                    self.stats["llm_filled"] += got
                    if err:
                        self.stats["llm_errors"] += 1
                        doc["warnings"].append("YandexGPT недоступен, оставлен результат локального режима: " + err[:150])
                    doc["llm_fields"] = [k for k in vals if vals[k] != before.get(k)]
            except Exception as e:                             # документ не должен ронять пакет
                text, vals, ev = "", {}, {}
                doc["error"] = f"{type(e).__name__}: {e}"
                self.stats["errors"] += 1
            flat = {k: str(vals.get(k) or NU) for k in KEYS}
            if vals:
                doc["warnings"] += check(flat)
            doc.update(text=text, values=flat, evidence={k: ev.get(k, "") for k in KEYS})
            for k, v in flat.items():
                self.fill[k] += v != NU
            self.docs[name] = doc
            notes = " ".join(doc["evidence"].values())
            self.rows.append({"name": name, "filled": sum(v != NU for v in flat.values()),
                              "warnings": len(doc["warnings"]), "error": doc["error"],
                              "llm": len(doc["llm_fields"]), "typo": "исправлена опечатка" in notes})
            self.files[name] = b""                             # исходные байты больше не нужны
        else:
            self.state = "done"
        self.finished = time.time()

    def summary(self, since=0):
        now = self.finished or time.time()
        total = (now - self.started) if self.started else 0
        done = len(self.rows)
        return {"id": self.id, "state": self.state, "llm": self.llm, "total": len(self.order), "done": done,
                "skipped": self.skipped, "flagged": sum(1 for r in self.rows if r["warnings"] or r["error"]),
                "seconds": round(total, 2), "rules_seconds": round(max(total - self.llm_seconds, 0), 2),
                "llm_seconds": round(self.llm_seconds, 2), **self.stats, "fill": self.fill,
                "rows": self.rows[since:]}

    def nested(self, name, with_evidence=False):
        d = self.docs[name]
        if with_evidence:
            return {g: {k: {"value": d["values"][k], "evidence": d["evidence"][k]} for k in ks} for g, ks in TPL.items()}
        return {g: {k: d["values"][k] for k in ks} for g, ks in TPL.items()}

    def archive(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            report = io.StringIO()
            wr = csv.writer(report, delimiter=";")
            wr.writerow(["документ", "поле", "замечание"])
            for name in sorted(self.docs):
                dump = lambda o: json.dumps(o, ensure_ascii=False, indent=2)
                z.writestr(f"result/{name}.json", dump(self.nested(name)))
                z.writestr(f"evidence/{name}.json", dump(self.nested(name, True)))
                d = self.docs[name]
                if d["error"]:
                    wr.writerow([name, "документ", "ошибка обработки: " + d["error"]])
                for w in d["warnings"]:
                    field, _, msg = w.partition(": ")
                    wr.writerow([name, field, msg] if msg else [name, "документ", field])
            z.writestr("review_report.csv", "﻿" + report.getvalue())
        return buf.getvalue()


def quality():
    """Сверка локального режима с ручной разметкой gold/."""
    gold, docs = HERE / "gold", HERE / "documents"
    if not gold.is_dir() or not docs.is_dir():
        return {"available": False}
    groups = {g: [0, 0] for g in TPL}
    bad, n = [], 0
    for g in sorted(gold.glob("*.json")):
        src = docs / (g.stem + ".md")
        if not src.exists():
            continue
        n += 1
        want = json.loads(g.read_text(encoding="utf-8"))
        got = extract(decode_bytes(src.read_bytes()))[0]
        for grp, ks in TPL.items():
            for k in ks:
                groups[grp][1] += 1
                if str(got.get(k) or NU) == want[grp][k]:
                    groups[grp][0] += 1
                else:
                    bad.append({"doc": g.stem, "field": k, "gold": want[grp][k], "got": str(got.get(k) or NU)})
    return {"available": True, "documents": n, "groups": groups, "mismatches": bad[:200]}


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def send(self, body, ctype="application/json; charset=utf-8", status=200, extra=None):
        if not isinstance(body, bytes):
            body = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def body(self):
        n = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(n).decode("utf-8")) if n else {}

    def job(self, jid):
        j = JOBS.get(jid)
        if not j:
            self.send({"error": "пакет не найден"}, status=404)
        return j

    def do_GET(self):
        u = urlparse(self.path)
        q = parse_qs(u.query)
        parts = [p for p in u.path.split("/") if p]
        if u.path in ("/", "/index.html"):
            return self.send((HERE / "web" / "index.html").read_bytes(), "text/html; charset=utf-8")
        if u.path == "/api/state":
            return self.send({"llm_configured": llm.configured(), "template": TPL,
                              "has_documents": (HERE / "documents").is_dir()})
        if u.path == "/api/quality":
            return self.send(quality())
        if len(parts) >= 3 and parts[:2] == ["api", "job"]:
            j = self.job(parts[2])
            if not j:
                return
            if len(parts) == 3:
                return self.send(j.summary(int(q.get("since", ["0"])[0])))
            if parts[3] == "doc":
                name = q.get("name", [""])[0]
                d = j.docs.get(name)
                if not d:
                    return self.send({"error": "документ не найден"}, status=404)
                return self.send({"name": name, "text": d["text"], "groups": j.nested(name, True),
                                  "warnings": d["warnings"], "error": d["error"], "llm_fields": d["llm_fields"]})
            if parts[3] == "result.zip":
                return self.send(j.archive(), "application/zip",
                                 extra={"Content-Disposition": 'attachment; filename="result.zip"'})
        self.send({"error": "не найдено"}, status=404)

    def do_POST(self):
        u = urlparse(self.path)
        parts = [p for p in u.path.split("/") if p]
        try:
            data = self.body()
        except Exception:
            return self.send({"error": "некорректный запрос"}, status=400)
        if u.path == "/api/job":
            j = Job()
            with LOCK:
                JOBS[j.id] = j
                for old in list(JOBS)[:-3]:                    # храним три последних пакета
                    JOBS.pop(old, None)
            return self.send({"id": j.id})
        if len(parts) == 4 and parts[:2] == ["api", "job"]:
            j = self.job(parts[2])
            if not j:
                return
            if parts[3] == "add" and j.state == "uploading":
                for f in data.get("files", []):
                    j.add(f["name"], base64.b64decode(f["b64"]))
                return self.send({"files": len(j.order), "skipped": j.skipped})
            if parts[3] == "path" and j.state == "uploading":
                p = Path(data.get("path", "")).expanduser()
                if not p.is_absolute():
                    p = HERE / p
                if p.is_file():
                    j.add(p.name, p.read_bytes())
                elif p.is_dir():
                    for f in sorted(x for x in p.rglob("*") if x.is_file() and not x.name.startswith(".")):
                        if f.suffix.lower() in SUFFIXES + (".zip",):
                            j.add(f.name, f.read_bytes())
                else:
                    return self.send({"error": f"Папка не найдена: {p}"}, status=400)
                return self.send({"files": len(j.order), "skipped": j.skipped})
            if parts[3] == "start" and j.state == "uploading":
                if not j.order:
                    return self.send({"error": "Не найдено ни одного файла .md или .txt"}, status=400)
                j.llm = bool(data.get("llm"))
                if j.llm and not llm.configured():
                    return self.send({"error": "Для режима с YandexGPT задайте YC_API_KEY и YC_FOLDER_ID в файле .env"}, status=400)
                threading.Thread(target=j.run, daemon=True).start()
                return self.send({"ok": True, "total": len(j.order)})
            if parts[3] == "stop":
                j.stop = True
                return self.send({"ok": True})
        self.send({"error": "не найдено"}, status=404)


def main():
    ap = argparse.ArgumentParser(description="Веб-интерфейс для пакетной обработки эпикризов")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--no-browser", action="store_true", help="не открывать браузер автоматически")
    a = ap.parse_args()
    server = ThreadingHTTPServer(("127.0.0.1", a.port), Handler)
    url = f"http://127.0.0.1:{a.port}"
    print(f"Интерфейс открыт: {url}\nОстановить — Ctrl+C")
    if not a.no_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nОстановлено")


if __name__ == "__main__":
    main()
