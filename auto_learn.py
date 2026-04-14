#!/usr/bin/env python3
"""
自動学習・分析スクリプト
毎日20時にlaunchdで実行。
1. chuly.parisのフォロワーからフォローバック検出
2. DMインボックスからDM返信検出
3. スコア別の反応率分析 → 学習ログ保存
"""
import sys, os, time, json, logging, random
sys.path.insert(0, os.path.dirname(__file__))

import requests
import sqlite3
from datetime import datetime

logging.basicConfig(
    filename=os.path.join(os.path.dirname(__file__), 'logs', 'auto_learn.log'),
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(message)s'
)
log = logging.getLogger(__name__)

DB_PATH = os.path.join(os.path.dirname(__file__), 'data', 'instagram_dm.db')
COOKIE_PATH = os.path.join(os.path.dirname(__file__), 'data', 'ig_cookies.json')
VIVEA_CACHE = os.path.join(os.path.dirname(__file__), 'data', 'vivea_followers.json')
HEADERS = {
    'X-IG-App-ID': '936619743392459',
    'X-Requested-With': 'XMLHttpRequest',
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
}

CHULY_USER_ID = None


def get_session():
    session = requests.Session()
    try:
        with open(COOKIE_PATH) as f:
            cookies = json.load(f)
        for name, value in cookies.items():
            session.cookies.set(name, value, domain='.instagram.com')
        session.headers.update(HEADERS)
        session.headers['X-CSRFToken'] = cookies.get('csrftoken', '')
    except Exception as e:
        log.error(f"Cookie読み込み失敗: {e}")
        return None
    return session


def get_chuly_followers(session, max_pages=100):
    """chuly.parisの全フォロワーを取得（キャッシュ更新も兼ねる）"""
    global CHULY_USER_ID
    if not CHULY_USER_ID:
        try:
            r = session.get(
                'https://www.instagram.com/api/v1/users/web_profile_info/?username=chuly.paris',
                timeout=15
            )
            d = r.json()
            CHULY_USER_ID = d['data']['user']['id']
        except Exception as e:
            log.error(f"chuly.paris ID取得失敗: {e}")
            return set()

    query_hash = 'c76146de99bb02f6415203be841dd25a'
    followers = set()
    cursor = None

    for page in range(max_pages):
        variables = {'id': CHULY_USER_ID, 'first': 50}
        if cursor:
            variables['after'] = cursor
        try:
            r = session.get(
                'https://www.instagram.com/graphql/query/',
                params={'query_hash': query_hash, 'variables': json.dumps(variables)},
                timeout=20
            )
            if r.status_code != 200:
                log.warning(f"フォロワー取得 page{page+1} status={r.status_code}")
                break
            d = r.json()
            edges = d.get('data', {}).get('user', {}).get('edge_followed_by', {}).get('edges', [])
            page_info = d.get('data', {}).get('user', {}).get('edge_followed_by', {}).get('page_info', {})

            for e in edges:
                followers.add(e['node']['username'])

            if not page_info.get('has_next_page'):
                break
            cursor = page_info.get('end_cursor')
        except Exception as e:
            log.error(f"フォロワー取得失敗: {e}")
            break
        time.sleep(random.uniform(8, 15))

    # キャッシュ更新
    if followers:
        try:
            with open(VIVEA_CACHE, 'w') as f:
                json.dump(sorted(followers), f, ensure_ascii=False)
            log.info(f"vivea_followers.json 更新: {len(followers)}件")
        except Exception:
            pass

    return followers


def get_dm_reply_users(session, max_pages=30):
    """DMインボックスからchuly.parisにメッセージを返してきたユーザーを検出"""
    reply_users = set()
    cursor = None

    for page in range(max_pages):
        params = {'limit': 20}
        if cursor:
            params['cursor'] = cursor
        try:
            r = session.get(
                'https://www.instagram.com/api/v1/direct_v2/inbox/',
                params=params, timeout=15
            )
            if r.status_code != 200:
                log.warning(f"DM inbox page{page+1} status={r.status_code}")
                break
            d = r.json()
            inbox = d.get('inbox', {})
            threads = inbox.get('threads', [])
            if not threads:
                break

            my_user_id = d.get('viewer', {}).get('pk')

            for t in threads:
                users = t.get('users', [])
                if not users:
                    continue
                other_user = users[0].get('username', '')

                # last_permanent_item で最後のメッセージ送信者を確認
                last_item = t.get('last_permanent_item', {})
                last_sender = last_item.get('user_id')

                # 相手が最後に送ったメッセージなら返信あり
                if last_sender and str(last_sender) != str(my_user_id):
                    reply_users.add(other_user)

            if not inbox.get('has_older'):
                break
            cursor = inbox.get('oldest_cursor')
        except Exception as e:
            log.error(f"DM inbox取得失敗: {e}")
            break
        time.sleep(5)

    return reply_users


def get_sent_accounts():
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute(
        "SELECT username, score, score_reason FROM accounts WHERE status='sent'"
    ).fetchall()
    conn.close()
    return rows


def get_existing_engagements():
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute(
        "SELECT username, type FROM engagements"
    ).fetchall()
    conn.close()
    existing = {}
    for username, eng_type in rows:
        existing.setdefault(username, set()).add(eng_type)
    return existing


def record_engagement(username, eng_type, detail=None):
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "INSERT INTO engagements (username, type, detail) VALUES (?, ?, ?)",
        (username, eng_type, detail)
    )
    conn.commit()
    conn.close()


def save_learning_log(summary, insights, stats):
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        INSERT INTO learning_log (date, total_sent, total_follow_back, total_like,
            follow_back_rate, like_rate, summary, insights)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        datetime.now().strftime("%Y-%m-%d"),
        stats['total_sent'],
        stats['follow_back'],
        stats['like'],
        stats['fb_rate'],
        stats['like_rate'],
        summary,
        insights
    ))
    conn.commit()
    conn.close()


def analyze_score_effectiveness(sent_accounts, followers, reply_users):
    """スコア帯別の反応率を分析"""
    buckets = {'15+': {'sent': 0, 'fb': 0, 'reply': 0},
               '10-14': {'sent': 0, 'fb': 0, 'reply': 0},
               '5-9': {'sent': 0, 'fb': 0, 'reply': 0},
               'unscored': {'sent': 0, 'fb': 0, 'reply': 0}}

    for username, score, reason in sent_accounts:
        if score is None:
            bucket = 'unscored'
        elif score >= 15:
            bucket = '15+'
        elif score >= 10:
            bucket = '10-14'
        else:
            bucket = '5-9'

        buckets[bucket]['sent'] += 1
        if username in followers:
            buckets[bucket]['fb'] += 1
        if username in reply_users:
            buckets[bucket]['reply'] += 1

    # シグナル別の反応率
    signal_stats = {}
    for username, score, reason in sent_accounts:
        if not reason:
            continue
        tags = [t.split('+')[0].split('-')[0] for t in reason.split(',')]
        for tag in tags:
            tag = tag.strip()
            if not tag:
                continue
            signal_stats.setdefault(tag, {'sent': 0, 'fb': 0, 'reply': 0})
            signal_stats[tag]['sent'] += 1
            if username in followers:
                signal_stats[tag]['fb'] += 1
            if username in reply_users:
                signal_stats[tag]['reply'] += 1

    return buckets, signal_stats


def run():
    os.makedirs(os.path.join(os.path.dirname(__file__), 'logs'), exist_ok=True)
    log.info("=== 自動学習・分析開始 ===")

    session = get_session()
    if not session:
        log.error("セッション作成失敗。終了。")
        return

    # 1. chuly.parisのフォロワーを全取得
    log.info("chuly.paris フォロワー取得中...")
    followers = get_chuly_followers(session)
    log.info(f"chuly.paris フォロワー数: {len(followers)}")

    # 2. DM返信ユーザーを検出
    log.info("DM返信ユーザー検出中...")
    reply_users = get_dm_reply_users(session)
    log.info(f"DM返信ユーザー数: {len(reply_users)}")

    # 3. 送信済みアカウントと照合
    sent_accounts = get_sent_accounts()
    existing_eng = get_existing_engagements()

    new_fb = []
    new_reply = []

    for username, score, reason in sent_accounts:
        existing_types = existing_eng.get(username, set())

        # フォローバック検出
        if username in followers and 'follow_back' not in existing_types:
            new_fb.append(username)
            record_engagement(username, 'follow_back',
                              f'自動検出 score={score} {reason or ""}')
            log.info(f"新規フォローバック: @{username} (score={score})")

        # DM返信検出
        if username in reply_users and 'dm_reply' not in existing_types:
            new_reply.append(username)
            record_engagement(username, 'dm_reply',
                              f'自動検出 score={score} {reason or ""}')
            log.info(f"新規DM返信: @{username} (score={score})")

    # 4. 統計計算
    conn = sqlite3.connect(DB_PATH)
    total_sent = conn.execute("SELECT COUNT(*) FROM accounts WHERE status='sent'").fetchone()[0]
    total_fb = conn.execute("SELECT COUNT(*) FROM engagements WHERE type='follow_back'").fetchone()[0]
    total_like = conn.execute("SELECT COUNT(*) FROM engagements WHERE type='like'").fetchone()[0]
    total_reply = conn.execute("SELECT COUNT(*) FROM engagements WHERE type='dm_reply'").fetchone()[0]
    conn.close()

    fb_rate = (total_fb / total_sent * 100) if total_sent > 0 else 0
    like_rate = (total_like / total_sent * 100) if total_sent > 0 else 0
    reply_rate = (total_reply / total_sent * 100) if total_sent > 0 else 0

    stats = {
        'total_sent': total_sent,
        'follow_back': total_fb,
        'like': total_like,
        'fb_rate': fb_rate,
        'like_rate': like_rate,
    }

    # 5. スコア帯別分析
    buckets, signal_stats = analyze_score_effectiveness(sent_accounts, followers, reply_users)

    # 6. 学習ログ作成
    summary_parts = [
        f"送信{total_sent}件",
        f"FB{total_fb}件({fb_rate:.1f}%)",
        f"DM返信{total_reply}件({reply_rate:.1f}%)",
        f"いいね{total_like}件({like_rate:.1f}%)",
    ]
    if new_fb:
        summary_parts.append(f"本日新規FB: {', '.join(new_fb[:10])}")
    if new_reply:
        summary_parts.append(f"本日新規返信: {', '.join(new_reply[:10])}")
    summary = '。'.join(summary_parts)

    # インサイト生成
    insights_parts = []

    # スコア帯別
    for bucket_name, data in buckets.items():
        if data['sent'] > 0:
            rate = data['fb'] / data['sent'] * 100
            rr = data['reply'] / data['sent'] * 100
            insights_parts.append(
                f"スコア{bucket_name}: 送信{data['sent']}件 FB率{rate:.1f}% 返信率{rr:.1f}%"
            )

    # 効果が高いシグナルTOP3
    signal_by_rate = []
    for tag, data in signal_stats.items():
        if data['sent'] >= 3:
            rate = (data['fb'] + data['reply']) / data['sent'] * 100
            signal_by_rate.append((tag, rate, data['sent']))
    signal_by_rate.sort(key=lambda x: -x[1])

    if signal_by_rate:
        top_signals = signal_by_rate[:3]
        insights_parts.append(
            "反応率TOP: " + ", ".join(f"{t}({r:.0f}%,n={n})" for t, r, n in top_signals)
        )

    # 推奨事項
    if fb_rate > 5:
        insights_parts.append("→ FB率好調。現在のターゲティング継続。")
    elif total_sent > 50 and fb_rate < 2:
        insights_parts.append("→ FB率低め。高スコアアカウント（paris/date/wed系）に集中を推奨。")

    if total_reply > 0 and reply_rate > 3:
        insights_parts.append("→ DM返信率良好。DM文面は効果的。")

    insights = '\n'.join(insights_parts) if insights_parts else None

    save_learning_log(summary, insights, stats)
    log.info(f"統計: {summary}")
    log.info(f"インサイト: {insights}")
    log.info("=== 自動学習・分析完了 ===")


if __name__ == '__main__':
    run()
