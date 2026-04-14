#!/usr/bin/env python3
"""PC上のSQLiteデータをCSVにエクスポートし、GitHubにpushしてクラウドと同期する"""
import sqlite3
import csv
import os
import subprocess
from datetime import datetime

BASE_DIR = os.path.dirname(__file__)
DB_PATH = os.path.join(BASE_DIR, 'data', 'instagram_dm.db')
DATA_DIR = os.path.join(BASE_DIR, 'data')

TABLES = {
    'accounts': ['id', 'username', 'status', 'sent_at', 'created_at',
                  'score', 'followers', 'posts', 'bio', 'full_name',
                  'is_business', 'enriched_at', 'score_reason'],
    'templates': ['id', 'name', 'body', 'is_active', 'created_at'],
    'engagements': ['id', 'username', 'type', 'detail', 'detected_at'],
    'learning_log': ['id', 'date', 'summary', 'insights', 'follow_back_rate',
                     'like_rate', 'total_sent', 'total_follow_back', 'total_like', 'created_at'],
}


def export_csvs():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    for table, cols in TABLES.items():
        rows = conn.execute(f"SELECT * FROM {table}").fetchall()
        path = os.path.join(DATA_DIR, f"{table}.csv")
        with open(path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=cols)
            writer.writeheader()
            for r in rows:
                d = dict(r)
                writer.writerow({c: d.get(c, '') for c in cols})
        print(f"  {table}: {len(rows)} rows -> {path}")
    conn.close()


def git_push():
    os.chdir(BASE_DIR)
    subprocess.run(['git', 'add', 'data/accounts.csv', 'data/templates.csv',
                    'data/engagements.csv', 'data/learning_log.csv'], check=True)
    result = subprocess.run(['git', 'diff', '--cached', '--quiet'])
    if result.returncode == 0:
        print("  No changes to push.")
        return
    now = datetime.now().strftime('%Y-%m-%d %H:%M')
    subprocess.run(['git', 'commit', '-m', f'sync: data update {now}'], check=True)
    subprocess.run(['git', 'push'], check=True)
    print("  Pushed to GitHub.")


if __name__ == '__main__':
    print(f"[{datetime.now().strftime('%H:%M:%S')}] Syncing DB to cloud...")
    export_csvs()
    git_push()
    print("Done.")
