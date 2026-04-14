#!/usr/bin/env python3
"""
自動候補収集スクリプト
2時間ごとにcronで実行し、新しいDM候補アカウントをDBに追加する。
Chromeのinstagramセッションcookieを使ってAPI呼び出し。
"""
import sys, os, time, random, json, logging
sys.path.insert(0, os.path.dirname(__file__))

import requests
import sqlite3
from datetime import datetime, timedelta

logging.basicConfig(
    filename=os.path.join(os.path.dirname(__file__), 'logs', 'auto_collect.log'),
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(message)s'
)
log = logging.getLogger(__name__)

DB_PATH = os.path.join(os.path.dirname(__file__), 'data', 'instagram_dm.db')
HEADERS = {
    'X-IG-App-ID': '936619743392459',
    'X-Requested-With': 'XMLHttpRequest',
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
}

# シードアカウント（フォロー中リストを掘る対象）
# 花嫁系 + 旅行系カップル/パリ旅行者
SEED_ACCOUNTS = [
    # 花嫁系
    'm.k.n0718', 'aya_wedding08', 'yun_wd_622', 'wd_sm27', 'wd__2_mori',
    'zuudesu0111', 'y_wd_mm', 'mri_wd2608', '__n1029_wd', 'hiroruri._.202524',
    'urimuuuchama', 'natsu_classica_2026',
    # 旅行系カップル・パリ旅行者
    'acouplethattravels',  # 日本人×ペルー人 旅行カップル
    'pinkyuca',            # パリ旅行お助け人
    'mi_diary_1',          # カフェ・旅行好き
    'hase__world',         # 世界一周
    'sekaspe',             # 海外カップル
]

VENDOR_WORDS = [
    'studio', 'photo', 'bridal', 'dress', 'venue', 'planner', 'atelier',
    'couture', 'cook', 'florist', 'flower_shop', 'camera', 'film', 'video',
    'chapel', 'hotel', 'ring', 'jewel', 'nail', 'salon', 'eyelash',
    'official', 'magazine', 'design', 'illustration', 'illust', 'shaving',
    'bodymake', 'sewing', 'gift_', 'bouquet', 'channel', 'calligraphy',
    'piece_', 'calme', 'cocosab', 'mimosa', 'litz_', 'silk',
]

# vivea.paris___のフォロワーリスト（除外対象）キャッシュファイル
VIVEA_CACHE = os.path.join(os.path.dirname(__file__), 'data', 'vivea_followers.json')


COOKIE_PATH = os.path.join(os.path.dirname(__file__), 'data', 'ig_cookies.json')


def get_session():
    """保存済みcookieファイルからrequestsセッションを作る"""
    session = requests.Session()
    try:
        with open(COOKIE_PATH) as f:
            cookies = json.load(f)
        for name, value in cookies.items():
            session.cookies.set(name, value, domain='.instagram.com')
    except Exception as e:
        log.error(f"Cookie読み込み失敗: {e}")
        return None
    session.headers.update(HEADERS)
    return session


def get_existing_usernames():
    """DBにある全ユーザー名を取得"""
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute("SELECT username FROM accounts").fetchall()
    conn.close()
    return set(r[0] for r in rows)


def add_to_db(usernames):
    """ユーザー名リストをDBに追加"""
    if not usernames:
        return 0
    conn = sqlite3.connect(DB_PATH)
    added = 0
    for u in usernames:
        try:
            conn.execute("INSERT OR IGNORE INTO accounts (username) VALUES (?)", (u,))
            added += conn.total_changes
        except Exception:
            pass
    conn.commit()
    actual = conn.execute("SELECT changes()").fetchone()
    conn.close()
    log.info(f"DB追加: {len(usernames)}件中 {added}件")
    return added


def get_user_id(session, username):
    """ユーザー名からIDを取得"""
    try:
        r = session.get(
            f'https://www.instagram.com/api/v1/users/web_profile_info/?username={username}',
            timeout=15
        )
        if r.status_code != 200:
            return None
        d = r.json()
        user = d.get('data', {}).get('user')
        if not user:
            return None
        return user.get('id'), user.get('is_private', True)
    except Exception as e:
        log.error(f"プロフィール取得失敗 @{username}: {e}")
        return None


def get_following(session, user_id, max_pages=3):
    """フォロー中リストをGraphQL APIで取得"""
    query_hash = 'd04b0a864b4b54837c0d870b0e77e076'
    all_users = []
    cursor = None

    for page in range(max_pages):
        variables = {'id': user_id, 'first': 50}
        if cursor:
            variables['after'] = cursor

        try:
            r = session.get(
                'https://www.instagram.com/graphql/query/',
                params={'query_hash': query_hash, 'variables': json.dumps(variables)},
                timeout=20
            )
            if r.status_code != 200:
                log.warning(f"GraphQL {r.status_code}")
                break
            d = r.json()
            edges = d.get('data', {}).get('user', {}).get('edge_follow', {}).get('edges', [])
            page_info = d.get('data', {}).get('user', {}).get('edge_follow', {}).get('page_info', {})

            for e in edges:
                node = e['node']
                all_users.append({
                    'username': node['username'],
                    'is_private': node.get('is_private', True),
                    'full_name': node.get('full_name', '')
                })

            if not page_info.get('has_next_page'):
                break
            cursor = page_info.get('end_cursor')

        except Exception as e:
            log.error(f"フォローリスト取得失敗: {e}")
            break

        # レート制限回避（サーバー負荷軽減）
        time.sleep(random.uniform(8, 15))

    return all_users


def get_followers(session, user_id, max_pages=1):
    """フォロワーリストをGraphQL APIで取得（旅行系シードのフォロワーを掘る用）"""
    query_hash = 'c76146de99bb02f6415203be841dd25a'
    all_users = []
    cursor = None

    for page in range(max_pages):
        variables = {'id': user_id, 'first': 50}
        if cursor:
            variables['after'] = cursor

        try:
            r = session.get(
                'https://www.instagram.com/graphql/query/',
                params={'query_hash': query_hash, 'variables': json.dumps(variables)},
                timeout=20
            )
            if r.status_code != 200:
                break
            d = r.json()
            edges = d.get('data', {}).get('user', {}).get('edge_followed_by', {}).get('edges', [])
            page_info = d.get('data', {}).get('user', {}).get('edge_followed_by', {}).get('page_info', {})

            for e in edges:
                node = e['node']
                all_users.append({
                    'username': node['username'],
                    'is_private': node.get('is_private', True),
                    'full_name': node.get('full_name', '')
                })

            if not page_info.get('has_next_page'):
                break
            cursor = page_info.get('end_cursor')

        except Exception as e:
            log.error(f"フォロワーリスト取得失敗: {e}")
            break

        time.sleep(random.uniform(8, 15))

    return all_users


# 旅行系シード（フォロワーを掘る対象）
TRAVEL_FOLLOWER_SEEDS = ['pinkyuca', 'meru_france', 'sea_fly_paris']


def is_vendor(username, full_name):
    """ベンダーかどうか判定"""
    combined = (username + ' ' + full_name).lower()
    return any(w in combined for w in VENDOR_WORDS)


def get_vivea_followers():
    """vivea.paris___のフォロワーリストをキャッシュから取得"""
    try:
        with open(VIVEA_CACHE) as f:
            return set(json.load(f))
    except Exception:
        return set()


def get_dm_users():
    """DM済みユーザーリストを取得"""
    try:
        dm_path = os.path.join(os.path.dirname(__file__), 'data', 'dm_users.json')
        with open(dm_path) as f:
            return set(json.load(f))
    except Exception:
        return set()


def filter_candidates(users, existing):
    """候補をフィルタ（ベンダー、vivea followers、DM済みを除外）"""
    vivea = get_vivea_followers()
    dm_users = get_dm_users()
    candidates = []
    seen = set()
    for u in users:
        name = u['username']
        if name in existing or name in seen:
            continue
        if u['is_private']:
            continue
        if is_vendor(name, u.get('full_name', '')):
            continue
        if name in vivea:
            continue
        if name in dm_users:
            continue
        seen.add(name)
        candidates.append(name)
    return candidates


def run():
    """メイン処理"""
    os.makedirs(os.path.join(os.path.dirname(__file__), 'logs'), exist_ok=True)
    log.info("=== 自動候補収集開始 ===")

    session = get_session()
    if not session:
        log.error("セッション作成失敗。終了。")
        return

    existing = get_existing_usernames()
    log.info(f"既存アカウント数: {len(existing)}")

    # ランダムにシードを1つ選んで掘る（サーバー負荷軽減）
    # 50%の確率で旅行系フォロワーシードを使う
    all_candidates = []
    use_travel = random.random() < 0.5 and TRAVEL_FOLLOWER_SEEDS

    if use_travel:
        seed = random.choice(TRAVEL_FOLLOWER_SEEDS)
        log.info(f"旅行系シード（フォロワー）: @{seed}")
        result = get_user_id(session, seed)
        if result:
            user_id, is_private = result
            time.sleep(random.uniform(5, 10))
            users = get_followers(session, user_id, max_pages=1)
            log.info(f"@{seed} のフォロワー: {len(users)}件取得")
            candidates = filter_candidates(users, existing)
            all_candidates.extend(candidates)
            existing.update(candidates)
    else:
        seed = random.choice(SEED_ACCOUNTS)
        log.info(f"シード（フォロー中）: @{seed}")
        result = get_user_id(session, seed)
        if result:
            user_id, is_private = result
            if is_private:
                log.warning(f"@{seed} は非公開")
            else:
                time.sleep(random.uniform(5, 10))
                following = get_following(session, user_id, max_pages=1)
                log.info(f"@{seed} のフォロー中: {len(following)}件取得")
                candidates = filter_candidates(following, existing)
                all_candidates.extend(candidates)
                existing.update(candidates)

    if all_candidates:
        added = add_to_db(all_candidates)
        log.info(f"新規候補 {len(all_candidates)}件 → DB追加 {added}件")
    else:
        log.info("新規候補なし")

    # 最終カウント
    conn = sqlite3.connect(DB_PATH)
    counts = conn.execute("SELECT status, COUNT(*) FROM accounts GROUP BY status").fetchall()
    conn.close()
    log.info(f"現在のDB状態: {dict(counts)}")
    log.info("=== 自動候補収集完了 ===")


if __name__ == '__main__':
    run()
