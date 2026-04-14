"""
全アカウントをブラウザでチェックして、問題のあるものをskippedにするスクリプト。
Chrome MCPからは使えないので、結果を手動で適用する。
"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from db.database import get_accounts, update_account_status

accounts = get_accounts(status="pending")
print(f"チェック対象: {len(accounts)}件")
for a in accounts:
    print(a["username"])
