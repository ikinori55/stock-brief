# -*- coding: utf-8 -*-
"""モバイル向けテキストブリーフ生成(GitHub Actions実行用)。

ウォッチリスト(watchlist.txt: 「code,東証33業種名」形式)または環境変数 INPUT_CODE / INPUT_SECTOR
で指定された銘柄について、scripts/ のデータ取得スクリプト群を実行し、
docs/brief/<code>.md (人間/Claude可読) と docs/brief/index.md を生成する。

必要な環境変数: JQUANTS_API_KEY (必須), EDINET_API_KEY (holders用・任意)
チャートは生成しない(テキストのみ)。個別スクリプトの失敗は「取得失敗」と記して続行する。
"""
import os, sys, io, json, re, glob, subprocess
from datetime import date

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
ROOT = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.join(ROOT, "scripts")
OUT = os.path.join(ROOT, "out")
DOCS = os.path.join(ROOT, "docs", "brief")
os.makedirs(OUT, exist_ok=True)
os.makedirs(DOCS, exist_ok=True)
TODAY = date.today().isoformat()

def run(script, *args, timeout=300):
    cmd = [sys.executable, os.path.join(SCRIPTS, script), *args]
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=timeout, env=env, cwd=OUT)
        ok = r.returncode == 0
        print(("  OK " if ok else "  NG ") + " ".join([script, *args]))
        if not ok:
            print("    " + r.stderr.decode("utf-8", "replace")[-200:].strip())
        return ok, r.stdout.decode("utf-8", "replace")
    except subprocess.TimeoutExpired:
        print(f"  NG {script} timeout")
        return False, ""

def load(name):
    try:
        with open(os.path.join(OUT, name), encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def f_(v, suffix=""):
    if v is None:
        return "不明"
    if isinstance(v, float):
        s = f"{v:,.2f}".rstrip("0").rstrip(".")
        return s + suffix
    return f"{v}{suffix}"

def build_brief(code, sector):
    yft = f"{code}.T"
    print(f"[{code}] データ収集...")
    run("technical.py", yft)
    run("fundamental.py", yft)
    run("jquants.py", "quarterly", code)
    run("jquants.py", "margin", code, "--weeks", "8")
    run("jquants.py", "shorts", code)
    if os.environ.get("EDINET_API_KEY"):
        run("jquants.py", "holders", code)
    run("kabutan_news.py", code)
    sec_data = None
    if sector:
        ok, out = run("jquants.py", "sector", sector)
        m = re.search(r"jquants_sector_(\w+)\.json", out)
        if m:
            sec_data = load(f"jquants_sector_{m.group(1)}.json")

    tech = (load("technical_results.json") or {}).get(yft) or {}
    fund = (load("fundamental_results.json") or {}).get(yft) or {}
    qtr = load(f"jquants_quarterly_{code}.json") or {}
    margin = load(f"jquants_margin_{code}.json") or {}
    shorts = load(f"jquants_shorts_{code}.json") or {}
    holders = load(f"edinet_holders_{code}.json") or {}
    news = load(f"kabutan_news_{code}.json") or {}

    name = holders.get("name") or fund.get("name") or yft
    L = []
    L.append(f"# {name} ({code}) データブリーフ")
    L.append(f"生成日: {TODAY} / データは各取得元の直近営業日ベース。数値は実データのみ、欠損は「不明」。")
    L.append("")

    # --- テクニカル ---
    L.append("## 株価スナップショット")
    if tech:
        L.append(f"- 終値: {f_(tech.get('price'),'円')} (52週 {f_(tech.get('lo_52w'))}〜{f_(tech.get('hi_52w'))})")
        L.append(f"- RSI14: {f_(tech.get('rsi14'))} / MA25乖離: {f_(tech.get('vs_ma25%'),'%')} / MA200乖離: {f_(tech.get('vs_ma200%'),'%')}")
        L.append(f"- 騰落: 1ヶ月 {f_(tech.get('chg_1m%'),'%')} / 3ヶ月 {f_(tech.get('chg_3m%'),'%')} / 1年 {f_(tech.get('chg_1y%'),'%')}")
        L.append(f"- {tech.get('gc_state','')} / MACD: {tech.get('macd_state','')} / 年率ボラ: {f_(tech.get('vol_ann%'),'%')}")
    else:
        L.append("- 取得失敗")
    L.append("")

    # --- バリュエーション ---
    L.append("## バリュエーション・財務")
    if fund:
        L.append(f"- PER: {f_(fund.get('PER'),'倍')} / 予想PER: {f_(fund.get('予想PER'),'倍')} / PBR: {f_(fund.get('PBR'),'倍')} / PEG: {f_(fund.get('PEG'))}")
        L.append(f"- EPS: {f_(fund.get('EPS'),'円')} / ROE: {f_(fund.get('ROE%'),'%')} / 配当利回り: {f_(fund.get('配当利回り%'),'%')}")
        L.append(f"- 時価総額: {f_(fund.get('時価総額(億)'),'億円')} / D/E: {f_(fund.get('D/E%'),'%')} / 流動比率: {f_(fund.get('流動比率'))}")
        L.append(f"- 増収率YoY: {f_(fund.get('増収率YoY%'),'%')} / 営業増益率YoY: {f_(fund.get('営業増益率YoY%'),'%')} / 財務スコア: {f_(fund.get('財務スコア(10点)'))}/10")
    else:
        L.append("- 取得失敗")
    L.append("")

    # --- 四半期業績 ---
    L.append("## 四半期業績(単独、億円)")
    qs = (qtr.get("quarterly") or [])[-5:]
    if qs:
        L.append("| 四半期 | 売上 | 営利 | 純利 | 営利率% | 営業CF累計 | FCF累計 |")
        L.append("|--|--|--|--|--|--|--|")
        for q in qs:
            L.append(f"| {q['period']} | {f_(q['売上高(億)'])} | {f_(q['営業利益(億)'])} | {f_(q['純利益(億)'])} "
                     f"| {f_(q['営業利益率%'])} | {f_(q['営業CF累計(億)'])} | {f_(q['FCF累計(億)'])} |")
        pg, fc = qtr.get("progress"), qtr.get("forecast")
        if pg:
            L.append(f"- **進捗率**({pg.get('対象')}): 売上 {f_(pg.get('売上進捗率%'),'%')} / 経常 {f_(pg.get('経常進捗率%'),'%')} / 純利 {f_(pg.get('純利進捗率%'),'%')}")
        if fc:
            L.append(f"- 通期会社予想({fc.get('開示日')}): 売上{f_(fc.get('売上(億)'))}億 経常{f_(fc.get('経常(億)'))}億 "
                     f"純利{f_(fc.get('純利(億)'))}億 EPS{f_(fc.get('EPS'))} 配当{f_(fc.get('年間配当'))}円")
        dv = qtr.get("dividends") or []
        if dv:
            L.append("- 配当履歴: " + " → ".join(f"{d['fy']}{f_(d['div'])}円" for d in dv[-5:]))
    else:
        L.append("- 取得失敗")
    L.append("")

    # --- 需給 ---
    L.append("## 需給")
    wk = (margin.get("weekly") or [])[-4:]
    if wk:
        L.append("**信用残(週次)**")
        for w in wk:
            bai = w.get("信用倍率")
            bai_s = f_(bai) if bai is not None else ("∞(売残0)" if not w.get("信用売残(株)") else "不明")
            L.append(f"- {w['date']}: 買残 {f_(w['信用買残(株)'],'株')} / 売残 {f_(w['信用売残(株)'],'株')} / 倍率 {bai_s}")
    reps = shorts.get("reports") or []
    if reps:
        latest = {}
        for r in sorted(reps, key=lambda x: x.get("CalcDate", "")):
            latest[r["SSName"]] = r
        top = sorted(latest.items(), key=lambda kv: -(float(kv[1].get("ShrtPosToSO") or 0)))[:5]
        L.append("**機関別空売り残高(0.5%超開示、最新)**")
        for n, r in top:
            L.append(f"- {n[:40]}: {float(r.get('ShrtPosToSO') or 0)*100:.2f}% ({r.get('CalcDate')})")
    else:
        L.append("**空売り**: 0.5%超の残高報告なし(空売り不能銘柄 or 大口ショート不在)")
    lh = (holders.get("large_holdings") or [])[:4]
    if lh:
        L.append("**大量保有報告(5%ルール、直近)**")
        for r in lh:
            prev = r.get("holding_ratio_previous")
            prev_s = f"(前回 {prev*100:.2f}%)" if prev else ""
            L.append(f"- {r.get('holder_name')}: {(r.get('holding_ratio') or 0)*100:.2f}% {prev_s} {(r.get('submit_date_time') or '')[:10]}")
    mj = holders.get("major_shareholders") or []
    if mj:
        fy = max(m.get("fiscal_year", 0) for m in mj)
        tops = [m for m in mj if m.get("fiscal_year") == fy][:5]
        L.append(f"**有報大株主(FY{fy}上位)**: " + " / ".join(f"{m['holder_name']} {m['ratio_pct']}%" for m in tops))
    L.append("")

    # --- セクター ---
    L.append("## セクター資金流入(TOPIX対比・5段階)")
    if sec_data and sec_data.get("horizons"):
        L.append(f"対象: {sec_data.get('sector')} (基準日 {sec_data.get('as_of')})")
        for k in ["1d", "3d", "1w", "2w", "1m", "3m"]:
            h = sec_data["horizons"].get(k)
            if h:
                L.append(f"- {h.get('label')}: **{h.get('tier')}** (セクター {f_(h.get('sector_ret%'),'%')} / TOPIX {f_(h.get('topix_ret%'),'%')} / 相対 {f_(h.get('relative_pp'),'pp')})")
        L.append("※価格ベースの相対強弱による代理評価(実際の売買代金フローではない)")
    else:
        L.append("- 業種未指定または取得失敗(watchlist.txt に「code,東証33業種名」で指定)")
    L.append("")

    # --- カタリスト ---
    L.append("## 材料・カタリスト(株探)")
    items = [i for i in (news.get("items") or []) if i.get("kinds")][:8]
    if items:
        for i in items:
            L.append(f"- {i['date']} [{','.join(i['kinds'])}] {i['title'][:60]}")
    else:
        L.append("- カタリスト該当見出しなし(または取得失敗)")
    L.append("")

    L.append("---")
    L.append("**免責: 本ブリーフは投資助言ではない。** データ出典: yfinance / J-Quants / EDINET DB / kabutan.jp。")
    L.append("投資判断(見通し5段階・おすすめ度)は claude.ai プロジェクトの指示に従い、このデータを根拠に行うこと。")

    md = "\n".join(L)
    with open(os.path.join(DOCS, f"{code}.md"), "w", encoding="utf-8") as f:
        f.write(md)
    print(f"[saved] docs/brief/{code}.md")
    # index用スナップショット
    return {"code": code, "name": name, "price": tech.get("price"), "rsi": tech.get("rsi14"),
            "chg_1m": tech.get("chg_1m%"), "sector": (sec_data or {}).get("sector"),
            "sector_1m": ((sec_data or {}).get("horizons", {}).get("1m") or {}).get("tier")}

def main():
    targets = []
    in_code = (os.environ.get("INPUT_CODE") or "").strip()
    if in_code:
        targets.append((in_code.replace(".T", ""), (os.environ.get("INPUT_SECTOR") or "").strip()))
    else:
        wl = os.path.join(ROOT, "watchlist.txt")
        if os.path.exists(wl):
            for line in open(wl, encoding="utf-8"):
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                parts = [p.strip() for p in line.split(",")]
                targets.append((parts[0], parts[1] if len(parts) > 1 else ""))
    if not targets:
        sys.exit("対象銘柄なし(watchlist.txt か INPUT_CODE を指定)")

    snaps = []
    for code, sector in targets:
        try:
            snaps.append(build_brief(code, sector))
        except Exception as e:
            print(f"[{code}] 失敗: {e}")

    idx = [f"# 銘柄ブリーフ一覧 (更新: {TODAY})", ""]
    for s in snaps:
        sec_s = f" / セクター1ヶ月: {s['sector_1m']}" if s.get("sector_1m") else ""
        idx.append(f"- [{s['code']} {s['name']}]({s['code']}.md) — 終値 {f_(s['price'],'円')} / RSI {f_(s['rsi'])} / 1ヶ月 {f_(s['chg_1m'],'%')}{sec_s}")
    idx.append("")
    idx.append("各リンク先が銘柄別データブリーフ。免責: 投資助言ではない。")
    with open(os.path.join(DOCS, "index.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(idx))
    print("[saved] docs/brief/index.md")

if __name__ == "__main__":
    main()
