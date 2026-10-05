"""Параллельный разбор документов на нескольких ядрах процессора.

Каждый эпикриз разбирается независимо теми же правилами, что и раньше, поэтому результат
не меняется — меняется только то, сколько документов обрабатывается одновременно.
Обращения к YandexGPT сюда не входят: они выполняются в основном процессе по очереди.
"""
import os
from concurrent.futures import ProcessPoolExecutor
from concurrent.futures.process import BrokenProcessPool
from pathlib import Path

MIN_BATCH = 24            # меньше этого запускать процессы невыгодно
_pool = None
_pool_size = 0


def default_workers():
    return max(1, min(os.cpu_count() or 1, 8))


def parse(item):
    """Разбор одного документа. item — путь к файлу или байты. Возвращает (текст, значения, цитаты, ошибка)."""
    from extract import extract
    from run import decode_bytes
    try:
        raw = Path(item).read_bytes() if isinstance(item, (str, Path)) else item
        text = decode_bytes(raw)
    except Exception as e:
        return "", {}, {}, f"{type(e).__name__}: {e}"
    try:
        vals, ev = extract(text)
        return text, vals, ev, None
    except Exception as e:                          # документ не должен ронять пакет
        return text, {}, {}, f"{type(e).__name__}: {e}"


def _executor(workers):
    global _pool, _pool_size
    if _pool is None or _pool_size != workers:
        if _pool is not None:
            _pool.shutdown(wait=False)
        _pool, _pool_size = ProcessPoolExecutor(max_workers=workers), workers
    return _pool


def run(items, workers=None, stop=lambda: False):
    """Выдаёт результаты parse() в исходном порядке. При сбое процессов продолжает последовательно."""
    global _pool
    items = list(items)
    workers = default_workers() if not workers else max(1, workers)
    if workers == 1 or len(items) < MIN_BATCH:
        for it in items:
            if stop():
                return
            yield parse(it)
        return
    step = workers * 8                              # подаём порциями, чтобы «Остановить» срабатывало быстро
    done = 0
    try:
        ex = _executor(workers)
        while done < len(items) and not stop():
            chunk = items[done:done + step]
            for res in ex.map(parse, chunk, chunksize=max(1, len(chunk) // (workers * 2))):
                yield res
                done += 1
    except (BrokenProcessPool, OSError, RuntimeError):
        _pool = None
        for it in items[done:]:
            if stop():
                return
            yield parse(it)


def shutdown():
    global _pool
    if _pool is not None:
        _pool.shutdown(wait=False)
        _pool = None
