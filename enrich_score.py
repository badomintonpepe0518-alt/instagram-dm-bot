#!/usr/bin/env python3
"""
プロフィール情報取得＆スコアリング
pending のうち未取得アカウントの web_profile_info を取得し、
親和性・返信率・予約見込みの観点からスコアを付ける。

スコアリング観点:
  +++ パリ関連キーワード(挙式/前撮り/旅行/ハネムーン)
  ++  結婚式/新婚/プレ花嫁/フォトウェディング
  ++  ハネムーン/新婚旅行
  +   旅行好き/カップル
  +   フォロワー 100-3000（返信率が高いゾーン）
  +   投稿数 5件以上（アクティブ）
  -   フォロワー >10000（返信率低下）
  -   ビジネスアカウント
  -   フォロワー <50（捨て垢率高）
  -   外部リンク (店舗/ブランド疑い)

score >= 5 のみ pending 維持、それ未満は scored_low に。
"""
import sys, os, time, random, json, logging, re
sys.path.insert(0, os.path.dirname(__file__))

import requests
import sqlite3
from datetime import datetime

logging.basicConfig(
    filename=os.path.join(os.path.dirname(__file__), 'logs', 'enrich_score.log'),
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(message)s'
)
log = logging.getLogger(__name__)

DB_PATH = os.path.join(os.path.dirname(__file__), 'data', 'instagram_dm.db')
COOKIE_PATH = os.path.join(os.path.dirname(__file__), 'data', 'ig_cookies.json')

HEADERS = {
    'X-IG-App-ID': '936619743392459',
    'X-Requested-With': 'XMLHttpRequest',
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
}

# 超強シグナル（予約直結）
PARIS_STRONG = [
    'パリ挙式', 'パリ前撮り', 'パリフォト', 'パリウェディング',
    'パリ旅行', 'パリハネムーン', 'パリ新婚旅行', 'パリ婚',
    '#パリ挙式', '#パリ前撮り', '#パリ旅行',
    'paris wedding', 'paris honeymoon', 'paris photoshoot',
]

# 強シグナル（検討層）
WEDDING_STRONG = [
    '前撮り', 'フォトウェディング', 'プレ花嫁', '卒花',
    '結婚式準備', '挙式', '入籍', '婚約',
    'wedding', 'bride', 'プロポーズ', 'marry', 'fiance',
    '#プレ花嫁', '#卒花嫁', '#前撮り',
]

# 中シグナル（親和性）
TRAVEL_SIGNAL = [
    'ハネムーン', '新婚旅行', '海外旅行', '海外挙式',
    'honeymoon', 'travel', 'trip', '旅行好き',
    'カップル', 'couple', 'デート',
]

# 日付パターン (2026, 2027 が bio にあると結婚式日付の可能性高)
DATE_PATTERN = re.compile(r'202[6-9][.\-/年]?(0?[1-9]|1[0-2])')

# 除外（enrime時点でもベンダーは落とす）
# 注意: '公式' は「公式アンバサダー」等に誤マッチするので使わない
# 'official' も 'officially engaged' に誤マッチの可能性あり
BAN_WORDS = [
    'shop', 'store', '_studio', '.studio', 'studio_',
    '_salon', '.salon', 'salon_',
    '_atelier', '.atelier', 'atelier_',
    'clinic', 'magazine', '(株)', '株式会社',
    'アフィリ', 'ダイエット垢', 'ビジネス案件',
    '集客コンサル', '副業', 'マッチングアプリ運営',
]


def get_session():
    session = requests.Session()
    with open(COOKIE_PATH) as f:
        cookies = json.load(f)
    for name, value in cookies.items():
        session.cookies.set(name, value, domain='.instagram.com')
    session.headers.update(HEADERS)
    return session


def fetch_profile(session, username):
    try:
        r = session.get(
            f'https://www.instagram.com/api/v1/users/web_profile_info/?username={username}',
            timeout=15
        )
        if r.status_code != 200:
            return None
        d = r.json()
        return d.get('data', {}).get('user')
    except Exception as e:
        log.error(f"@{username} fetch失敗: {e}")
        return None


def score_profile(user):
    """profile dict からスコアを計算。(score, reason) を返す"""
    bio = (user.get('biography') or '').lower()
    full = (user.get('full_name') or '').lower()
    combined = bio + ' ' + full

    followers = user.get('edge_followed_by', {}).get('count', 0)
    following = user.get('edge_follow', {}).get('count', 0)
    posts = user.get('edge_owner_to_timeline_media', {}).get('count', 0)
    is_business = user.get('is_business_account', False)
    is_private = user.get('is_private', False)
    is_verified = user.get('is_verified', False)
    external = user.get('external_url') or ''

    score = 0
    reasons = []

    # 除外シグナル（即0点）
    for w in BAN_WORDS:
        if w in combined:
            return 0, f'ban:{w}'
    if is_private:
        return 0, 'private'
    if is_verified:
        return 0, 'verified'
    if is_business:
        score -= 3
        reasons.append('business-3')

    # パリ系（超強）
    for w in PARIS_STRONG:
        if w.lower() in combined:
            score += 10
            reasons.append(f'paris+10({w})')
            break

    # 結婚式系（強）
    wedding_hit = 0
    for w in WEDDING_STRONG:
        if w.lower() in combined:
            wedding_hit += 1
    if wedding_hit >= 2:
        score += 6
        reasons.append(f'wed+6({wedding_hit})')
    elif wedding_hit == 1:
        score += 4
        reasons.append('wed+4')

    # 旅行・カップル系
    travel_hit = 0
    for w in TRAVEL_SIGNAL:
        if w.lower() in combined:
            travel_hit += 1
    if travel_hit >= 2:
        score += 4
        reasons.append(f'travel+4({travel_hit})')
    elif travel_hit == 1:
        score += 2
        reasons.append('travel+2')

    # 日付（結婚式日付っぽい）
    if DATE_PATTERN.search(bio):
        score += 5
        reasons.append('date+5')

    # フォロワー数
    if 100 <= followers <= 1500:
        score += 3
        reasons.append('fol_sweet+3')
    elif 1500 < followers <= 3000:
        score += 2
        reasons.append('fol_ok+2')
    elif followers > 10000:
        score -= 3
        reasons.append('fol_big-3')
    elif followers < 50:
        score -= 3
        reasons.append('fol_tiny-3')

    # 投稿数（アクティブ指標）
    if posts >= 20:
        score += 2
        reasons.append('posts+2')
    elif posts >= 5:
        score += 1
        reasons.append('posts+1')
    elif posts < 3:
        score -= 3
        reasons.append('posts_dead-3')

    # フォロー:フォロワー比（スパムっぽいのを弾く）
    if followers > 0 and following / max(followers, 1) > 5:
        score -= 2
        reasons.append('spammy-2')

    # 外部リンクありはビジネス傾向
    if external and not is_business:
        score -= 1
        reasons.append('url-1')

    return score, ','.join(reasons)


def run(limit=60, min_score=5):
    os.makedirs(os.path.join(os.path.dirname(__file__), 'logs'), exist_ok=True)
    log.info("=== enrich&score 開始 ===")

    session = get_session()
    conn = sqlite3.connect(DB_PATH)

    # 未取得のpending を古い順に
    rows = conn.execute(
        "SELECT id, username FROM accounts WHERE status='pending' AND enriched_at IS NULL ORDER BY id LIMIT ?",
        (limit,)
    ).fetchall()
    log.info(f"対象: {len(rows)}件")

    kept, dropped, errors = 0, 0, 0
    for idx, (id_, username) in enumerate(rows, 1):
        user = fetch_profile(session, username)
        if user is None:
            errors += 1
            log.warning(f"[{idx}/{len(rows)}] @{username} 取得失敗")
            time.sleep(random.uniform(10, 18))
            continue

        score, reason = score_profile(user)
        bio = (user.get('biography') or '')[:500]
        full = user.get('full_name') or ''
        followers = user.get('edge_followed_by', {}).get('count', 0)
        posts = user.get('edge_owner_to_timeline_media', {}).get('count', 0)
        is_business = 1 if user.get('is_business_account') else 0

        new_status = 'pending' if score >= min_score else 'skipped'
        conn.execute(
            """UPDATE accounts SET
                score=?, followers=?, posts=?, bio=?, full_name=?,
                is_business=?, enriched_at=datetime('now','localtime'),
                score_reason=?, status=?
               WHERE id=?""",
            (score, followers, posts, bio, full, is_business, reason, new_status, id_)
        )
        conn.commit()

        if new_status == 'pending':
            kept += 1
        else:
            dropped += 1

        log.info(f"[{idx}/{len(rows)}] @{username} score={score} f={followers} p={posts} -> {new_status} ({reason})")
        print(f"[{idx}/{len(rows)}] @{username:25} score={score:3} f={followers:5} p={posts:4} -> {new_status}")

        # レート制限対策
        time.sleep(random.uniform(8, 14))

    conn.close()
    log.info(f"=== 完了: kept={kept} dropped={dropped} errors={errors} ===")
    print(f'\n完了: 維持={kept} 除外={dropped} エラー={errors}')


if __name__ == '__main__':
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument('--limit', type=int, default=60)
    ap.add_argument('--min-score', type=int, default=5)
    args = ap.parse_args()
    run(limit=args.limit, min_score=args.min_score)
