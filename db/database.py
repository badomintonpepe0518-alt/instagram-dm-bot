from __future__ import annotations

import sqlite3
import os
from datetime import datetime
from typing import Optional

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "instagram_dm.db")


def get_connection():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db():
    conn = get_connection()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS accounts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            status TEXT DEFAULT 'pending' CHECK(status IN ('pending','sent','skipped')),
            sent_at TEXT,
            created_at TEXT DEFAULT (datetime('now','localtime')),
            score INTEGER,
            followers INTEGER,
            posts INTEGER,
            bio TEXT,
            full_name TEXT,
            is_business INTEGER,
            enriched_at TEXT,
            score_reason TEXT
        );

        CREATE TABLE IF NOT EXISTS templates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            body TEXT NOT NULL,
            is_active INTEGER DEFAULT 1,
            created_at TEXT DEFAULT (datetime('now','localtime'))
        );

        CREATE TABLE IF NOT EXISTS engagements (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL,
            type TEXT NOT NULL CHECK(type IN ('follow_back','like','comment','story_view','dm_reply','report')),
            detail TEXT,
            detected_at TEXT DEFAULT (datetime('now','localtime'))
        );

        CREATE TABLE IF NOT EXISTS learning_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL,
            summary TEXT NOT NULL,
            insights TEXT,
            follow_back_rate REAL,
            like_rate REAL,
            total_sent INTEGER,
            total_follow_back INTEGER,
            total_like INTEGER,
            created_at TEXT DEFAULT (datetime('now','localtime'))
        );
    """)
    conn.commit()
    conn.close()
    _import_csvs_if_empty()


def _safe_int(v):
    try: return int(v)
    except (ValueError, TypeError): return None

def _safe_float(v):
    try: return float(v)
    except (ValueError, TypeError): return 0.0

def _import_csvs_if_empty():
    """DBが空のとき（クラウド初回起動時）CSVからデータを復元する"""
    import csv
    conn = get_connection()
    count = conn.execute("SELECT COUNT(*) FROM accounts").fetchone()[0]
    if count > 0:
        conn.close()
        return

    data_dir = os.path.dirname(DB_PATH)

    # accounts.csv
    csv_path = os.path.join(data_dir, "accounts.csv")
    if os.path.exists(csv_path):
        with open(csv_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                try:
                    conn.execute(
                        """INSERT OR IGNORE INTO accounts
                           (id,username,status,sent_at,created_at,score,followers,posts,bio,full_name,is_business,enriched_at,score_reason)
                           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                        (
                            _safe_int(row.get("id")),
                            row["username"],
                            row.get("status", "pending"),
                            row.get("sent_at") or None,
                            row.get("created_at") or None,
                            _safe_int(row.get("score")),
                            _safe_int(row.get("followers")),
                            _safe_int(row.get("posts")),
                            row.get("bio") or None,
                            row.get("full_name") or None,
                            _safe_int(row.get("is_business")),
                            row.get("enriched_at") or None,
                            row.get("score_reason") or None,
                        ),
                    )
                except Exception:
                    pass

    # templates.csv
    csv_path = os.path.join(data_dir, "templates.csv")
    if os.path.exists(csv_path):
        with open(csv_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                try:
                    conn.execute(
                        "INSERT OR IGNORE INTO templates (id,name,body,is_active,created_at) VALUES (?,?,?,?,?)",
                        (_safe_int(row.get("id")), row["name"], row["body"],
                         _safe_int(row.get("is_active")) or 1, row.get("created_at")),
                    )
                except Exception:
                    pass

    # engagements.csv
    csv_path = os.path.join(data_dir, "engagements.csv")
    if os.path.exists(csv_path):
        with open(csv_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                try:
                    conn.execute(
                        "INSERT OR IGNORE INTO engagements (id,username,type,detail,detected_at) VALUES (?,?,?,?,?)",
                        (_safe_int(row.get("id")), row["username"], row["type"],
                         row.get("detail") or None, row.get("detected_at")),
                    )
                except Exception:
                    pass

    # learning_log.csv
    csv_path = os.path.join(data_dir, "learning_log.csv")
    if os.path.exists(csv_path):
        with open(csv_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                try:
                    conn.execute(
                        """INSERT OR IGNORE INTO learning_log
                           (id,date,summary,insights,follow_back_rate,like_rate,total_sent,total_follow_back,total_like,created_at)
                           VALUES (?,?,?,?,?,?,?,?,?,?)""",
                        (
                            _safe_int(row.get("id")), row["date"], row["summary"],
                            row.get("insights") or None,
                            _safe_float(row.get("follow_back_rate")),
                            _safe_float(row.get("like_rate")),
                            _safe_int(row.get("total_sent")),
                            _safe_int(row.get("total_follow_back")),
                            _safe_int(row.get("total_like")),
                            row.get("created_at"),
                        ),
                    )
                except Exception:
                    pass

    conn.commit()
    conn.close()


# --- Accounts ---

def add_accounts(usernames):
    conn = get_connection()
    added = 0
    for u in usernames:
        u = u.strip().lstrip("@")
        if not u:
            continue
        try:
            conn.execute("INSERT INTO accounts (username) VALUES (?)", (u,))
            added += 1
        except sqlite3.IntegrityError:
            pass
    conn.commit()
    conn.close()
    return added


def get_accounts(status=None):
    conn = get_connection()
    if status:
        rows = conn.execute("SELECT * FROM accounts WHERE status=? ORDER BY id", (status,)).fetchall()
    else:
        rows = conn.execute("SELECT * FROM accounts ORDER BY id").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_account_counts():
    conn = get_connection()
    rows = conn.execute("SELECT status, COUNT(*) as cnt FROM accounts GROUP BY status").fetchall()
    today = datetime.now().strftime("%Y-%m-%d")
    today_sent = conn.execute(
        "SELECT COUNT(*) as cnt FROM accounts WHERE status='sent' AND sent_at LIKE ?",
        (today + "%",),
    ).fetchone()["cnt"]
    conn.close()
    result = {"pending": 0, "sent": 0, "skipped": 0}
    for r in rows:
        result[r["status"]] = r["cnt"]
    result["total"] = sum(result.values())
    result["today_sent"] = today_sent
    return result


def update_account_status(account_id, status):
    conn = get_connection()
    sent_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S") if status == "sent" else None
    conn.execute("UPDATE accounts SET status=?, sent_at=? WHERE id=?", (status, sent_at, account_id))
    conn.commit()
    conn.close()


def delete_account(account_id):
    conn = get_connection()
    conn.execute("DELETE FROM accounts WHERE id=?", (account_id,))
    conn.commit()
    conn.close()


def delete_all_accounts():
    conn = get_connection()
    conn.execute("DELETE FROM accounts")
    conn.commit()
    conn.close()


def reset_accounts():
    conn = get_connection()
    conn.execute("UPDATE accounts SET status='pending', sent_at=NULL")
    conn.commit()
    conn.close()


# --- Templates ---

def get_active_template():
    conn = get_connection()
    row = conn.execute("SELECT * FROM templates WHERE is_active=1 ORDER BY id DESC LIMIT 1").fetchone()
    conn.close()
    return dict(row) if row else None


def save_template(name, body):
    conn = get_connection()
    conn.execute("UPDATE templates SET is_active=0")
    conn.execute("INSERT INTO templates (name, body, is_active) VALUES (?, ?, 1)", (name, body))
    conn.commit()
    conn.close()


def update_template(template_id, body):
    conn = get_connection()
    conn.execute("UPDATE templates SET body=? WHERE id=?", (body, template_id))
    conn.commit()
    conn.close()


# --- Engagements ---

def add_engagement(username, eng_type, detail=None):
    conn = get_connection()
    conn.execute(
        "INSERT INTO engagements (username, type, detail) VALUES (?, ?, ?)",
        (username.strip().lstrip("@"), eng_type, detail),
    )
    conn.commit()
    conn.close()


def get_engagements(eng_type=None, limit=200):
    conn = get_connection()
    if eng_type:
        rows = conn.execute(
            "SELECT * FROM engagements WHERE type=? ORDER BY id DESC LIMIT ?",
            (eng_type, limit),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM engagements ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_engagement_stats():
    conn = get_connection()
    total_sent = conn.execute("SELECT COUNT(*) as cnt FROM accounts WHERE status='sent'").fetchone()["cnt"]
    rows = conn.execute("SELECT type, COUNT(DISTINCT username) as cnt FROM engagements GROUP BY type").fetchall()
    conn.close()
    stats = {r["type"]: r["cnt"] for r in rows}
    stats["total_sent"] = total_sent
    fb = stats.get("follow_back", 0)
    stats["follow_back_rate"] = (fb / total_sent * 100) if total_sent > 0 else 0
    lk = stats.get("like", 0)
    stats["like_rate"] = (lk / total_sent * 100) if total_sent > 0 else 0
    return stats


def get_engaged_usernames():
    """反応があったユーザー名のセットを返す"""
    conn = get_connection()
    rows = conn.execute("SELECT DISTINCT username FROM engagements").fetchall()
    conn.close()
    return {r["username"] for r in rows}


def get_engagement_by_username(username):
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM engagements WHERE username=? ORDER BY detected_at",
        (username.strip().lstrip("@"),),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# --- Learning Log ---

def save_learning_log(date, summary, insights, stats):
    conn = get_connection()
    conn.execute("""
        INSERT INTO learning_log (date, summary, insights, follow_back_rate, like_rate,
            total_sent, total_follow_back, total_like)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        date, summary, insights,
        stats.get("follow_back_rate", 0), stats.get("like_rate", 0),
        stats.get("total_sent", 0), stats.get("follow_back", 0), stats.get("like", 0),
    ))
    conn.commit()
    conn.close()


def get_learning_logs(limit=30):
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM learning_log ORDER BY id DESC LIMIT ?", (limit,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]
