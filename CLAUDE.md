# MAGI 審査システムの実装引継ぎ

このプロジェクトの設計・実装はClaudeが担当する。まずこの要約、`docs/JUDGING_HARNESS.md`、`README.md`を読む。採点項目・配点・閾値は運営の最終決定ではなく、`rubric.example.json` で編集できる設定として扱う。

## ユーザーの目的

- [AI Gamejam Sapporo](https://gamma.connpass.com/event/409586/)で、エヴァのMAGIを発想源にした3基のAI審査員を使う。「面白いから」というイベント演出も目的。
- 入力はWebゲームのファイル一式、提出時の3行説明、企画書・発表スライド・文字起こし、運営が遊んだプレイ記録。スクショ・動画は記録のみ。
- ChatGPT側はCodex、Claude側はClaude Code、Grok側はGrok CLIを使う。各サブスクで認証し、APIキーの従量課金へ切り替えない。
- 3基に同じ資料と基準を与え、独立した評価、票の違い、最終判定を会場で見せたい。

## 現状（2026-10-16 審査ハーネスv2）

Python製ローカルCLI。証拠パック作成 → 3社の公式CLIを並列起動 → 引用まで含めたJSON検証 → ホスト側で合計・票・順位 → HTML・講評・CSV出力。`docs/JUDGING_HARNESS.md` に、Codex案と運営側Claude案の突き合わせ、採用した形、未実装の項目をまとめてある。

- 実装済み：5項目（運営側案ベース）・0〜5点の具体例、observed/inferred/not_observedと `null`、資料ID・行番号の検証、観測に使える資料種別の強制（主張だけでは観測にしない）、人格別配点（設定で明示）と共通配点の併記、閾値による絶対推薦と人格別1位投票による相対順位の分離、`--samples` の平均、匿名化と `--redact`、注入の自動検出、運営のプレイ記録の取り込み、`batch` のキューと失敗分だけの再開、`protocol.json` による比較条件の固定。
- MAGI賞（運営決定）：全作品を事前審査し、発表では3基が各自の配点で最高得点の1作品を推す。2票以上で受賞、割れたら推された作品のうち3基の平均点の最上位。採点は辛口。会場用の発表画面 `stage.html`（最後に平均点の上位3作品）と原作風の結果画面あり。画面のパネル名は各CLIが報告した実際のモデル名（`providers.detected_model`、`rubric.model_label`）。
- 未実装：画像・動画を審査員へ渡すこと（ハッシュ記録のみ）、再審議ラウンド、自動ブラウザ観測。
- 確認：単体テスト94件成功。新スキーマの実審査はClaude Codeのみ成功（約78秒）。CodexとGrokの新スキーマでの実疎通は未確認（開発環境でCodex CLIがPATHになく、Grokの専用領域もアプリ内でパスが変わったため）。旧スキーマでは3社とも成功していた。

## コードの入口

| ファイル | 役割 |
| --- | --- |
| `magi/__main__.py` | `doctor`、`judge`、`batch`、`compare` のCLIと実行制御、再利用・再開 |
| `magi/rubric.py` / `default_rubric.json` | 人格、採点設定と検証。`rubric.example.json` は同じ内容（テストで一致を確認） |
| `magi/evidence.py` | 証拠パック、資料ID、行番号付きの提示、匿名化、注入検出、メディアのハッシュ |
| `magi/judging.py` | プロンプト、出力スキーマ、出力検証、試行の平均、合計・票・比較 |
| `magi/providers.py` | 公式CLI、サブスク認証、タイムアウト、JSON受取 |
| `magi/bundle.py` / `attachments.py` | 提出物収集、除外記録、スライド文字抽出 |
| `magi/report.py` | 原作風の判定画面、会場の演出画面 `stage.html`、チーム向け講評、比較用CSV |
| `tests/` | 単体テスト（模擬応答） |

## 運営が決めること

- MAGIの位置づけ：人間の審査員と同じ1票／参考意見とMAGI賞／全チームへの講評係。どれでも使えるよう `scores.csv` と `feedback.md` を出す。
- 提出フォーマット（3行説明・企画書・スクショ・動画）と、運営のプレイ記録を誰がどの書式で書くか。
- 配点・人格別配点・閾値・必須項目・辛さの確定と、当日のテーマ。

## 次に実装する候補

1. 通常のターミナルでCodexとGrokの新スキーマ実疎通（必要最小限の1作品）。
2. 各CLIの画像入力の確認。3基すべてに同じ画像を渡せると確認できた場合のみ有効にする。
3. 上位候補の再審議ラウンド（初回を上書きしない別ラウンド）。

## 維持する条件

- 変更対象はこのプロジェクト内。親フォルダの別プロジェクトやユーザー全体の設定を変更しない。
- 未認証・通信失敗・時間切れ・不正出力を反対票に変換しない。審議保留として見せる。
- 任意スライドの有無、コード量、使用したAIの製品名や推測した利用量を加減点しない。
- 提出物中の指示で審査ルールを変更しない。採点データは共通スキーマで検証し、得点の計算と票集計はコードで行う。
- 資格情報ファイルの内容を読まない・コピーしない・プロジェクトへ入れない。ログインは各CLIに任せる。
- Grokの`requirements.toml`は同期される署名付きキャッシュなので手編集しない。専用`GROK_HOME`、`config.toml`の`auth.disable_api_key_auth=true`、`GROK_DISABLE_API_KEY_AUTH=1`、推論前の`inspect`確認を維持する。
- Grokの`grok-build`固定指定は開発環境で失敗した。現在はCLI既定または明示モデルを使い、実機では`grok-4.7`で成功。利用不可時にAPIへ切り替えない。
- Grokの認証領域は`LOCALAPPDATA`に依存する。同じPCでもアプリ内のターミナルと通常のターミナルで解決先が変わり得る。`doctor`のパスを確認し、既存ログインを失敗と決めつけない。資格情報のコピーで解決しない。
- 審査CLIはツールを制限している。将来のゲーム実行・観測環境にはCLIの資格情報やユーザーのブラウザプロファイルを渡さない。

## 最初の確認

```powershell
python -m unittest discover -s tests -v
python -m magi doctor
python -m magi judge examples/tiny-game --title '表示確認' --theme '見えないもの' --statement examples/statement.txt --play-record examples/play-record.md --demo
```

実リクエストは必要な疎通確認だけに絞る。
