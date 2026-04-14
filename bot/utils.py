from __future__ import annotations

import csv
import io
import re
import glob
import os
from typing import Optional


def parse_csv_usernames(file_content) -> list:
    if isinstance(file_content, bytes):
        file_content = file_content.decode("utf-8")
    reader = csv.DictReader(io.StringIO(file_content))
    usernames = []
    for row in reader:
        username = row.get("username", "").strip().lstrip("@")
        if username:
            usernames.append(username)
    return usernames


def parse_html_usernames(html_content) -> list:
    """chuly_paris_outreach_*.html からユーザー名を抽出"""
    if isinstance(html_content, bytes):
        html_content = html_content.decode("utf-8")
    # instagram://user?username=xxx or instagram.com/xxx のパターンを抽出
    usernames = re.findall(r'instagram://user\?username=([a-zA-Z0-9_.]+)', html_content)
    if not usernames:
        # フォールバック: @username パターン
        usernames = re.findall(r'@([a-zA-Z0-9_.]+)', html_content)
    return list(dict.fromkeys(usernames))  # 重複除去（順序保持）


def find_outreach_html_files(search_dirs=None) -> list:
    """ワークスペース内のchuly_paris_outreach_*.htmlを検索"""
    if search_dirs is None:
        search_dirs = [
            os.path.expanduser("~"),
            os.path.expanduser("~/Desktop"),
            os.path.expanduser("~/Documents"),
            os.path.expanduser("~/Downloads"),
        ]
    found = []
    for d in search_dirs:
        pattern = os.path.join(d, "chuly_paris_outreach_*.html")
        for f in glob.glob(pattern):
            found.append({
                "path": f,
                "name": os.path.basename(f),
                "mtime": os.path.getmtime(f),
            })
    found.sort(key=lambda x: x["mtime"], reverse=True)
    return found
