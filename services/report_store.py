"""Durable single-operator job records; interrupted jobs never become PASS."""
import sqlite3
from pathlib import Path
from models.verification import VerificationReport


class ReportStore:
    def __init__(self, path):
        self.path = str(path)
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS reports (id TEXT PRIMARY KEY, owner TEXT NOT NULL, status TEXT NOT NULL, report TEXT)')

    def connect(self):
        return sqlite3.connect(self.path, timeout=10)

    def create(self, report_id, owner):
        with self.connect() as db:
            db.execute('INSERT INTO reports VALUES (?, ?, ?, NULL)', (report_id, owner, 'QUEUED'))

    def start(self, report_id, owner):
        with self.connect() as db:
            return db.execute("UPDATE reports SET status='RUNNING' WHERE id=? AND owner=? AND status='QUEUED'", (report_id, owner)).rowcount == 1

    def finish(self, report_id, owner, report):
        with self.connect() as db:
            db.execute('UPDATE reports SET status=?, report=? WHERE id=? AND owner=?', (report.verdict.value, report.model_dump_json(), report_id, owner))

    def get(self, report_id, owner):
        with self.connect() as db:
            row = db.execute('SELECT status, report FROM reports WHERE id=? AND owner=?', (report_id, owner)).fetchone()
        if row is None:
            return None
        return {'report_id': report_id, 'status': row[0], 'report': __import__('json').loads(row[1]) if row[1] else None}

    def recover_interrupted(self):
        with self.connect() as db:
            rows = db.execute("SELECT id FROM reports WHERE status IN ('QUEUED','RUNNING')").fetchall()
            for (report_id,) in rows:
                report = VerificationReport(id=report_id, partial_reasons=['Worker interrupted; submit a new verification after reviewing the outcome'])
                report.final_verdict()
                db.execute('UPDATE reports SET status=?, report=? WHERE id=?', ('PARTIAL', report.model_dump_json(), report_id))
        return len(rows)

    def healthy(self):
        with self.connect() as db:
            return db.execute('SELECT 1').fetchone() == (1,)
