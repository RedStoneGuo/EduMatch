"""SQLite data layer for EduMatch.

Chosen because the corpus is moderate in size (795 archive files, hundreds of
facts, thousands of rows at most) and SQLite ships with Python - no server, no
extra infrastructure, easy to ship with a competition submission.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterable, Iterator

from .config import Settings, load_settings

SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
    doc_id TEXT PRIMARY KEY,
    relative_path TEXT NOT NULL,
    file_name TEXT NOT NULL,
    extension TEXT,
    category TEXT,
    school TEXT,
    years TEXT,
    size_kb REAL,
    is_pdf INTEGER DEFAULT 0,
    text_status TEXT DEFAULT 'unknown',
    retrieval_time TEXT
);
CREATE TABLE IF NOT EXISTS schools (
    school_id TEXT PRIMARY KEY,
    name TEXT UNIQUE NOT NULL,
    is_211 INTEGER DEFAULT 1,
    city TEXT DEFAULT '北京'
);
CREATE TABLE IF NOT EXISTS majors (
    major_id TEXT PRIMARY KEY,
    name TEXT UNIQUE NOT NULL,
    family TEXT,
    major_code TEXT
);
CREATE TABLE IF NOT EXISTS education_facts (
    fact_id TEXT PRIMARY KEY,
    family TEXT,
    year INTEGER,
    school TEXT,
    major TEXT,
    section TEXT,
    fact_type TEXT,
    value REAL,
    unit TEXT,
    raw_text TEXT,
    source_document TEXT,
    source_line INTEGER,
    upstream_source TEXT,
    evidence_level TEXT,
    confidence REAL
);
CREATE TABLE IF NOT EXISTS skills (
    skill_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    category TEXT,
    parents TEXT,
    children TEXT,
    aliases TEXT
);
CREATE TABLE IF NOT EXISTS courses (
    course_id TEXT PRIMARY KEY,
    school TEXT,
    year INTEGER,
    major TEXT,
    name TEXT NOT NULL,
    category TEXT,
    credits REAL,
    practice_hours REAL,
    is_practice INTEGER DEFAULT 0,
    description TEXT,
    source_document TEXT,
    evidence_level TEXT DEFAULT 'D'
);
CREATE TABLE IF NOT EXISTS course_skills (
    course_id TEXT,
    skill_id TEXT,
    match_type TEXT,
    confidence REAL,
    PRIMARY KEY (course_id, skill_id)
);
CREATE TABLE IF NOT EXISTS jobs (
    job_id TEXT PRIMARY KEY,
    company TEXT, position TEXT, industry TEXT, city TEXT,
    salary_min REAL, salary_max REAL, education TEXT, experience TEXT,
    job_description TEXT, publish_time TEXT, source TEXT, url TEXT, crawl_time TEXT,
    company_norm TEXT, position_norm TEXT, city_norm TEXT, salary_bucket TEXT,
    fingerprint TEXT, content_key TEXT, is_duplicate INTEGER DEFAULT 0,
    dataset_id TEXT, search_keyword TEXT, city_code TEXT, work_type TEXT,
    company_size TEXT, salary_detail TEXT, source_job_id TEXT
);
CREATE TABLE IF NOT EXISTS job_skills (
    job_id TEXT, skill_id TEXT, weight REAL DEFAULT 1.0,
    PRIMARY KEY (job_id, skill_id)
);
CREATE TABLE IF NOT EXISTS market_evidence (
    dataset_id TEXT PRIMARY KEY,
    payload TEXT NOT NULL,
    source_document TEXT,
    evidence_level TEXT,
    n_postings INTEGER,
    notes TEXT,
    retrieval_time TEXT
);
CREATE TABLE IF NOT EXISTS policies (
    policy_id TEXT PRIMARY KEY,
    title TEXT, file_name TEXT, relative_path TEXT, extension TEXT,
    publish_date TEXT, year INTEGER, agency TEXT, region TEXT, policy_type TEXT,
    policy_goal TEXT, key_terms TEXT, industry_direction TEXT,
    talent_direction TEXT, education_direction TEXT, skills_related TEXT,
    evidence_quote TEXT, text_status TEXT, char_count INTEGER, source TEXT, url TEXT,
    retrieval_time TEXT, is_duplicate INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS evidence (
    evidence_id TEXT PRIMARY KEY,
    run_id TEXT, source_type TEXT, title TEXT, locator TEXT, quote TEXT,
    page INTEGER, year INTEGER, school TEXT, url TEXT, retrieval_time TEXT,
    evidence_level TEXT, confidence REAL
);
CREATE TABLE IF NOT EXISTS metrics (
    run_id TEXT, metric_id TEXT, name TEXT, value REAL, unit TEXT, status TEXT,
    confidence REAL, evidence_level TEXT, source_count INTEGER, reason TEXT,
    n_observations INTEGER, detail TEXT,
    PRIMARY KEY (run_id, metric_id)
);
CREATE TABLE IF NOT EXISTS scores (
    run_id TEXT, key TEXT, value REAL, dimension TEXT, payload TEXT,
    PRIMARY KEY (run_id, key)
);
CREATE TABLE IF NOT EXISTS analysis_runs (
    run_id TEXT PRIMARY KEY,
    user_query TEXT, mode TEXT, plan TEXT, tool_calls TEXT, skill_calls TEXT,
    input_data TEXT, metrics TEXT, scores TEXT, evidence TEXT,
    final_answer TEXT, started_at TEXT, finished_at TEXT, status TEXT
);
CREATE INDEX IF NOT EXISTS idx_edu_facts_school ON education_facts(school, year, fact_type);
CREATE INDEX IF NOT EXISTS idx_policies_year ON policies(year, agency);
"""

# Columns added after the first release; applied idempotently by migrate().
JOB_COLUMN_MIGRATIONS: dict[str, str] = {
    "dataset_id": "TEXT",
    "search_keyword": "TEXT",
    "city_code": "TEXT",
    "work_type": "TEXT",
    "company_size": "TEXT",
    "salary_detail": "TEXT",
    "source_job_id": "TEXT",
}


def migrate(conn: sqlite3.Connection) -> list[str]:
    """Add missing columns to existing databases without dropping data."""
    applied: list[str] = []
    existing = {row["name"] for row in conn.execute("PRAGMA table_info(jobs)").fetchall()}
    for column, sql_type in JOB_COLUMN_MIGRATIONS.items():
        if column not in existing:
            conn.execute(f"ALTER TABLE jobs ADD COLUMN {column} {sql_type}")
            applied.append(column)
    # indexes that depend on the migrated columns must be created afterwards
    conn.executescript(
        "CREATE INDEX IF NOT EXISTS idx_jobs_fingerprint ON jobs(fingerprint);"
        "CREATE INDEX IF NOT EXISTS idx_jobs_dataset ON jobs(dataset_id, search_keyword);"
    )
    return applied


@contextmanager
def connect(settings: Settings | None = None) -> Iterator[sqlite3.Connection]:
    settings = settings or load_settings()
    settings.db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(settings.db_path)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_schema(settings: Settings | None = None) -> Path:
    settings = settings or load_settings()
    with connect(settings) as conn:
        conn.executescript(SCHEMA)
        migrate(conn)
    return settings.db_path


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def upsert_many(conn: sqlite3.Connection, table: str, rows: Iterable[dict[str, Any]]) -> int:
    rows = [r for r in rows if r]
    if not rows:
        return 0
    cols = sorted(rows[0])
    placeholders = ",".join("?" for _ in cols)
    sql = f"INSERT OR REPLACE INTO {table} ({','.join(cols)}) VALUES ({placeholders})"
    conn.executemany(sql, [[row.get(c) for c in cols] for row in rows])
    return len(rows)


def insert_documents(conn: sqlite3.Connection, records: list[dict[str, Any]]) -> int:
    rows = [
        {
            "doc_id": f"doc:{i:05d}",
            "relative_path": r["relative_path"],
            "file_name": r["file_name"],
            "extension": r["extension"],
            "category": r["category"],
            "school": r.get("school"),
            "years": _json(r.get("years") or []),
            "size_kb": r.get("size_kb"),
            "is_pdf": 1 if r.get("is_pdf") else 0,
            "text_status": "extractable" if r.get("is_text_extractable") else "pdf_needs_extractor",
        }
        for i, r in enumerate(records, start=1)
    ]
    return upsert_many(conn, "documents", rows)


def save_run(conn: sqlite3.Connection, run: dict[str, Any]) -> None:
    conn.execute(
        """INSERT OR REPLACE INTO analysis_runs
           (run_id,user_query,mode,plan,tool_calls,skill_calls,input_data,metrics,
            scores,evidence,final_answer,started_at,finished_at,status)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            run["run_id"], run.get("user_query"), run.get("mode"),
            _json(run.get("plan")), _json(run.get("tool_calls")), _json(run.get("skill_calls")),
            _json(run.get("input_data")), _json(run.get("metrics")), _json(run.get("scores")),
            _json(run.get("evidence")), run.get("final_answer"),
            run.get("started_at"), run.get("finished_at"), run.get("status", "ok"),
        ),
    )


def save_evidence(conn: sqlite3.Connection, run_id: str, items: list[dict[str, Any]]) -> int:
    rows = [
        {
            "evidence_id": item["evidence_id"],
            "run_id": run_id,
            "source_type": item.get("source_type"),
            "title": item.get("title"),
            "locator": item.get("locator"),
            "quote": item.get("quote"),
            "page": item.get("page"),
            "year": item.get("year"),
            "school": item.get("school"),
            "url": item.get("url"),
            "retrieval_time": item.get("retrieval_time"),
            "evidence_level": item.get("evidence_level"),
            "confidence": item.get("confidence"),
        }
        for item in items
    ]
    return upsert_many(conn, "evidence", rows)


def save_metrics(conn: sqlite3.Connection, run_id: str, metrics: list[dict[str, Any]]) -> int:
    rows = [
        {
            "run_id": run_id,
            "metric_id": m["metric_id"],
            "name": m["name"],
            "value": m.get("value"),
            "unit": m.get("unit"),
            "status": m.get("status"),
            "confidence": m.get("confidence"),
            "evidence_level": m.get("evidence_level"),
            "source_count": m.get("source_count"),
            "reason": m.get("reason"),
            "n_observations": m.get("n_observations"),
            "detail": _json(m.get("detail") or {}),
        }
        for m in metrics
    ]
    return upsert_many(conn, "metrics", rows)


def query(conn: sqlite3.Connection, sql: str, params: Iterable[Any] = ()) -> list[dict[str, Any]]:
    return [dict(r) for r in conn.execute(sql, tuple(params)).fetchall()]
