# -*- coding: utf-8 -*-
"""J-Quants API V2 + EDINET から日本株の深掘りデータを取得する。
環境変数 JQUANTS_API_KEY が必要(x-api-keyヘッダー方式)。holdersのみ EDINET_API_KEY。

使い方:
  python jquants.py quarterly 6492 [--years 5] [--chart]  # 四半期業績+CF+進捗率+配当履歴
  python jquants.py margin 6492 [--weeks 26] [--chart]    # 週次の信用買残/売残/信用倍率
  python jquants.py margin-daily 6492 [--days 30]         # 日々公表信用残(規制・注意銘柄のみ)
  python jquants.py shorts 7203 [--days 365]              # 空売り残高報告(0.5%超、機関名つき)
  python jquants.py flows [--section TSEPrime] [--chart]  # 投資部門別売買状況(市場全体)
  python jquants.py sector 機械 [--chart]                 # セクター資金流入の5段階評価(6期間)+3ヶ月vs TOPIXチャート
  python jquants.py holders 6492                          # 大量保有報告書(5%)+有報大株主(EDINET DB)
  python jquants.py activists [--min-ratio 5]             # アクティビストの最新ポジション一覧(市場横断)
  python jquants.py holder-search 光通信                   # 大株主名の逆引き: その主体が何を何%持つか
  python jquants.py holder-history --issuer 6492          # 保有履歴の時系列(--filer 主体名 でも可)

出力: 表(標準出力) + jquants_<subcmd>_<code>.json、--chartで charts/ にPNG
注意: 業績は決算短信の累計値を単独四半期に差分変換。ティッカーに.Tは不要。
"""
import os, sys, io, json, argparse
import urllib.request, urllib.error
from datetime import date, timedelta

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
BASE = "https://api.jquants.com/v2"

def api_get(path, **params):
    key = os.environ.get("JQUANTS_API_KEY")
    if not key:
        sys.exit("環境変数 JQUANTS_API_KEY が未設定です")
    qs = "&".join(f"{k}={v}" for k, v in params.items() if v)
    url = f"{BASE}{path}?{qs}"
    rows, pagination_key = [], None
    while True:
        u = url + (f"&pagination_key={pagination_key}" if pagination_key else "")
        req = urllib.request.Request(u, headers={"x-api-key": key})
        try:
            with urllib.request.urlopen(req) as r:
                data = json.loads(r.read())
        except urllib.error.HTTPError as e:
            sys.exit(f"APIエラー {e.code}: {u}\n{e.read().decode()[:300]}")
        rows += data.get("data", [])
        pagination_key = data.get("pagination_key")
        if not pagination_key:
            break
    return rows

def num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None

def oku(v, nd=1):
    return round(v / 1e8, nd) if v is not None else None

def fmt(v, w=9):
    return f"{v:>{w}}" if v is not None else " " * w

# ---------- quarterly: 四半期業績 + CF + 進捗率 + 配当 ----------

def cmd_quarterly(code, years, chart):
    rows = api_get("/fins/summary", code=code)
    fs = [r for r in rows if "FinancialStatements" in r.get("DocType", "") and num(r.get("Sales"))]
    fs.sort(key=lambda r: (r["CurFYSt"], r["CurPerEn"], r["DiscDate"]))
    uniq = {}
    for r in fs:  # 訂正開示は最後を採用
        uniq[(r["CurFYSt"], r["CurPerType"])] = r
    fs = sorted(uniq.values(), key=lambda r: (r["CurFYSt"], r["CurPerEn"]))

    out, prev_by_fy = [], {}
    for r in fs:
        fy = r["CurFYSt"]
        cur = {k: num(r.get(k)) for k in ("Sales", "OP", "OdP", "NP")}
        prev = prev_by_fy.get(fy)
        single = {k: (cur[k] - prev[k] if (prev and cur[k] is not None and prev.get(k) is not None) else cur[k])
                  for k in cur}
        prev_by_fy[fy] = cur
        cfo, cfi = num(r.get("CFO")), num(r.get("CFI"))
        out.append({
            "period": f"{r['CurPerEn'][:7]}({r['CurPerType']})",
            "period_end": r["CurPerEn"], "fy": fy, "type": r["CurPerType"],
            "売上高(億)": oku(single["Sales"]), "営業利益(億)": oku(single["OP"]),
            "経常利益(億)": oku(single["OdP"]), "純利益(億)": oku(single["NP"]),
            "営業利益率%": round(single["OP"] / single["Sales"] * 100, 1) if (single["OP"] is not None and single["Sales"]) else None,
            "累計売上(億)": oku(cur["Sales"]), "累計経常(億)": oku(cur["OdP"]), "累計純利(億)": oku(cur["NP"]),
            "営業CF累計(億)": oku(cfo), "FCF累計(億)": oku(cfo + cfi) if (cfo is not None and cfi is not None) else None,
            "EPS(累計)": num(r.get("EPS")), "BPS": num(r.get("BPS")),
            "年間配当": num(r.get("DivAnn")),
            "配当性向%": round(num(r.get("PayoutRatioAnn")) * 100, 1) if num(r.get("PayoutRatioAnn")) is not None else None,
            "開示日": r["DiscDate"],
        })
    cutoff = (date.today() - timedelta(days=int(years * 365.25))).isoformat()
    view = [o for o in out if o["period_end"] >= cutoff]

    # 直近の通期会社予想(業績予想修正も含め最新)
    fc = [r for r in rows if num(r.get("FSales")) or num(r.get("FOdP"))]
    forecast = None
    if fc:
        f = max(fc, key=lambda r: r["DiscDate"])
        forecast = {"開示日": f["DiscDate"], "売上(億)": oku(num(f.get("FSales"))), "営業(億)": oku(num(f.get("FOP"))),
                    "経常(億)": oku(num(f.get("FOdP"))), "純利(億)": oku(num(f.get("FNP"))),
                    "EPS": num(f.get("FEPS")), "年間配当": num(f.get("FDivAnn"))}

    print(f"===== {code} 四半期業績(単独四半期、億円) 出典: J-Quants fins/summary =====")
    print(f"{'四半期':<14}{'売上高':>8}{'営業利益':>9}{'経常':>8}{'純利益':>8}{'営利率%':>8}{'営業CF累計':>11}{'FCF累計':>9}")
    for o in view:
        print(f"{o['period']:<14}{fmt(o['売上高(億)'],8)}{fmt(o['営業利益(億)'])}{fmt(o['経常利益(億)'],8)}"
              f"{fmt(o['純利益(億)'],8)}{fmt(o['営業利益率%'],8)}{fmt(o['営業CF累計(億)'],11)}{fmt(o['FCF累計(億)'],9)}")

    # 進捗率: 最新の累計実績 vs 最新の通期予想
    progress = None
    if forecast and out:
        latest = out[-1]
        if latest["type"] != "FY":
            def prog(cum, full):
                return round(cum / full * 100, 1) if (cum is not None and full) else None
            progress = {
                "対象": latest["period"],
                "売上進捗率%": prog(latest["累計売上(億)"], forecast["売上(億)"]),
                "経常進捗率%": prog(latest["累計経常(億)"], forecast["経常(億)"]),
                "純利進捗率%": prog(latest["累計純利(億)"], forecast["純利(億)"]),
            }
            q_elapsed = {"1Q": 25, "2Q": 50, "3Q": 75}.get(latest["type"], 0)
            print(f"\n進捗率({latest['period']}時点 vs 通期予想): "
                  f"売上 {progress['売上進捗率%']}% / 経常 {progress['経常進捗率%']}% / 純利 {progress['純利進捗率%']}%"
                  f"  (期間経過の目安 {q_elapsed}% → 経常が大幅超過なら上方修正含み)")
    if forecast:
        print(f"通期会社予想({forecast['開示日']}): 売上{forecast['売上(億)']}億 営業{forecast['営業(億)']}億 "
              f"経常{forecast['経常(億)']}億 純利{forecast['純利(億)']}億 EPS{forecast['EPS']} 配当{forecast['年間配当']}円")

    # 配当履歴(FY実績)
    divs = [(o["fy"][:4] + "期", o["年間配当"], o["配当性向%"]) for o in out if o["type"] == "FY" and o["年間配当"] is not None]
    if divs:
        print("\n配当履歴(年間、実績):")
        for fy, d, pr in divs[-6:]:
            trend = ""
            print(f"  {fy}: {d}円" + (f" (性向{pr}%)" if pr is not None else ""))
        if forecast and forecast["年間配当"] is not None:
            print(f"  今期予想: {forecast['年間配当']}円")
        vals = [d for _, d, _ in divs]
        if len(vals) >= 2:
            streak = "増配" if vals[-1] > vals[-2] else ("減配⚠" if vals[-1] < vals[-2] else "据置")
            print(f"  直近実績は前期比{streak}")

    result = {"code": code, "quarterly": view, "forecast": forecast, "progress": progress,
              "dividends": [{"fy": a, "div": b, "payout": c} for a, b, c in divs]}
    _save(f"jquants_quarterly_{code}.json", result)

    if chart and view:
        import numpy as np
        plt = _plt_init()
        fig, (ax1, ax3) = plt.subplots(2, 1, figsize=(12, 7.5), sharex=True,
                                       gridspec_kw={"height_ratios": [3, 1]})
        x = np.arange(len(view))
        ax1.bar(x - 0.2, [o["売上高(億)"] or 0 for o in view], 0.4, label="売上高", color="#8ab4d8")
        ax1.bar(x + 0.2, [o["営業利益(億)"] or 0 for o in view], 0.4, label="営業利益", color="#d98a5f")
        ax2 = ax1.twinx()
        ax2.plot(x, [o["純利益(億)"] for o in view], "g.-", label="純利益(右軸)")
        ax1.set_ylabel("億円"); ax2.set_ylabel("純利益(億円)")
        ax1.set_title(f"{code} 四半期業績推移 (J-Quants, 取得日{date.today()})")
        h1, l1 = ax1.get_legend_handles_labels(); h2, l2 = ax2.get_legend_handles_labels()
        ax1.legend(h1 + h2, l1 + l2, loc="upper left")
        ax3.plot(x, [o["営業利益率%"] for o in view], "r.-", label="営業利益率%")
        ax3.axhline(0, color="black", lw=0.6)
        ax3.set_ylabel("営利率%"); ax3.grid(axis="y", alpha=0.3); ax3.legend(loc="upper left")
        ax3.set_xticks(x, [o["period"] for o in view], rotation=60, fontsize=8)
        _plt_save(fig, f"quarterly_{code}.png")

# ---------- margin: 週次信用残 ----------

def cmd_margin(code, weeks, chart):
    frm = (date.today() - timedelta(weeks=weeks + 2)).strftime("%Y%m%d")
    rows = api_get("/markets/margin-interest", code=code, **{"from": frm, "to": date.today().strftime("%Y%m%d")})
    rows.sort(key=lambda r: r["Date"])
    out = []
    for r in rows:
        buy, sell = num(r.get("LongVol")), num(r.get("ShrtVol"))
        out.append({"date": r["Date"], "信用買残(株)": buy, "信用売残(株)": sell,
                    "信用倍率": round(buy / sell, 2) if (buy and sell) else None})
    print(f"===== {code} 週次信用残 出典: J-Quants margin-interest =====")
    print(f"{'週末日':<12}{'買残(株)':>12}{'売残(株)':>12}{'信用倍率':>10}{'買残前週比':>12}")
    prev = None
    for o in out:
        chg = f"{o['信用買残(株)'] - prev:+,.0f}" if (prev is not None and o["信用買残(株)"] is not None) else ""
        bai = o["信用倍率"] if o["信用倍率"] is not None else ("∞(売残0)" if not o["信用売残(株)"] else "")
        print(f"{o['date']:<12}{o['信用買残(株)']:>12,.0f}{o['信用売残(株)']:>12,.0f}{bai:>10}{chg:>12}")
        prev = o["信用買残(株)"]
    _save(f"jquants_margin_{code}.json", {"code": code, "weekly": out})

    if chart and out:
        import numpy as np
        plt = _plt_init()
        fig, ax1 = plt.subplots(figsize=(11, 5))
        x = np.arange(len(out))
        ax1.bar(x - 0.2, [o["信用買残(株)"] or 0 for o in out], 0.4, label="信用買残", color="#d62728")
        ax1.bar(x + 0.2, [o["信用売残(株)"] or 0 for o in out], 0.4, label="信用売残", color="#1f77b4")
        ax1.set_xticks(x, [o["date"][5:] for o in out], rotation=60, fontsize=8)
        ax1.set_ylabel("株数")
        ax1.set_title(f"{code} 週次信用残推移 (J-Quants, 取得日{date.today()})")
        ax1.legend()
        _plt_save(fig, f"margin_{code}.png")

# ---------- margin-daily: 日々公表信用残 ----------

def cmd_margin_daily(code, days):
    frm = (date.today() - timedelta(days=days)).strftime("%Y%m%d")
    rows = api_get("/markets/margin-alert", code=code, **{"from": frm, "to": date.today().strftime("%Y%m%d")})
    rows.sort(key=lambda r: r.get("Date", r.get("PubDate", "")))
    if not rows:
        print(f"{code}: 日々公表銘柄の指定期間データなし(=現在、日々公表・規制の対象外。週次のmarginを使う)")
        return
    print(f"===== {code} 日々公表信用残 出典: J-Quants margin-alert =====")
    keys = [k for k in rows[-1].keys() if k not in ("Code",)]
    print(json.dumps(rows[-10:], ensure_ascii=False, indent=1))
    _save(f"jquants_margin_daily_{code}.json", {"code": code, "daily": rows})

# ---------- shorts: 空売り残高報告(機関名つき、0.5%超) ----------

def cmd_shorts(code, days, chart=False):
    rows = api_get("/markets/short-sale-report", code=code)
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    rows = [r for r in rows if r.get("DiscDate", "") >= cutoff]
    if not rows:
        print(f"{code}: 過去{days}日に空売り残高報告なし(0.5%超の大口空売りが存在しない)")
        return
    rows.sort(key=lambda r: (r["CalcDate"], r["DiscDate"]))
    # 機関ごとの時系列
    by_inst = {}
    for r in rows:
        by_inst.setdefault(r["SSName"], []).append(r)

    print(f"===== {code} 空売り残高報告(発行済比0.5%超のみ開示) 出典: J-Quants short-sale-report(元データJPX) =====")
    print(f"\n[機関別 最新ポジション]")
    print(f"{'機関名':<45}{'残高比率%':>9}{'株数':>14}{'前回比率%':>10}{'計算日':>12}")
    for name, hist in sorted(by_inst.items(), key=lambda kv: -(num(kv[1][-1]["ShrtPosToSO"]) or 0)):
        r = hist[-1]
        ratio = num(r["ShrtPosToSO"])
        prev = num(r.get("PrevRptRatio"))
        arrow = ""
        if ratio is not None and prev is not None:
            arrow = " ↑増" if ratio > prev else (" ↓減" if ratio < prev else " →")
        print(f"{name[:44]:<45}{ratio*100 if ratio else 0:>8.2f}{num(r['ShrtPosShares']) or 0:>14,.0f}"
              f"{(prev*100 if prev else 0):>9.2f}{arrow}{r['CalcDate']:>12}")

    print(f"\n[機関別 残高推移(計算日ベース)]")
    for name, hist in sorted(by_inst.items(), key=lambda kv: -(num(kv[1][-1]["ShrtPosToSO"]) or 0)):
        print(f"  ● {name[:60]}")
        for r in hist:
            ratio = num(r["ShrtPosToSO"]) or 0
            bar = "#" * int(ratio * 1000)  # 0.1%につき1文字
            print(f"    {r['CalcDate']}  {ratio*100:5.2f}%  {bar}")

    # 全機関合算(0.5%超の見えている分のみ)
    total_by_date = {}
    cur = {}
    for r in rows:
        cur[r["SSName"]] = num(r["ShrtPosToSO"]) or 0
        total_by_date[r["CalcDate"]] = sum(cur.values())
    print(f"\n[開示分合算の推移(0.5%未満に落ちた機関は最後の値で残る点に注意)]")
    for d, t in sorted(total_by_date.items())[-10:]:
        print(f"  {d}  {t*100:5.2f}%")

    _save(f"jquants_shorts_{code}.json", {"code": code, "reports": rows})

    if chart:
        from datetime import datetime
        plt = _plt_init()
        fig, ax = plt.subplots(figsize=(11, 5.5))
        for name, hist in sorted(by_inst.items(), key=lambda kv: -(num(kv[1][-1]["ShrtPosToSO"]) or 0))[:8]:
            xs = [datetime.strptime(r["CalcDate"], "%Y-%m-%d") for r in hist]
            ys = [(num(r["ShrtPosToSO"]) or 0) * 100 for r in hist]
            ax.plot(xs, ys, ".-", label=name[:28])
        ax.axhline(0.5, color="gray", ls="--", lw=0.8)
        ax.text(0.01, 0.5, "開示下限0.5%", fontsize=8, color="gray",
                transform=ax.get_yaxis_transform(), va="bottom")
        ax.set_ylabel("空売り残高比率(%)")
        ax.set_title(f"{code} 機関別空売り残高推移 (JPX空売り残高報告, 取得日{date.today()})")
        ax.legend(fontsize=8)
        ax.grid(alpha=0.3)
        fig.autofmt_xdate(rotation=60)
        _plt_save(fig, f"shorts_{code}.png")

# ---------- sector: セクター資金流入の5段階評価 ----------

# 東証33業種 → J-Quants指数コード(0040水産〜0060サービスの連番)
SECTOR33 = {
    "水産・農林業": "0040", "鉱業": "0041", "建設業": "0042", "食料品": "0043",
    "繊維製品": "0044", "パルプ・紙": "0045", "化学": "0046", "医薬品": "0047",
    "石油・石炭製品": "0048", "ゴム製品": "0049", "ガラス・土石製品": "004A",
    "鉄鋼": "004B", "非鉄金属": "004C", "金属製品": "004D", "機械": "004E",
    "電気機器": "004F", "輸送用機器": "0050", "精密機器": "0051", "その他製品": "0052",
    "電気・ガス業": "0053", "陸運業": "0054", "海運業": "0055", "空運業": "0056",
    "倉庫・運輸関連業": "0057", "情報・通信業": "0058", "卸売業": "0059", "小売業": "005A",
    "銀行業": "005B", "証券・商品先物取引業": "005C", "保険業": "005D", "その他金融業": "005E",
    "不動産業": "005F", "サービス業": "0060",
}

def resolve_sector(name):
    n = name.strip().replace("(", "").replace(")", "")
    if n in SECTOR33:
        return n, SECTOR33[n]
    for k in SECTOR33:  # 部分一致(例: サービス→サービス業、情報通信→情報・通信業)
        kk = k.replace("・", "")
        if n == kk or n in k or k in n or n in kk or kk in n:
            return k, SECTOR33[k]
    return None, None

def _idx_bars(code, days):
    frm = (date.today() - timedelta(days=days)).strftime("%Y%m%d")
    rows = api_get("/indices/bars/daily", code=code, **{"from": frm, "to": date.today().strftime("%Y%m%d")})
    rows.sort(key=lambda r: r["Date"])
    return rows

def _ret(rows, n):  # n営業日前比のリターン%(rowsは日付昇順、C=終値)
    if len(rows) < 2:
        return None
    i = max(0, len(rows) - 1 - n)
    base = num(rows[i]["C"])
    last = num(rows[-1]["C"])
    return round((last / base - 1) * 100, 2) if (base and last) else None

# 期間区分: キー, 表示名, 営業日数, 5段階の帯(やや/活況の相対pp閾値)
SECTOR_HORIZONS = [
    ("1d",  "過去1日",    1,  (0.5, 1.5)),
    ("3d",  "過去3日",    3,  (0.8, 2.5)),
    ("1w",  "過去1週間",  5,  (1.0, 3.0)),
    ("2w",  "過去2週間",  10, (1.3, 3.5)),
    ("1m",  "過去1ヶ月",  20, (1.5, 4.0)),
    ("3m",  "過去3ヶ月",  60, (3.0, 8.0)),
]

def _tier(rel, band):
    lo, hi = band
    if rel is None:
        return "判定不能"
    if rel >= hi:   return "活況"
    if rel >= lo:   return "やや活況"
    if rel > -lo:   return "中立"
    if rel > -hi:   return "やや資金流出"
    return "資金流出"

def cmd_sector(name, chart=False):
    sec_name, idx = resolve_sector(name)
    if not idx:
        sys.exit(f"業種『{name}』を東証33業種にマッチできません。例: 機械 / 電気機器 / 化学 / 情報・通信業")
    sec = _idx_bars(idx, 150)
    top = _idx_bars("0000", 150)
    result = {"sector": sec_name, "index_code": idx, "as_of": sec[-1]["Date"] if sec else None,
              "horizons": {}}
    print(f"===== セクター資金流入 『{sec_name}』(指数{idx}) vs TOPIX 出典: J-Quants indices =====")
    print(f"{'期間':<12}{'セクター騰落%':>12}{'TOPIX騰落%':>12}{'相対(pp)':>10}  5段階評価")
    for key, jp, n, band in SECTOR_HORIZONS:
        s, t = _ret(sec, n), _ret(top, n)
        rel = round(s - t, 2) if (s is not None and t is not None) else None
        tier = _tier(rel, band)
        result["horizons"][key] = {"label": jp, "days": n, "sector_ret%": s,
                                   "topix_ret%": t, "relative_pp": rel, "tier": tier}
        print(f"{jp:<12}{fmt(s,10)}{fmt(t,12)}{fmt(rel,10)}  {tier}")
    print("\n※資金流入の代理指標=セクター指数のTOPIX対比の相対強弱(価格ベース)。"
          "実際の売買代金フローではない点に留意。相対プラス=資金がこのセクターに回っている目安")
    _save(f"jquants_sector_{idx}.json", result)

    if chart and sec and top:
        from datetime import datetime
        # 直近3ヶ月(約60営業日)を基準日=100に正規化して比較
        sec3, top3 = sec[-61:], top[-61:]
        base_s, base_t = num(sec3[0]["C"]), num(top3[0]["C"])
        # 日付で突き合わせ(両方に存在する営業日のみ)
        tmap = {r["Date"]: num(r["C"]) for r in top3}
        xs, ys_s, ys_t, ys_rel = [], [], [], []
        for r in sec3:
            d, cs = r["Date"], num(r["C"])
            ct = tmap.get(d)
            if cs and ct and base_s and base_t:
                xs.append(datetime.strptime(d, "%Y-%m-%d"))
                ys_s.append(cs / base_s * 100)
                ys_t.append(ct / base_t * 100)
                ys_rel.append(cs / base_s * 100 - ct / base_t * 100)
        plt = _plt_init()
        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(11, 6.5), sharex=True,
                                       gridspec_kw={"height_ratios": [3, 1]})
        ax1.plot(xs, ys_s, color="#d62728", lw=1.8, label=f"{sec_name}(指数{idx})")
        ax1.plot(xs, ys_t, color="#1f77b4", lw=1.8, label="TOPIX")
        ax1.axhline(100, color="gray", lw=0.7, ls="--")
        ax1.set_ylabel("基準日=100")
        ax1.set_title(f"{sec_name} vs TOPIX 直近3ヶ月(基準日={xs[0].date() if xs else ''}=100) J-Quants")
        ax1.legend(); ax1.grid(alpha=0.3)
        ax2.fill_between(xs, ys_rel, 0, where=[v >= 0 for v in ys_rel], color="#2f855a", alpha=0.6, interpolate=True)
        ax2.fill_between(xs, ys_rel, 0, where=[v < 0 for v in ys_rel], color="#c0392b", alpha=0.6, interpolate=True)
        ax2.axhline(0, color="black", lw=0.7)
        ax2.set_ylabel("相対(pp)\n+=資金流入")
        ax2.grid(alpha=0.3)
        fig.autofmt_xdate(rotation=45)
        _plt_save(fig, f"sector_{idx}.png")
        result["chart"] = f"charts/sector_{idx}.png"
    return result

# ---------- flows: 投資部門別売買状況 ----------

FLOW_CATS = [("FrgnBal", "海外投資家"), ("IndBal", "個人"), ("TrstBnkBal", "信託銀行"),
             ("InvTrBal", "投資信託"), ("BusCoBal", "事業法人"), ("PropBal", "証券自己")]

def cmd_flows(weeks, section, chart):
    frm = (date.today() - timedelta(weeks=weeks + 2)).strftime("%Y%m%d")
    rows = api_get("/equities/investor-types", **{"from": frm, "to": date.today().strftime("%Y%m%d")})
    wk = sorted([r for r in rows if r["Section"] == section], key=lambda r: r["StDate"])
    print(f"===== {section} 投資部門別 週次差引(買-売) 単位:億円 出典: J-Quants =====")
    print(f"{'週':<14}" + "".join(f"{name:>10}" for _, name in FLOW_CATS))
    out = []
    for w in wk:
        rec = {"week": f"{w['StDate']}~{w['EnDate']}"}
        line = f"{w['StDate'][5:]}~{w['EnDate'][5:]:<6}"
        for k, name in FLOW_CATS:
            v = round(num(w[k]) / 1e5, 0) if num(w[k]) is not None else None  # 千円→億円
            rec[name] = v
            line += f"{v:>12,.0f}" if v is not None else f"{'':>12}"
        out.append(rec)
        print(line)
    print("-" * (14 + 12 * len(FLOW_CATS)))
    print(f"{'累計':<12}" + "".join(f"{sum(o[name] or 0 for o in out):>12,.0f}" for _, name in FLOW_CATS))
    _save(f"jquants_flows_{section}.json", {"section": section, "weekly": out})

    if chart and out:
        import numpy as np
        plt = _plt_init()
        fig, ax = plt.subplots(figsize=(12, 5.5))
        x = np.arange(len(out))
        colors = ["#d62728", "#1f77b4", "#2ca02c", "#ff7f0e", "#9467bd", "#7f7f7f"]
        width = 0.14
        for i, ((_, name), c) in enumerate(zip(FLOW_CATS, colors)):
            ax.bar(x + (i - 2.5) * width, [o[name] or 0 for o in out], width, label=name, color=c)
        ax.axhline(0, color="black", lw=0.8)
        ax.set_xticks(x, [o["week"][5:10] + "~" for o in out], rotation=45, fontsize=8)
        ax.set_ylabel("差引(億円) +=買い越し")
        ax.set_title(f"投資部門別売買状況 {section} (J-Quants, 取得日{date.today()})")
        ax.legend(ncol=3)
        ax.grid(axis="y", alpha=0.3)
        _plt_save(fig, f"flows_{section}.png")

# ---------- holders: 大量保有報告書・大株主(EDINET DB) ----------

EDB_BASE = "https://edinetdb.jp/v1"

def edb_get(path, **params):
    key = os.environ.get("EDINET_API_KEY")
    if not key:
        sys.exit("環境変数 EDINET_API_KEY が未設定です。https://edinetdb.jp/developers で無料発行しキーを設定してください")
    qs = "&".join(f"{k}={urllib.request.quote(str(v))}" for k, v in params.items() if v)
    url = f"{EDB_BASE}{path}" + (f"?{qs}" if qs else "")
    req = urllib.request.Request(url, headers={"X-API-Key": key})
    try:
        with urllib.request.urlopen(req) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        sys.exit(f"EDINET DB APIエラー {e.code}: {url}\n{e.read().decode()[:300]}")

def cmd_holders(code, days):
    sec4 = code[:4]
    # 証券コード→EDINETコード解決
    sr = edb_get("/search", q=sec4)
    cands = sr if isinstance(sr, list) else sr.get("data", sr.get("results", sr.get("companies", [])))
    edinet_code, name = None, None
    for c in cands or []:
        sec = str(c.get("sec_code", c.get("secCode", c.get("securities_code", ""))))
        if sec.startswith(sec4):
            edinet_code = c.get("edinet_code", c.get("edinetCode", c.get("code")))
            name = c.get("name", c.get("company_name", c.get("filer_name")))
            break
    if not edinet_code:
        sys.exit(f"{sec4}: EDINET DBで企業を特定できず。レスポンス例: {json.dumps(cands[:1] if cands else sr, ensure_ascii=False)[:300]}")

    result = {"code": sec4, "edinet_code": edinet_code, "name": name}
    print(f"===== {sec4} {name} ({edinet_code}) 出典: EDINET DB =====")

    # 大量保有報告書(5%ルール)の最新保有者
    lh = edb_get(f"/companies/{edinet_code}/shareholders")
    holders = lh if isinstance(lh, list) else lh.get("data", lh.get("shareholders", []))
    print("\n[大量保有報告書(5%ルール)ベースの保有者]")
    if holders:
        print(json.dumps(holders, ensure_ascii=False, indent=1)[:3000])
    else:
        print("  提出なし(5%超の大量保有者が存在しないか未提出)")
    result["large_holdings"] = holders

    # 有報記載の上位大株主
    mj = edb_get(f"/companies/{edinet_code}/major-shareholders")
    majors = mj if isinstance(mj, list) else mj.get("data", mj.get("major_shareholders", []))
    print("\n[有価証券報告書記載の大株主(上位10)]")
    if majors:
        print(json.dumps(majors, ensure_ascii=False, indent=1)[:3000])
    else:
        print("  データなし")
    result["major_shareholders"] = majors

    _save(f"edinet_holders_{sec4}.json", result)

# ---------- activists / holder-search / holder-history (EDINET DB) ----------

def cmd_activists(min_ratio):
    resp = edb_get("/shareholders/activists")
    rows = resp.get("data", []) if isinstance(resp, dict) else resp
    rows = [r for r in rows if (num(r.get("holding_ratio")) or 0) * 100 >= min_ratio]
    rows.sort(key=lambda r: r.get("submit_date_time", ""), reverse=True)
    print(f"===== アクティビスト最新ポジション(保有{min_ratio}%以上, {len(rows)}件) 出典: EDINET DB =====")
    print(f"{'提出日':<12}{'コード':>6} {'銘柄':<24}{'比率%':>7}  アクティビスト")
    for r in rows:
        d = (r.get("submit_date_time") or "")[:10]
        ratio = (num(r.get("holding_ratio")) or 0) * 100
        print(f"{d:<12}{r.get('issuer_sec_code') or '----':>6} {(r.get('issuer_name') or '')[:23]:<24}"
              f"{ratio:>7.2f}  {(r.get('filer_name') or '')[:40]}")
    _save("edinet_activists.json", {"min_ratio": min_ratio, "positions": rows})

def cmd_holder_search(name):
    resp = edb_get("/shareholders/search", q=name)
    rows = resp.get("data", []) if isinstance(resp, dict) else resp
    rows.sort(key=lambda r: -(num(r.get("total_holding_ratio")) or 0))
    print(f"===== 「{name}」の保有銘柄({len(rows)}件、最新報告ベース) 出典: EDINET DB =====")
    print(f"{'コード':>6} {'銘柄':<26}{'保有比率%':>9}  {'最終報告日':<12}")
    for r in rows:
        ratio = (num(r.get("total_holding_ratio")) or 0) * 100
        d = (r.get("submit_date_time") or "")[:10]
        print(f"{r.get('issuer_sec_code') or '----':>6} {(r.get('issuer_name') or '')[:25]:<26}{ratio:>9.2f}  {d:<12}")
    print("\n注: 5%割れ後の売却は報告義務がないため、比率5%未満の行は「その後さらに売った」可能性あり")
    _save(f"edinet_holder_search.json", {"query": name, "holdings": rows})

def cmd_holder_history(filer, issuer):
    params = {}
    if filer:
        params["filer"] = filer
    if issuer:
        # 証券コード4桁ならEDINETコードに解決
        iss = issuer.replace(".T", "")
        if iss.isdigit():
            sr = edb_get("/search", q=iss[:4])
            cands = sr if isinstance(sr, list) else sr.get("data", [])
            for c in cands or []:
                if str(c.get("sec_code", "")).startswith(iss[:4]):
                    iss = c.get("edinet_code")
                    break
        params["issuer"] = iss
    if not params:
        sys.exit("--filer <主体名> か --issuer <証券コード/EDINETコード> のどちらかを指定してください")
    resp = edb_get("/shareholders/history", **params)
    rows = resp.get("data", []) if isinstance(resp, dict) else resp
    rows.sort(key=lambda r: r.get("submit_date_time", ""))
    print(f"===== 保有履歴 {params} ({len(rows)}件) 出典: EDINET DB =====")
    print(f"{'提出日':<12}{'コード':>6} {'銘柄':<20}{'比率%':>7}{'前回%':>7}  保有者")
    for r in rows:
        d = (r.get("submit_date_time") or "")[:10]
        ratio = (num(r.get("holding_ratio", r.get("total_holding_ratio"))) or 0) * 100
        prev = num(r.get("holding_ratio_previous"))
        prev_s = f"{prev*100:.2f}" if prev is not None else ""
        print(f"{d:<12}{r.get('issuer_sec_code') or '----':>6} {(r.get('issuer_name') or '')[:19]:<20}"
              f"{ratio:>7.2f}{prev_s:>7}  {(r.get('holder_name') or r.get('filer_name') or '')[:35]}")
    _save("edinet_holder_history.json", {"params": params, "history": rows})

# ---------- helpers ----------

def _save(fname, obj):
    with open(fname, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)
    print(f"\n[saved] {fname}")

def _plt_init():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib import font_manager
    for f in font_manager.fontManager.ttflist:
        if "Yu Gothic" in f.name:
            plt.rcParams["font.family"] = f.name
            break
    return plt

def _plt_save(fig, fname):
    os.makedirs("charts", exist_ok=True)
    path = os.path.join("charts", fname)
    fig.tight_layout()
    fig.savefig(path, dpi=110)
    print(f"[chart] {path}")

if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    q = sub.add_parser("quarterly"); q.add_argument("code"); q.add_argument("--years", type=float, default=5); q.add_argument("--chart", action="store_true")
    m = sub.add_parser("margin"); m.add_argument("code"); m.add_argument("--weeks", type=int, default=26); m.add_argument("--chart", action="store_true")
    md = sub.add_parser("margin-daily"); md.add_argument("code"); md.add_argument("--days", type=int, default=30)
    s = sub.add_parser("shorts"); s.add_argument("code"); s.add_argument("--days", type=int, default=365); s.add_argument("--chart", action="store_true")
    f = sub.add_parser("flows"); f.add_argument("--weeks", type=int, default=12); f.add_argument("--section", default="TSEPrime"); f.add_argument("--chart", action="store_true")
    sc = sub.add_parser("sector"); sc.add_argument("name"); sc.add_argument("--chart", action="store_true")
    h = sub.add_parser("holders"); h.add_argument("code"); h.add_argument("--days", type=int, default=45)
    ac = sub.add_parser("activists"); ac.add_argument("--min-ratio", type=float, default=5.0)
    hs = sub.add_parser("holder-search"); hs.add_argument("name")
    hh = sub.add_parser("holder-history"); hh.add_argument("--filer"); hh.add_argument("--issuer")
    a = ap.parse_args()
    code = getattr(a, "code", "").replace(".T", "") if hasattr(a, "code") else None
    if a.cmd == "quarterly":
        cmd_quarterly(code, a.years, a.chart)
    elif a.cmd == "margin":
        cmd_margin(code, a.weeks, a.chart)
    elif a.cmd == "margin-daily":
        cmd_margin_daily(code, a.days)
    elif a.cmd == "shorts":
        cmd_shorts(code, a.days, a.chart)
    elif a.cmd == "flows":
        cmd_flows(a.weeks, a.section, a.chart)
    elif a.cmd == "sector":
        cmd_sector(a.name, a.chart)
    elif a.cmd == "holders":
        cmd_holders(code, a.days)
    elif a.cmd == "activists":
        cmd_activists(a.min_ratio)
    elif a.cmd == "holder-search":
        cmd_holder_search(a.name)
    elif a.cmd == "holder-history":
        cmd_holder_history(a.filer, a.issuer)
