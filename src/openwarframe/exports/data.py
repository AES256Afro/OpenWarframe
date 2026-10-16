"""Machine formats: account.json, account.sqlite and a CSV folder."""

from __future__ import annotations

import csv
import json
import sqlite3
from pathlib import Path

from ..report.model import Report
from .tables import Table


def write_json(report: Report, path: Path) -> Path:
    path.write_text(report.model_dump_json(indent=1), encoding="utf-8")
    return path


def write_schema(path: Path) -> Path:
    schema = Report.model_json_schema()
    schema["$id"] = "https://github.com/AES256Afro/OpenWarframe/docs/schema/account.schema.json"
    schema["title"] = "OpenWarframe account report"
    path.write_text(json.dumps(schema, indent=1), encoding="utf-8")
    return path


def _sql_type(values: list) -> str:
    for v in values:
        if v is None:
            continue
        if isinstance(v, bool | int):
            return "INTEGER"
        if isinstance(v, float):
            return "REAL"
        return "TEXT"
    return "TEXT"


def _cell(v):
    if isinstance(v, list | dict):
        return json.dumps(v, ensure_ascii=False)
    return v


def write_sqlite(tables: list[Table], report: Report, path: Path) -> Path:
    if path.exists():
        path.unlink()
    conn = sqlite3.connect(path)
    try:
        with conn:
            conn.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT)")
            conn.executemany(
                "INSERT INTO meta VALUES (?, ?)",
                [
                    ("schema_version", report.schema_version),
                    ("generated_at", report.generated_at.isoformat()),
                    ("snapshot_taken_at", report.snapshot_taken_at.isoformat()),
                    ("coverage", ",".join(report.coverage)),
                    ("anonymized", str(report.identity.anonymized).lower()),
                ],
            )
            for t in tables:
                cols = t.columns
                types = {c: _sql_type([r.get(c) for r in t.rows]) for c in cols}
                ddl = ", ".join(f'"{c}" {types[c]}' for c in cols)
                conn.execute(f'CREATE TABLE "{t.name}" ({ddl})')
                conn.executemany(
                    f'INSERT INTO "{t.name}" VALUES ({",".join("?" * len(cols))})',
                    [[_cell(r.get(c)) for c in cols] for r in t.rows],
                )
    finally:
        conn.close()
    return path


def write_csv(tables: list[Table], directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    for t in tables:
        with (directory / f"{t.name}.csv").open("w", newline="", encoding="utf-8-sig") as fh:
            w = csv.DictWriter(fh, fieldnames=t.columns, extrasaction="ignore")
            w.writeheader()
            for r in t.rows:
                w.writerow({c: _cell(r.get(c)) for c in t.columns})
    return directory
