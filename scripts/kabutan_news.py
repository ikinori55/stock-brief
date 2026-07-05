# -*- coding: utf-8 -*-
"""株探(kabutan.jp)の銘柄別ニュースからカタリスト(材料・開示・決算)を取得する。

使い方:
  python kabutan_news.py 6492                # 材料+開示+決算速報を取得
  python kabutan_news.py 6492 --limit 30     # 表示件数

出力: 表(標準出力) + kabutan_news_<code>.json
注意: 個人利用の軽量スクレイピング(各モード1リクエスト、計3リクエスト)。連打しない。
"""
import os, sys, io, re, json, time, argparse
import urllib.request

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36",
      "Accept-Language": "ja"}
MODES = [("1", "材料"), ("3", "開示"), ("2", "決算")]

# 見出しからカタリスト種別を推定するキーワード
CATALYST_PAT = [
    ("上方修正", r"上方修正|増額"),
    ("下方修正", r"下方修正|減額"),
    ("決算", r"決算|営業益|経常益|最終益|純利益"),
    ("増配/株主還元", r"増配|復配|自社株買い|株主優待"),
    ("減配", r"減配|無配"),
    ("受注/契約", r"受注|契約|採用|納入"),
    ("提携/M&A", r"提携|買収|統合|子会社化|TOB|MBO"),
    ("株式分割", r"分割"),
    ("増資/希薄化", r"増資|新株予約権|売出"),
    ("テーマ/思惑", r"関連|テーマ|思惑|物色"),
    ("急騰/急落", r"ストップ高|ストップ安|急伸|急騰|急落|年初来"),
    ("レーティング", r"レーティング|目標株価|格上げ|格下げ"),
]

def fetch(code, nmode):
    url = f"https://kabutan.jp/stock/news?code={code}" + (f"&nmode={nmode}" if nmode else "")
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.read().decode("utf-8", errors="replace")

def parse(html, code):
    items = []
    # 記事リンク: /stock/news?code=XXXX&b=n2026070400061 (IDに日付が埋まる)
    for m in re.finditer(r'<a href="/stock/news\?code=' + code + r'&(?:amp;)?b=([kn]\d{8})(\d+)"[^>]*>([^<]+)</a>', html):
        bid, seq, title = m.group(1), m.group(2), m.group(3).strip()
        d = f"{bid[1:5]}-{bid[5:7]}-{bid[7:9]}"
        kinds = [name for name, pat in CATALYST_PAT if re.search(pat, title)]
        items.append({"date": d, "title": title, "kinds": kinds, "id": bid + seq})
    return items

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("code")
    ap.add_argument("--limit", type=int, default=25)
    a = ap.parse_args()
    code = a.code.replace(".T", "")

    all_items, seen = [], set()
    for nmode, label in MODES:
        try:
            html = fetch(code, nmode)
        except Exception as e:
            print(f"[{label}] 取得失敗: {e}", file=sys.stderr)
            continue
        got = parse(html, code)
        for it in got:
            if it["id"] not in seen:
                seen.add(it["id"])
                it["source"] = label
                all_items.append(it)
        time.sleep(1)  # 行儀よく

    all_items.sort(key=lambda x: x["date"], reverse=True)
    print(f"===== {code} 株探ニュース/カタリスト({len(all_items)}件) 出典: kabutan.jp =====")
    print(f"{'日付':<12}{'種別':<16}{'区分':<6}見出し")
    for it in all_items[:a.limit]:
        kinds = ",".join(it["kinds"]) or "-"
        print(f"{it['date']:<12}{kinds[:15]:<16}{it['source']:<6}{it['title'][:60]}")

    out = f"kabutan_news_{code}.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump({"code": code, "items": all_items}, f, ensure_ascii=False, indent=1)
    print(f"\n[saved] {out}")

if __name__ == "__main__":
    main()
