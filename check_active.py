"""
各pendingアカウントのアクティブ度をチェックするヘルパー。
Chrome MCP経由で1件ずつプロフィール→投稿→日付を確認する。
結果をJSONで出力。
"""
# This script outputs the list of pending usernames for the Chrome MCP check loop
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from db.database import get_accounts

pending = get_accounts(status="pending")
for a in pending:
    print(a["username"])
