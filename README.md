# mobile-kit — iPhoneのClaudeアプリで使う株式データブリーフ

PCを立ち上げずに、iPhoneの**Claudeアプリ**で個別株の投資判断(簡易版・テキストのみ)を行うためのキット。
計算は**GitHub Actions**が行い、ClaudeアプリはGitHub上の生成物(データブリーフ)を読んで判断する。

```
[GitHub Actions(毎朝cron / 手動Run)]
   ├─ scripts/ を実行(J-Quants・EDINET DB・yfinance・株探)
   └─ docs/brief/<code>.md を生成してコミット
        ↓
[iPhone]
   ├─ Claudeアプリ: ブリーフURLを渡す→カスタム指示に沿って投資判断を返す
   └─ GitHubアプリ: 任意銘柄のオンデマンド実行(Run workflow)・非公開時の閲覧
```

## できること / できないこと

| | |
|--|--|
| ✅ ウォッチリスト銘柄の毎朝自動ブリーフ | テクニカル/PER・PBR/四半期業績+進捗率/信用残/空売り機関/大株主/セクター資金流入(6期間5段階)/カタリスト |
| ✅ 任意銘柄のオンデマンド分析 | GitHubアプリから Run workflow(1〜2分で完成) |
| ✅ 別アカウントのiPhoneから閲覧 | 公開リポ=URL共有のみ / 非公開=GitHubアプリで閲覧しClaudeに貼り付け |
| ❌ チャート画像 | 簡易版はテキストのみ |
| ❌ Claudeアプリ内でのリアルタイム実行 | 原理的に不可(計算はActions側) |

## セットアップ(1回だけ・PC推奨だがスマホでも可)

1. **GitHubで新規リポジトリを作成**
   - 名前例: `stock-brief`
   - **非公開(Private)+GitHubコネクタ(手順6)**: 推奨。コネクタ経由ならClaudeが非公開リポも
     読み書きできるため、内容を守りつつ「分析して」の全自動が使える
   - **公開(Public)**: コネクタなしでもraw URLをClaudeが直接読める。ただしブリーフ内容も公開される

2. **この mobile-kit の中身をリポジトリ直下にコピーして push**
   ```
   stock-brief/
     .github/workflows/brief.yml
     scripts/            (jquants.py ほか4本)
     brief.py
     watchlist.txt
     requirements.txt
     .gitignore
   ```

3. **APIキーを GitHub Actions Secrets に登録**(⚠️ ファイルに平文で書かない)
   - リポジトリ → Settings → Secrets and variables → **Actions** → New repository secret
   - `JQUANTS_API_KEY` = J-Quants V2のAPIキー(必須)
   - `EDINET_API_KEY` = edinetdb.jp のAPIキー(大株主情報用。無くても動く)

4. **動作確認**: Actionsタブ → `stock-brief` → Run workflow → 空のまま実行
   → 数分後 `docs/brief/index.md` と銘柄別mdが生成されていれば成功

5. **claude.aiプロジェクトを作成**(判断層)
   - claude.aiで新規プロジェクト →「カスタム指示」に `claude_project_instructions.md` の内容を貼る
   - **別アカウントでも同じ指示を貼れば同じ判断アシスタントになる**(プロジェクト自体の共有は不要)

## 6. GitHubコネクタ接続(「〜を分析して」の一言で全自動にする・推奨)

claude.aiの **設定 → コネクタ → GitHub を接続**(アカウントごとに1回。別アカウントでも同様に接続)。
これでClaudeアプリが Issue作成・ファイル取得を代行できるようになり、チャットで
**「7203を分析して」と言うだけ**で以下が自動で回る:

1. Claudeが対象リポジトリに Issue `分析 7203 輸送用機器` を作成
2. GitHub Actionsが起動(1〜3分)→ ブリーフ生成 → **同じIssueに全文コメント返信**して自動クローズ
3. Claudeがコメント(またはdocs/brief/7203.md)を読んで、5段階見通し+おすすめ度を返す

コネクタなしでも下記A/Bの手動運用で使える。

## 毎日の使い方(iPhone)

**A. ウォッチリスト銘柄を見る**(平日朝7:30 JSTに自動更新済み)
Claudeアプリのプロジェクトで:
> `https://raw.githubusercontent.com/<ユーザー名>/stock-brief/main/docs/brief/6492.md` を読んで判断して

**B. 新しい銘柄をオンデマンド分析(コネクタなしの場合)**
1. GitHubアプリ(またはブラウザ) → リポジトリ → Actions → stock-brief → **Run workflow**
   - code: `7203` / sector: `輸送用機器`(東証33業種名、任意)
2. 1〜2分待って、Claudeアプリで `…/docs/brief/7203.md` を読ませる

**B'. Issueでのオンデマンド分析(コネクタなしでもGitHubアプリから可能)**
リポジトリに Issue を作るだけでもよい。タイトル: `分析 7203 輸送用機器` → 数分後に
結果がIssueコメントで返る(GitHub通知が届く)

**C. 比較**
> 6492と6356のブリーフを読み比べて、今買うならどちらか理由つきで

**D. 非公開リポジトリの場合**
GitHubアプリで `docs/brief/<code>.md` を開く→全選択コピー→Claudeアプリに貼って「判断して」

## ウォッチリストの編集

`watchlist.txt` を編集してコミット(GitHubアプリ/Webからも編集可能):
```
6492,機械
7203,輸送用機器
```
業種名は東証33業種(機械/電気機器/化学/情報・通信業など)。省略するとセクター評価だけスキップ。

## 注意事項

- **免責: 本システムの出力は投資助言ではない。** 発注・資金管理の最終責任は利用者にある。
- APIキーはSecretsにのみ置く。リポジトリのファイル・コミット履歴に書いたら即失効・再発行すること。
- 公開リポジトリでは分析結果(どの銘柄を見ているか)が第三者に見える。気になるなら非公開+コピペ運用。
- kabutan.jp はクラウドIPからのアクセスを弾く可能性がある。その場合カタリスト欄は「取得失敗」になる(他は動く)。
- J-Quants無料枠のレート制限(5リクエスト/分)に当たる場合は、watchlistを減らすか実行間隔を空ける。
