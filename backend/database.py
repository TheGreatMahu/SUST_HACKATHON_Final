"""
SQLite Persistence Layer — SuperAgent LiquidityIQ
===================================================
Persists transactions, agents, cases, audit trails, alerts, and narrations
to a local SQLite database. Data survives server restarts.

Design decisions:
  - Raw sqlite3 (not SQLAlchemy) — minimal overhead, judges can read the code
  - Single DB file at backend/data/liquidityiq.db
  - Write-through: every mutation hits disk immediately
  - Read: load from DB on startup if it exists, skip data regeneration
"""

import sqlite3
import json
from pathlib import Path
from datetime import datetime
from typing import Optional


DB_PATH = Path("backend/data/liquidityiq.db")


class Database:
    """SQLite persistence for the LiquidityIQ system."""

    def __init__(self, db_path: Path = DB_PATH):
        self._db_path = db_path
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn: Optional[sqlite3.Connection] = None

    def connect(self):
        """Open connection and create tables if needed."""
        self._conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._create_tables()
        print(f"[Database] Connected to {self._db_path}")

    def close(self):
        if self._conn:
            self._conn.close()
            self._conn = None

    @property
    def conn(self) -> sqlite3.Connection:
        if not self._conn:
            self.connect()
        return self._conn

    # ------------------------------------------------------------------
    # Schema
    # ------------------------------------------------------------------

    def _create_tables(self):
        cur = self._conn.cursor()

        cur.executescript("""
            CREATE TABLE IF NOT EXISTS agents (
                agent_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                area TEXT NOT NULL,
                thana TEXT NOT NULL,
                district TEXT DEFAULT 'Sylhet',
                active_providers TEXT NOT NULL,  -- JSON array
                shared_cash_amount REAL NOT NULL,
                provider_balances TEXT NOT NULL,  -- JSON object
                created_at TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS transactions (
                txn_id TEXT PRIMARY KEY,
                provider TEXT NOT NULL,
                agent_id TEXT NOT NULL,
                account_id TEXT NOT NULL,
                txn_type TEXT NOT NULL,
                amount REAL NOT NULL,
                timestamp TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at TEXT DEFAULT (datetime('now'))
            );

            CREATE INDEX IF NOT EXISTS idx_txn_provider ON transactions(provider);
            CREATE INDEX IF NOT EXISTS idx_txn_agent ON transactions(agent_id);
            CREATE INDEX IF NOT EXISTS idx_txn_timestamp ON transactions(timestamp);

            CREATE TABLE IF NOT EXISTS cases (
                case_id TEXT PRIMARY KEY,
                alert_type TEXT,
                provider TEXT,
                agent_id TEXT,
                severity TEXT,
                confidence TEXT,
                classification TEXT,
                status TEXT NOT NULL DEFAULT 'open',
                title TEXT,
                summary TEXT,
                evidence TEXT,  -- JSON
                narration TEXT,  -- JSON
                recommended_action TEXT,
                disclaimer TEXT,
                current_owner_id TEXT,
                current_owner_role TEXT,
                resolved_at TEXT,
                resolved_by TEXT,
                resolution_note TEXT,
                created_at TEXT DEFAULT (datetime('now')),
                updated_at TEXT DEFAULT (datetime('now'))
            );

            CREATE INDEX IF NOT EXISTS idx_case_status ON cases(status);
            CREATE INDEX IF NOT EXISTS idx_case_provider ON cases(provider);

            CREATE TABLE IF NOT EXISTS audit_trail (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                case_id TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                actor_id TEXT,
                actor_role TEXT,
                action TEXT NOT NULL,
                from_status TEXT,
                to_status TEXT,
                note TEXT,
                FOREIGN KEY (case_id) REFERENCES cases(case_id)
            );

            CREATE INDEX IF NOT EXISTS idx_audit_case ON audit_trail(case_id);

            CREATE TABLE IF NOT EXISTS notifications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                case_id TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                action TEXT,
                target_role TEXT,
                target_id TEXT,
                channel TEXT,
                message TEXT,
                FOREIGN KEY (case_id) REFERENCES cases(case_id)
            );

            CREATE TABLE IF NOT EXISTS alerts (
                alert_id TEXT PRIMARY KEY,
                alert_type TEXT NOT NULL,
                provider TEXT,
                agent_id TEXT,
                severity TEXT,
                confidence TEXT,
                classification TEXT,
                title TEXT,
                summary TEXT,
                evidence TEXT,  -- JSON
                recommended_action TEXT,
                disclaimer TEXT,
                created_at TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS narrations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                alert_id TEXT,
                english TEXT,
                bangla TEXT,
                banglish TEXT,
                narration_mode TEXT,
                generated_at TEXT,
                FOREIGN KEY (alert_id) REFERENCES alerts(alert_id)
            );

            CREATE TABLE IF NOT EXISTS chat_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT DEFAULT 'default',
                role TEXT NOT NULL,  -- 'user' or 'assistant'
                content TEXT NOT NULL,
                language TEXT DEFAULT 'english',
                timestamp TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS system_meta (
                key TEXT PRIMARY KEY,
                value TEXT,
                updated_at TEXT DEFAULT (datetime('now'))
            );
        """)
        self._conn.commit()

    # ------------------------------------------------------------------
    # System metadata
    # ------------------------------------------------------------------

    def set_meta(self, key: str, value: str):
        self.conn.execute(
            "INSERT OR REPLACE INTO system_meta (key, value, updated_at) VALUES (?, ?, ?)",
            (key, value, datetime.utcnow().isoformat())
        )
        self.conn.commit()

    def get_meta(self, key: str) -> Optional[str]:
        row = self.conn.execute("SELECT value FROM system_meta WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else None

    def has_data(self) -> bool:
        """Check if the DB already has generated data."""
        row = self.conn.execute("SELECT COUNT(*) as cnt FROM transactions").fetchone()
        return row["cnt"] > 0

    # ------------------------------------------------------------------
    # Agents
    # ------------------------------------------------------------------

    def save_agents(self, agents: list[dict]):
        cur = self.conn.cursor()
        for a in agents:
            cur.execute("""
                INSERT OR REPLACE INTO agents
                (agent_id, name, area, thana, district, active_providers, shared_cash_amount, provider_balances)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                a["agent_id"],
                a.get("name", ""),
                a.get("area", ""),
                a.get("thana", ""),
                a.get("district", "Sylhet"),
                json.dumps(a.get("active_providers", []), default=str),
                a.get("shared_cash", {}).get("cash_amount", 0) if isinstance(a.get("shared_cash"), dict) else 0,
                json.dumps(a.get("provider_balances", {}), default=str),
            ))
        self.conn.commit()

    # ------------------------------------------------------------------
    # Transactions
    # ------------------------------------------------------------------

    def save_transactions(self, transactions: list[dict]):
        """Bulk insert transactions."""
        cur = self.conn.cursor()
        cur.executemany("""
            INSERT OR IGNORE INTO transactions
            (txn_id, provider, agent_id, account_id, txn_type, amount, timestamp, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, [
            (
                t["txn_id"], t["provider"], t["agent_id"], t["account_id"],
                t["txn_type"], t["amount"], str(t["timestamp"]), t["status"]
            )
            for t in transactions
        ])
        self.conn.commit()

    def get_transaction_count(self) -> int:
        row = self.conn.execute("SELECT COUNT(*) as cnt FROM transactions").fetchone()
        return row["cnt"]

    def get_transactions(self, provider: str = None, agent_id: str = None,
                         since: str = None, until: str = None, limit: int = 200) -> list[dict]:
        query = "SELECT * FROM transactions WHERE 1=1"
        params = []
        if provider:
            query += " AND provider = ?"
            params.append(provider)
        if agent_id:
            query += " AND agent_id = ?"
            params.append(agent_id)
        if since:
            query += " AND timestamp >= ?"
            params.append(since)
        if until:
            query += " AND timestamp <= ?"
            params.append(until)
        query += " ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)

        rows = self.conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Cases
    # ------------------------------------------------------------------

    def save_case(self, case: dict):
        """Insert or update a case."""
        cur = self.conn.cursor()
        cur.execute("""
            INSERT OR REPLACE INTO cases
            (case_id, alert_type, provider, agent_id, severity, confidence,
             classification, status, title, summary, evidence, narration,
             recommended_action, disclaimer, current_owner_id, current_owner_role,
             resolved_at, resolved_by, resolution_note, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            case.get("case_id"),
            case.get("alert_type"),
            case.get("provider"),
            case.get("agent_id"),
            case.get("severity"),
            case.get("confidence"),
            case.get("classification"),
            case.get("status", "open"),
            case.get("title"),
            case.get("summary"),
            json.dumps(case.get("evidence", {}), default=str),
            json.dumps(case.get("narration", {}), default=str),
            case.get("recommended_action"),
            case.get("disclaimer"),
            case.get("current_owner_id"),
            case.get("current_owner_role"),
            case.get("resolved_at"),
            case.get("resolved_by"),
            case.get("resolution_note"),
            datetime.utcnow().isoformat(),
        ))
        self.conn.commit()

    def save_audit_entry(self, case_id: str, entry: dict):
        """Append an audit trail entry."""
        self.conn.execute("""
            INSERT INTO audit_trail
            (case_id, timestamp, actor_id, actor_role, action, from_status, to_status, note)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            case_id,
            entry.get("timestamp", datetime.utcnow().isoformat()),
            entry.get("actor_id"),
            entry.get("actor_role"),
            entry.get("action"),
            entry.get("from_status"),
            entry.get("to_status"),
            entry.get("note"),
        ))
        self.conn.commit()

    def save_notification(self, case_id: str, notification: dict):
        """Log a notification event."""
        self.conn.execute("""
            INSERT INTO notifications
            (case_id, timestamp, action, target_role, target_id, channel, message)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            case_id,
            notification.get("timestamp", datetime.utcnow().isoformat()),
            notification.get("action"),
            notification.get("target_role"),
            notification.get("target_id"),
            notification.get("channel"),
            notification.get("message"),
        ))
        self.conn.commit()

    def get_cases(self, status: str = None, provider: str = None,
                  agent_id: str = None) -> list[dict]:
        query = "SELECT * FROM cases WHERE 1=1"
        params = []
        if status:
            query += " AND status = ?"
            params.append(status)
        if provider:
            query += " AND provider = ?"
            params.append(provider)
        if agent_id:
            query += " AND agent_id = ?"
            params.append(agent_id)
        query += " ORDER BY created_at DESC"
        rows = self.conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]

    def get_audit_trail(self, case_id: str) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM audit_trail WHERE case_id = ? ORDER BY timestamp",
            (case_id,)
        ).fetchall()
        return [dict(r) for r in rows]

    def get_notifications(self, case_id: str) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM notifications WHERE case_id = ? ORDER BY timestamp",
            (case_id,)
        ).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Alerts & Narrations
    # ------------------------------------------------------------------

    def save_alert(self, alert: dict):
        self.conn.execute("""
            INSERT OR REPLACE INTO alerts
            (alert_id, alert_type, provider, agent_id, severity, confidence,
             classification, title, summary, evidence, recommended_action, disclaimer)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            alert.get("alert_id"),
            alert.get("alert_type"),
            alert.get("provider"),
            alert.get("agent_id"),
            alert.get("severity"),
            alert.get("confidence"),
            alert.get("classification"),
            alert.get("title"),
            alert.get("summary"),
            json.dumps(alert.get("evidence", {}), default=str),
            alert.get("recommended_action"),
            alert.get("disclaimer"),
        ))
        self.conn.commit()

    def save_narration(self, alert_id: str, narration: dict):
        self.conn.execute("""
            INSERT INTO narrations
            (alert_id, english, bangla, banglish, narration_mode, generated_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            alert_id,
            narration.get("english", ""),
            narration.get("bangla", ""),
            narration.get("banglish", ""),
            narration.get("narration_mode", "template"),
            narration.get("generated_at", datetime.utcnow().isoformat()),
        ))
        self.conn.commit()

    # ------------------------------------------------------------------
    # Chat History
    # ------------------------------------------------------------------

    def save_chat_message(self, role: str, content: str, session_id: str = "default",
                          language: str = "english"):
        self.conn.execute("""
            INSERT INTO chat_history (session_id, role, content, language)
            VALUES (?, ?, ?, ?)
        """, (session_id, role, content, language))
        self.conn.commit()

    def get_chat_history(self, session_id: str = "default", limit: int = 20) -> list[dict]:
        rows = self.conn.execute("""
            SELECT role, content, language, timestamp
            FROM chat_history
            WHERE session_id = ?
            ORDER BY id DESC LIMIT ?
        """, (session_id, limit)).fetchall()
        return list(reversed([dict(r) for r in rows]))

    def clear_chat_history(self, session_id: str = "default"):
        self.conn.execute("DELETE FROM chat_history WHERE session_id = ?", (session_id,))
        self.conn.commit()

    # ------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------

    def get_stats(self) -> dict:
        """Database statistics for the /db-stats endpoint."""
        tables = ["agents", "transactions", "cases", "audit_trail",
                   "notifications", "alerts", "narrations", "chat_history"]
        stats = {}
        for table in tables:
            row = self.conn.execute(f"SELECT COUNT(*) as cnt FROM {table}").fetchone()
            stats[table] = row["cnt"]

        # DB file size
        if self._db_path.exists():
            stats["db_file_size_bytes"] = self._db_path.stat().st_size
            stats["db_file_size_mb"] = round(self._db_path.stat().st_size / (1024 * 1024), 2)

        stats["db_path"] = str(self._db_path)
        return stats
