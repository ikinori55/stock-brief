# -*- coding: utf-8 -*-
"""テクニカル分析 + ゴールデンクロス・バックテスト
使い方: python technical.py 5942.T 8103.T 6955.T  [--period 5y] [--short 50 --long 200]
日本株は ticker に .T を付与 (例 7203.T)。米国株はそのまま (例 AAPL)。
結果は標準出力(JSON)と technical_results.json に保存。
"""
import sys, io, json, argparse
import numpy as np
import pandas as pd
import yfinance as yf

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

def rsi(s, n=14):
    d = s.diff()
    g = d.clip(lower=0).rolling(n).mean()
    l = (-d.clip(upper=0)).rolling(n).mean()
    return 100 - (100 / (1 + g / l))

def macd(s, fast=12, slow=26, sig=9):
    line = s.ewm(span=fast, adjust=False).mean() - s.ewm(span=slow, adjust=False).mean()
    signal = line.ewm(span=sig, adjust=False).mean()
    return line - signal  # histogram

def backtest_gc(df, short, long):
    """ショートMAがロングMAを上抜けで買い・下抜けで売り（ロングオンリー）。
    約定は翌日近似（前日ポジションを当日リターンに適用）、手数料は未考慮。"""
    d = df.copy()
    d["s"] = d["Close"].rolling(short).mean()
    d["l"] = d["Close"].rolling(long).mean()
    d = d.dropna(subset=["s", "l"]).copy()
    if len(d) < 2:
        return None
    d["pos"] = (d["s"] > d["l"]).astype(int)
    d["sig"] = d["pos"].diff()
    d["ret"] = d["Close"].pct_change().fillna(0)
    d["strat_ret"] = d["pos"].shift(1).fillna(0) * d["ret"]
    trades, entry_px, entry_dt = [], None, None
    for dt, row in d.iterrows():
        if row["sig"] == 1:
            entry_px, entry_dt = row["Close"], dt
        elif row["sig"] == -1 and entry_px is not None:
            trades.append({"in": entry_dt.date().isoformat(), "out": dt.date().isoformat(),
                           "ret%": round((row["Close"]/entry_px-1)*100, 2)})
            entry_px = None
    open_trade = None
    if entry_px is not None:
        last = d.iloc[-1]
        open_trade = {"in": entry_dt.date().isoformat(), "out": "OPEN",
                      "ret%": round((last["Close"]/entry_px-1)*100, 2)}
    eq = (1 + d["strat_ret"]).cumprod()
    bh = (1 + d["ret"]).cumprod()
    rets = [t["ret%"] for t in trades]
    n = len(trades)
    return {
        "params": f"{short}/{long}",
        "trades": n,
        "win_rate%": round(100*sum(r > 0 for r in rets)/n, 1) if n else None,
        "avg_ret%": round(float(np.mean(rets)), 2) if n else None,
        "best%": round(max(rets), 2) if n else None,
        "worst%": round(min(rets), 2) if n else None,
        "strat_total%": round((eq.iloc[-1]-1)*100, 1),
        "buyhold_total%": round((bh.iloc[-1]-1)*100, 1),
        "strat_maxDD%": round((eq/eq.cummax()-1).min()*100, 1),
        "period": f"{d.index[0].date()} 〜 {d.index[-1].date()}",
        "recent_trades": trades[-5:],
        "open_trade": open_trade,
    }

def analyze(tkr, period, short, long):
    out = {"ticker": tkr}
    df = yf.download(tkr, period=period, interval="1d", auto_adjust=True, progress=False)
    if df.empty:
        out["error"] = "no data (ティッカー確認: 日本株は.T付与)"
        return out
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    c = df["Close"]
    last = float(c.iloc[-1])
    out["last_date"] = df.index[-1].date().isoformat()
    out["price"] = round(last, 2)
    for w in (25, 50, 75, 200):
        df[f"ma{w}"] = c.rolling(w).mean()
    out["ma25"] = round(float(df["ma25"].iloc[-1]), 2)
    out["ma200"] = round(float(df["ma200"].iloc[-1]), 2)
    out["vs_ma25%"] = round((last/df["ma25"].iloc[-1]-1)*100, 1)
    out["vs_ma200%"] = round((last/df["ma200"].iloc[-1]-1)*100, 1)
    out["rsi14"] = round(float(rsi(c).iloc[-1]), 1)
    h = macd(c).iloc[-1]
    out["macd_hist"] = round(float(h), 3)
    out["macd_state"] = "強気(>0)" if h > 0 else "弱気(<0)"
    out["chg_1m%"] = round((last/float(c.iloc[-21])-1)*100, 1) if len(c) > 21 else None
    out["chg_3m%"] = round((last/float(c.iloc[-63])-1)*100, 1) if len(c) > 63 else None
    out["chg_1y%"] = round((last/float(c.iloc[-252])-1)*100, 1) if len(c) > 252 else None
    out["vol_ann%"] = round(float(c.pct_change().std()*np.sqrt(252)*100), 1)
    out["hi_52w"] = round(float(c.iloc[-252:].max()), 2) if len(c) > 252 else None
    out["lo_52w"] = round(float(c.iloc[-252:].min()), 2) if len(c) > 252 else None
    out["gc_state"] = "ゴールデンクロス(50>200)" if df["ma50"].iloc[-1] > df["ma200"].iloc[-1] else "デッドクロス(50<200)"
    out[f"backtest_{short}_{long}"] = backtest_gc(df, short, long)
    out["backtest_25_75"] = backtest_gc(df, 25, 75)
    return out

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("tickers", nargs="+")
    ap.add_argument("--period", default="5y")
    ap.add_argument("--short", type=int, default=50)
    ap.add_argument("--long", type=int, default=200)
    a = ap.parse_args()
    res = {}
    for t in a.tickers:
        try:
            res[t] = analyze(t, a.period, a.short, a.long)
        except Exception as e:
            res[t] = {"ticker": t, "error": str(e)}
    print(json.dumps(res, ensure_ascii=False, indent=2))
    with open("technical_results.json", "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=2)
