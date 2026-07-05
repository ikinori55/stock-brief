# -*- coding: utf-8 -*-
"""決算データから財務分析（収益性・成長性・安全性・割安性 + 10点スコア）
使い方: python fundamental.py 5942.T 8103.T AAPL
結果は標準出力(JSON)と fundamental_results.json に保存。
"""
import sys, io, json, argparse
import yfinance as yf

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

def g(df, row, i):
    try:
        if df is not None and row in df.index:
            return float(df.loc[row].iloc[i])
    except Exception:
        pass
    return None

def pct(a, b):
    return round((a/b-1)*100, 1) if (a is not None and b not in (None, 0)) else None

def analyze(tkr):
    t = yf.Ticker(tkr)
    inc, info = t.financials, t.info
    rev = [g(inc, "Total Revenue", i) for i in range(3)]
    op = [g(inc, "Operating Income", i) for i in range(3)]
    ni = [g(inc, "Net Income", i) for i in range(3)]
    periods = [str(c.date()) for c in inc.columns[:3]] if (inc is not None and not inc.empty) else []
    d = {
        "name": info.get("shortName"),
        "periods(新→旧)": periods,
        "売上高": [round(x/1e8, 0) if x else None for x in rev],   # 億円(JP) / 億ドル換算ではない、通貨はinfo参照
        "通貨": info.get("financialCurrency"),
        "営業利益": [round(x/1e8, 1) if x else None for x in op],
        "純利益": [round(x/1e8, 1) if x else None for x in ni],
        "営業利益率%": [round(o/r*100, 1) if (o and r) else None for o, r in zip(op, rev)],
        "純利益率%": [round(n/r*100, 1) if (n and r) else None for n, r in zip(ni, rev)],
        "増収率YoY%": pct(rev[0], rev[1]),
        "営業増益率YoY%": pct(op[0], op[1]),
        "売上CAGR_2y%": pct(rev[0], rev[2]),
        "ROE%": round(info.get("returnOnEquity")*100, 1) if info.get("returnOnEquity") else None,
        "EPS": round(info.get("trailingEps"), 1) if info.get("trailingEps") else None,
        "PER": round(info.get("trailingPE"), 1) if info.get("trailingPE") else None,
        "予想PER": round(info.get("forwardPE"), 1) if info.get("forwardPE") else None,
        "PBR": round(info.get("priceToBook"), 2) if info.get("priceToBook") else None,
        "D/E%": round(info.get("debtToEquity"), 0) if info.get("debtToEquity") else None,
        "流動比率": round(info.get("currentRatio"), 2) if info.get("currentRatio") else None,
        "配当利回り%": info.get("dividendYield"),
        "時価総額(億)": round(info.get("marketCap")/1e8, 0) if info.get("marketCap") else None,
    }
    # PEGレシオ: yfinance提供値を優先、無ければ PER÷利益成長率% で自前計算
    peg = info.get("trailingPegRatio")
    if peg is None and d["PER"] and info.get("earningsGrowth"):
        eg = info["earningsGrowth"] * 100
        peg = d["PER"] / eg if eg > 0 else None
    d["PEG"] = round(peg, 2) if peg else None  # <1割安 / 1-2適正 / >2割高が目安。成長鈍化局面では歪む
    s = 0
    if d["増収率YoY%"] and d["増収率YoY%"] > 0: s += 1
    if d["営業増益率YoY%"] and d["営業増益率YoY%"] > 0: s += 2
    if d["ROE%"] and d["ROE%"] > 8: s += 2
    elif d["ROE%"] and d["ROE%"] > 0: s += 1
    if d["PBR"] and d["PBR"] < 1.0: s += 2
    elif d["PBR"] and d["PBR"] < 1.5: s += 1
    if d["D/E%"] is not None and d["D/E%"] < 60: s += 1
    if d["流動比率"] and d["流動比率"] > 1.5: s += 1
    if op and op[0] and op[0] > 0 and ni and ni[0] and ni[0] > 0: s += 1
    d["財務スコア(10点)"] = s
    return d

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("tickers", nargs="+")
    a = ap.parse_args()
    res = {}
    for t in a.tickers:
        try:
            res[t] = analyze(t)
        except Exception as e:
            res[t] = {"ticker": t, "error": str(e)}
    print(json.dumps(res, ensure_ascii=False, indent=2))
    with open("fundamental_results.json", "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=2)
