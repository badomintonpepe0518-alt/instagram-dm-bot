import sys
import os
import json

sys.path.insert(0, os.path.dirname(__file__))

import streamlit as st
import streamlit.components.v1 as components
import pandas as pd
from db.database import (
    init_db,
    add_accounts,
    get_accounts,
    get_account_counts,
    update_account_status,
    delete_all_accounts,
    reset_accounts,
    get_active_template,
    save_template,
    update_template,
    add_engagement,
    get_engagements,
    get_engagement_stats,
    get_engagement_by_username,
    get_learning_logs,
)
from bot.utils import parse_csv_usernames

init_db()

st.set_page_config(page_title="chuly.paris DM営業ツール", page_icon="📩", layout="wide")

# モバイル対応CSS
st.markdown("""
<style>
@media (max-width: 768px) {
    .block-container { padding: 1rem 0.5rem !important; }
    h1 { font-size: 1.3rem !important; }
    h2 { font-size: 1.1rem !important; }
    .stTabs [data-baseweb="tab-list"] { gap: 0px; }
    .stTabs [data-baseweb="tab"] { font-size: 0.8rem; padding: 0.5rem 0.3rem; }
    [data-testid="stSidebar"] { display: none; }
    .stDataFrame { font-size: 0.75rem; }
    div[data-testid="stMetric"] { padding: 0.3rem; }
    div[data-testid="stMetric"] label { font-size: 0.75rem !important; }
    div[data-testid="stMetric"] [data-testid="stMetricValue"] { font-size: 1.2rem !important; }
}
/* 送信ボタンを大きく */
.stButton > button { min-height: 3rem; font-size: 1rem; }
</style>
""", unsafe_allow_html=True)

st.title("📩 chuly.paris DM営業ツール")

# --- サイドバー: ステータス概要 ---
counts = get_account_counts()
eng_stats = get_engagement_stats()

st.sidebar.header("📊 ステータス")
st.sidebar.metric("合計", counts["total"])
col1, col2, col3 = st.sidebar.columns(3)
col1.metric("未送信", counts["pending"])
col2.metric("送信済", counts["sent"])
col3.metric("スキップ", counts["skipped"])

st.sidebar.divider()
st.sidebar.header("💡 反応率")
st.sidebar.metric("フォローバック率", f"{eng_stats['follow_back_rate']:.1f}%")
st.sidebar.metric("いいね率", f"{eng_stats['like_rate']:.1f}%")

st.sidebar.divider()
st.sidebar.caption("毎朝8時に自動で100件がDBに登録されます。\n反応チェックは毎日20時に自動実行されます。")

# --- タブ ---
tab_today, tab_list, tab_analytics, tab_template = st.tabs(
    ["📸 今日のリスト", "📋 アカウントリスト", "📈 学習・分析", "✉️ テンプレート"]
)

# ============================
# タブ0: 今日の高精度リスト
# ============================
with tab_today:
    st.header("📸 今日のDMリスト（高精度）")
    st.markdown("""
    <div style="background:#ffe0e0;padding:10px 16px;border-radius:8px;margin-bottom:8px;font-size:13px;color:#c0392b;font-weight:600;border:1px solid #e74c3c;">
        ⚠️ Instagramアプリが <b>@chuly.paris</b> になっているか確認してから送信！
    </div>
    """, unsafe_allow_html=True)

    # DM文面コピペ欄
    _DEFAULT_DM = """【予算10万円、舞台はパリ】

初めまして😌
私たちは、Vivéaがプロデュースする 私服のカジュアルフォトサービス
"Chuly（チュリー）"と申します📸

・パリの思い出を自然な形で残したい
・観光の合間に、無理なく撮影したい
・ご予算を抑えつつおしゃれに撮影をしたい

そんな方に向けて、 おふたりの特別なご旅行を "おふたりらしい形"で残すことを 大切にしています🕊️

予算は10万円からご案内可能です🤍

また、Chulyをディレクションしている「Vivéa（ヴィヴェア）」では、 パリを舞台にした前撮り撮影を中心に、 ウェディングムービーやオリジナルドレスのプランもご用意しております👗🎞️
https://www.instagram.com/vivea.paris___

ぜひパリでお会いできたら嬉しいです🇫🇷"""
    template = get_active_template()
    _dm_body = template["body"] if template else _DEFAULT_DM

    st.caption("精度スコア順に上位70件を表示。スコアリング済み。")

    # クエリパラメータでアクション処理（スマホからのフォールバック）
    _params = st.query_params
    _action = _params.get("action")
    _aid = _params.get("aid")
    if _action and _aid:
        try:
            _aid_int = int(_aid)
            if _action == "sent":
                update_account_status(_aid_int, "sent")
            elif _action == "skipped":
                update_account_status(_aid_int, "skipped")
        except Exception:
            pass
        st.query_params.clear()
        st.rerun()

    import sqlite3 as _sql
    _db = _sql.connect(os.path.join(os.path.dirname(__file__), 'data', 'instagram_dm.db'))
    _db.row_factory = _sql.Row

    # DM済みユーザーをロードしてリアルタイム除外
    _dm_path = os.path.join(os.path.dirname(__file__), 'data', 'dm_users.json')
    _dm_set = set()
    try:
        with open(_dm_path) as _f:
            _dm_set = set(json.load(_f))
    except Exception:
        pass

    _all_candidates = _db.execute("""
        SELECT id, username, score, followers, posts, bio, full_name, score_reason
        FROM accounts
        WHERE status='pending' AND score IS NOT NULL AND score >= 5
        ORDER BY score DESC
    """).fetchall()
    _top = [r for r in _all_candidates if r['username'] not in _dm_set][:70]

    _sent_today = _db.execute("""
        SELECT COUNT(*) FROM accounts
        WHERE status='sent' AND date(sent_at)=date('now','localtime')
    """).fetchone()[0]
    _db.close()

    if not _top:
        st.info("スコアリング済みの候補がありません。enrich_score.py を実行してください。")
    else:
        # 全カードを1つのcomponents.htmlで描画（scriptタグが使える）
        _cards_items = []
        for i, r in enumerate(_top, 1):
            u = r['username']
            acc_id = r['id']
            sc = r['score']
            fol = r['followers'] or 0
            po = r['posts'] or 0
            fn = (r['full_name'] or '').replace('<', '&lt;').replace('>', '&gt;').replace('{', '').replace('}', '').replace("'", "&#39;")

            if sc >= 15:
                bc = '#e74c3c'; bl = 'HOT'
            elif sc >= 10:
                bc = '#e67e22'; bl = 'HIGH'
            else:
                bc = '#3498db'; bl = 'OK'

            _cards_items.append(
                f'<div class="c" id="c{acc_id}">'
                f'<div class="r"><span class="n">{i}</span><div class="f">'
                f'<div class="u">@{u}</div>'
                f'<div class="m"><span style="background:{bc}" class="b">{bl} {sc}</span>'
                f'<span class="g">{fol:,}fol・{po}posts</span></div>'
                f'<div class="fn">{fn}</div>'
                f'</div></div>'
                f'<div class="btns">'
                f'<a class="btn bo" href="#" onclick="return oi(\'{u}\')">開く</a>'
                f'<a class="btn bs" href="#" onclick="return da({acc_id},\'sent\',this)">✅ 済</a>'
                f'<a class="btn bk" href="#" onclick="return da({acc_id},\'skipped\',this)">❌ 除外</a>'
                f'</div></div>'
            )

        _html_content = f'''<!DOCTYPE html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:-apple-system,BlinkMacSystemFont,'Helvetica Neue',sans-serif;background:transparent}}
.st{{background:#fff7f0;padding:10px 16px;border-radius:8px;margin-bottom:10px;font-size:13px;color:#c9a96e;font-weight:600}}
.c{{background:#fff;border-radius:12px;margin:6px 0;padding:12px 14px;box-shadow:0 1px 4px rgba(0,0,0,.07);transition:opacity .2s,max-height .3s,margin .3s,padding .3s;overflow:hidden;max-height:200px}}
.c.hide{{opacity:0;max-height:0;margin:0;padding:0}}
.r{{display:flex;align-items:center;gap:8px}}
.n{{font-size:13px;color:#bbb;font-weight:600;min-width:24px}}
.f{{flex:1;min-width:0}}
.u{{font-size:15px;font-weight:600;color:#222}}
.m{{font-size:11px;margin-top:2px}}
.b{{color:#fff;border-radius:4px;padding:1px 6px;font-size:10px;font-weight:700}}
.g{{color:#888;margin-left:4px}}
.fn{{font-size:12px;color:#666;margin-top:1px}}
.btns{{display:flex;gap:6px;margin-top:8px}}
.btn{{flex:1;text-align:center;border-radius:20px;padding:8px 0;font-size:13px;font-weight:600;text-decoration:none;color:#fff;display:block}}
.bo{{background:linear-gradient(135deg,#c9a96e,#e8c88a)}}
.bs{{background:#27ae60}}
.bk{{background:#95a5a6}}
.dm-box{{background:#f8f6f3;border:1px solid #e8e0d4;border-radius:12px;margin-bottom:12px;overflow:hidden}}
.dm-header{{display:flex;justify-content:space-between;align-items:center;padding:10px 14px;cursor:pointer}}
.dm-header h3{{font-size:14px;color:#c9a96e;margin:0}}
.dm-toggle{{font-size:12px;color:#999}}
.dm-body{{display:none;padding:0 14px 12px;font-size:13px;color:#333;white-space:pre-wrap;line-height:1.6}}
.dm-body.show{{display:block}}
.copy-btn{{display:block;margin:8px auto 0;background:linear-gradient(135deg,#c9a96e,#e8c88a);color:#fff;border:none;border-radius:20px;padding:10px 24px;font-size:14px;font-weight:600;cursor:pointer}}
.copy-btn.done{{background:#27ae60}}
</style></head><body>
<div class="dm-box">
<div class="dm-header" onclick="var b=this.nextElementSibling;b.classList.toggle('show');this.querySelector('.dm-toggle').textContent=b.classList.contains('show')?'▲':'▼'">
<h3>✉️ DM文面</h3><span class="dm-toggle">▼</span></div>
<div class="dm-body" id="dmt">{_dm_body.replace(chr(10),"<br>")}<br>
<button class="copy-btn" onclick="var t=document.getElementById('dmt').innerText;navigator.clipboard.writeText(t).then(function(){{var b=event.target;b.textContent='✅ コピーしました！';b.classList.add('done');setTimeout(function(){{b.textContent='📋 DM文面をコピー';b.classList.remove('done')}},2000)}})">📋 DM文面をコピー</button>
</div></div>
<div class="st">残 <span id="rc">{len(_top)}</span>件 ／ 今日送信済 <span id="sc">{_sent_today}</span>件 ／ スコア {_top[-1]["score"]}〜{_top[0]["score"]}点</div>
{"".join(_cards_items)}
<script>
function oi(u){{
  var app='instagram://user?username='+u;
  var web='https://www.instagram.com/'+u+'/';
  var w=window.open(app,'_blank');
  setTimeout(function(){{
    try{{if(!w||w.closed)window.top.location.href=web;}}catch(e){{window.top.location.href=web;}}
  }},1500);
  return false;
}}
function da(aid,action,el){{
  var c=el.closest('.c');
  c.classList.add('hide');
  window.top.location.href='?action='+action+'&aid='+aid;
  var rc=document.getElementById('rc');
  rc.textContent=parseInt(rc.textContent)-1;
  if(action==='sent'){{var sc=document.getElementById('sc');sc.textContent=parseInt(sc.textContent)+1;}}
  return false;
}}
</script>
</body></html>'''
        components.html(_html_content, height=len(_top) * 130 + 60, scrolling=True)



# ============================
# タブ2: アカウントリスト
# ============================
with tab_list:
    st.header("アカウントリスト管理")
    st.caption("毎朝8時にスケジュールタスクが自動で100件登録されます。")

    # アカウント一覧
    st.divider()
    st.subheader("登録済みアカウント")
    filter_status = st.selectbox("フィルター", ["すべて", "未送信", "送信済", "スキップ"])
    status_map = {"すべて": None, "未送信": "pending", "送信済": "sent", "スキップ": "skipped"}
    accounts = get_accounts(status=status_map[filter_status])

    if accounts:
        df = pd.DataFrame(accounts)
        st.dataframe(
            df[["id", "username", "status", "sent_at", "created_at"]],
            use_container_width=True,
            hide_index=True,
            column_config={
                "id": st.column_config.NumberColumn("ID", width="small"),
                "username": st.column_config.TextColumn("ユーザー名"),
                "status": st.column_config.TextColumn("ステータス"),
                "sent_at": st.column_config.TextColumn("送信日時"),
                "created_at": st.column_config.TextColumn("登録日時"),
            },
        )
    else:
        st.info("アカウントが登録されていません。")

    st.divider()
    col_reset, col_delete = st.columns(2)
    with col_reset:
        if st.button("🔄 全アカウントを未送信に戻す", use_container_width=True):
            reset_accounts()
            st.rerun()
    with col_delete:
        if st.button("🗑️ 全アカウントを削除", use_container_width=True, type="secondary"):
            delete_all_accounts()
            st.rerun()


# ============================
# タブ3: 学習・分析
# ============================
with tab_analytics:
    st.header("📈 学習・分析")

    # --- 反応サマリー ---
    st.subheader("反応サマリー")
    col_fb, col_lk, col_reply, col_total = st.columns(4)
    col_fb.metric("フォローバック", eng_stats.get("follow_back", 0),
                  f"{eng_stats['follow_back_rate']:.1f}%")
    col_lk.metric("いいね", eng_stats.get("like", 0),
                  f"{eng_stats['like_rate']:.1f}%")
    col_reply.metric("DM返信", eng_stats.get("dm_reply", 0))
    col_total.metric("DM送信数", eng_stats.get("total_sent", 0))

    # --- 反応の手動記録 ---
    st.divider()
    st.subheader("反応を記録")
    st.caption("フォローバックやいいねがあったら記録してください。自動チェックタスク（毎日20時）でも検出されます。")

    col_user, col_type = st.columns([2, 1])
    with col_user:
        eng_username = st.text_input("ユーザー名", placeholder="username", key="eng_user")
    with col_type:
        eng_type = st.selectbox("反応タイプ", [
            "follow_back", "like", "comment", "story_view", "dm_reply"
        ], format_func=lambda x: {
            "follow_back": "🔁 フォローバック",
            "like": "❤️ いいね",
            "comment": "💬 コメント",
            "story_view": "👁️ ストーリー閲覧",
            "dm_reply": "📩 DM返信",
        }[x], key="eng_type")

    eng_detail = st.text_input("詳細メモ（任意）", placeholder="例: プロフィールに旅行好きと記載", key="eng_detail")
    if st.button("📝 記録する", key="record_eng"):
        if eng_username.strip():
            add_engagement(eng_username, eng_type, eng_detail if eng_detail.strip() else None)
            st.success(f"@{eng_username.strip().lstrip('@')} の反応を記録しました。")
            st.rerun()
        else:
            st.error("ユーザー名を入力してください。")

    # --- 反応履歴 ---
    st.divider()
    st.subheader("反応履歴")
    engagements = get_engagements(limit=100)
    if engagements:
        eng_df = pd.DataFrame(engagements)
        type_labels = {
            "follow_back": "🔁 フォローバック",
            "like": "❤️ いいね",
            "comment": "💬 コメント",
            "story_view": "👁️ ストーリー",
            "dm_reply": "📩 DM返信",
        }
        eng_df["type_label"] = eng_df["type"].map(type_labels)
        st.dataframe(
            eng_df[["username", "type_label", "detail", "detected_at"]],
            use_container_width=True,
            hide_index=True,
            column_config={
                "username": st.column_config.TextColumn("ユーザー名"),
                "type_label": st.column_config.TextColumn("反応タイプ"),
                "detail": st.column_config.TextColumn("詳細"),
                "detected_at": st.column_config.TextColumn("検出日時"),
            },
        )
    else:
        st.info("まだ反応データがありません。")

    # --- 学習ログ ---
    st.divider()
    st.subheader("学習ログ")
    st.caption("反応チェックタスクが分析結果をここに記録します。")
    logs = get_learning_logs(limit=10)
    if logs:
        for log in logs:
            with st.expander(f"📅 {log['date']} — FB率 {log['follow_back_rate']:.1f}% / いいね率 {log['like_rate']:.1f}%"):
                st.write(f"**サマリー:** {log['summary']}")
                if log["insights"]:
                    st.write(f"**インサイト:** {log['insights']}")
                st.caption(f"送信数: {log['total_sent']} / FB: {log['total_follow_back']} / いいね: {log['total_like']}")
    else:
        st.info("まだ学習ログがありません。反応チェックタスク実行後に表示されます。")


# ============================
# タブ4: テンプレート
# ============================
with tab_template:
    st.header("DMテンプレート")

    template = get_active_template()

    if template:
        st.subheader("現在のテンプレート")
        edited_body = st.text_area("DM文面を編集", value=template["body"], height=200, key="edit_template")
        if st.button("💾 更新", key="update_btn"):
            update_template(template["id"], edited_body)
            st.success("テンプレートを更新しました。")
            st.rerun()
    else:
        st.info("テンプレートがまだ登録されていません。下のフォームから作成してください。")

    st.divider()
    st.subheader("新規テンプレート作成")
    new_name = st.text_input("テンプレート名", value="メイン", key="new_name")
    new_body = st.text_area(
        "DM本文",
        placeholder="はじめまして！\n〇〇について興味はありませんか？",
        height=200,
        key="new_body",
    )
    if st.button("📝 作成", key="create_btn"):
        if new_body.strip():
            save_template(new_name, new_body)
            st.success("テンプレートを作成しました。")
            st.rerun()
        else:
            st.error("DM本文を入力してください。")
