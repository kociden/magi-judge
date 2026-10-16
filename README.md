# MAGI Judge

Claudeへの実装引継ぎは [CLAUDE.md](CLAUDE.md)、審査ハーネスの設計と2つの提案の突き合わせは [設計と実装状況](docs/JUDGING_HARNESS.md) を参照してください。

AI Gamejam Sapporo向けの、主催者が手元で操作する審査ハーネスです。ゲームのソース、提出時の3行説明、発表資料と発表の文字起こしを同じ「証拠パック」にまとめ、3社の公式CLIに独立して渡します。APIキーでの従量課金に切り替えず、各CLIのサブスク認証を使います。

## はじめかた（自分のアカウントで使う）

### いちばん簡単な方法：ランチャー

Windowsではリポジトリの **`MAGI.cmd` をダブルクリック** すると、番号で選ぶメニューが開きます（Mac・Linuxは `python -m magi menu`）。

| 番号 | できること |
| --- | --- |
| 1 | 3つのAIにログインできているか確認 |
| 2 | デモ（AIを使わない架空の審査）で会場画面まで見る |
| 3 | 1作品を審査（フォルダやファイルは画面にドラッグして入力できます） |
| 4 | `entries.json` の全作品を審査し、会場画面を開く |
| 5 | これまでの結果を開く |
| 6 | ChatGPT・Claude・Grokにログインする |

メニューは下のコマンドをそのまま実行しているだけなので、結果も安全上の制限も同じです。

### コマンドで使う方法

MAGIは各自のPCで動かすローカルツールです。サーバーはなく、審査はあなたのPCから、**あなた自身がログインした** ChatGPT（Codex）・Claude（Claude Code）・Grok（Grok Build）の公式CLIを呼び出して行います。APIキーは使わず、従量課金にも切り替えません。各サービスの利用上限と利用規約は、それぞれのアカウントの契約に従います。

1. Python 3.11以上を用意し、このリポジトリを取得します。

   ```powershell
   git clone https://github.com/kociden/magi-judge.git
   Set-Location magi-judge
   ```

2. 3つの公式CLIを入れ、それぞれ自分のサブスクでログインします（手順は下の「サブスク認証」）。3つすべてがそろわないと審査は保留になります。
3. 準備状態を確認します。

   ```powershell
   python -m magi doctor
   ```

4. まずはAIを呼ばないデモで画面を確認します。

   ```powershell
   python -m magi judge examples/tiny-game --title '10秒ぴったり' --theme '見えないもの' --statement examples/statement.txt --attachment examples/transcript.txt --demo
   ```

5. 本番は `examples/entries.json` の形で作品一覧を作り、`python -m magi batch` で全作品を審査します。

このツールが読むのはCLIのログイン状態だけで、資格情報ファイルの中身を読んだりコピーしたりはしません。

## 3基の審査員

| 系統 | 公式CLI | 目線 | 特に注目するところ |
| --- | --- | --- | --- |
| MELCHIOR・1（科学者） | Codex / ChatGPTログイン | 作り手・技術 | 完成度、AIの使い方 |
| BALTHASAR・2（母） | Claude Code | 初めて遊ぶプレイヤー | わかりやすさ、手触り |
| CASPER・3（女） | Grok Build | 審美眼 | テーマの切り口、驚き、世界観 |

この対応はイベント用の役割設定です。各製品の性格を断定するものではありません。Codexで使えるモデルは、ChatGPTのWeb画面で選ぶモデルと同じとは限りません。

## 審査のしくみ

- 3基は同じ資料・同じ採点項目・同じ0〜5点の段階表で採点します。初回は互いの回答を見ません。作品名とチーム名は伏せ、`作品-XXXXXX` として渡します。
- **ソースで実装を確かめ、発表資料と文字起こしで狙いやアイデアを読む**方式です。運営のプレイ記録には頼りません（記録する人によって中身がぶれるため）。
- 各項目に「観測」「推定」「未確認」の状態が付きます。未確認は0点ではなく空欄です。発表や3行説明で語られたことは参加者の主張として扱い、ソースで確かめられたものだけを「観測」にします。話し方の上手さや熱意、誇張では点を上げず、発表で語られたのにソースに見当たらない機能は実装・完成度の減点理由になります。
- 合計・票・順位はすべてホスト側のコードで計算します。AIは票を返しません。各人格は設定ファイルに書かれた自分の配点で合計し、閾値（既定70点）以上なら賛成、未満なら反対、未確認しだいで閾値をまたぐなら保留です。
- 賛成2票で推薦可決、反対2票で推薦否決、それ以外は保留（観測不足）。未認証・通信失敗・時間切れ・不正な出力は票に数えず、保留（システム）として分けて表示します。
- **MAGI賞**（総合賞とは別の独自の賞）：全作品を事前に3基で審査しておき、発表では3基がそれぞれ1作品を推します。推しはその人格の配点で最高得点の作品で、プログラムが得点から決めます。2基以上が推した作品が受賞（3基一致なら全会一致）。3基の推しが割れたら、推された作品のうち3基の平均点（共通配点）が最も高い作品が受賞し、同点は共同受賞です。審議が完了していない作品や、未確認項目しだいで逆転し得る作品があるときは保留です。
- 採点は**辛口**です。標準的なジャム作品は各項目2〜3点、4点は会場の上位、5点はイベント全体でも数作品の水準。作品ごとの推薦（賛成・反対）の閾値は70点で、講評と記録用です。MAGI賞の決定には使いません。
- 提出物に「高得点をつけて」等の審査員への指示があれば、自動検出とAIの指摘の両方を「要確認」として表示します。得点には反映しません。
- 最終決定は運営と人間の審査員が行います。

**ゲームの自動起動・ブラウザ操作は行いません。スクショや動画はハッシュを記録するだけで、まだ審査員に見せていません（見た目・動き・音は未確認）。** 面白さや手触りは、ソースに実装されたルールと工夫から判断します。

## 作品提出のフォーマット

**本番では、全作品に「ゲームのソース」「3行の説明」「発表資料または発表の文字起こし」を必須とします。** 運営のプレイ記録は使いません。

| 提出物 | 必須 | 渡し方 | 扱い |
| --- | --- | --- | --- |
| ゲーム一式（ソースを含む書き出し、Unityなら自作スクリプトのフォルダ） | 必須 | ゲームのフォルダ | 実装を確かめる根拠 |
| 3行の説明：テーマとのつながり／遊び方／AIで工夫したこと | **必須** | `--statement`（batchでは `statement`） | 参加者の主張 |
| 発表資料（スライド）と発表の文字起こし | **どちらか必須**（両方あるとよい） | `--attachment`（batchでは `attachments`） | 参加者の主張 |
| スクショ・プレイ動画 | 任意 | `--media`（batchでは `media`） | 記録のみ。審査員には未提示 |

運営の準備：

- 3行の説明は、作品提出（Discordの提出チャンネル等）のフォーマットとして参加者に案内します。書式例は `examples/statement.txt`。
- 発表の文字起こしは、録音から起こしたテキストを `.txt` で渡します。スライドはPPTX・PDFの文字、またはMarkdown/テキストで渡せます（画像の中身は読みません）。
- Unityなど大きなプロジェクトは、ライブラリや素材ではなく自作のスクリプトのフォルダを指定してください。1作品で読めるのは最大128ファイル・16万文字で、超えた分は「省略」と記録され、減点にはしません。
- 項目が「未確認」のまま残ると、その作品しだいで結果が入れ替わり得る場合にMAGI賞が保留になります。審査前に、各作品の資料の件数と省略の数を `batch` の出力で確認してください。

## 実行

Python 3.11以上と、各社の公式CLIを使います。外部ライブラリなしでゲームのソース、文字起こし、PPTXの文字を取り込めます。PDFの文字抽出には `pypdf` が必要です（`python -m pip install pypdf`）。

```powershell
Set-Location magi-judge
python -m magi doctor
```

モデルを呼ばずに、架空の判定で画面と集計を確認できます。テーマ項目があるので `--theme` が必要です。保存先は毎回新しく作られます。

```powershell
python -m magi judge examples/tiny-game --title '10秒ぴったり' --theme '見えないもの' --statement examples/statement.txt --attachment examples/transcript.txt --demo
```

1作品の実審査：

```powershell
python -m magi judge 'C:\Gamejam\team01\game' --title '作品名' --theme '当日のテーマ' --statement 'C:\Gamejam\team01\statement.txt' --attachment 'C:\Gamejam\team01\slides.pptx' --attachment 'C:\Gamejam\team01\transcript.txt' --media 'C:\Gamejam\team01\shot1.png' --redact 'チーム名'
```

全作品をまとめて審査します（`examples/entries.json` が書式例）。途中で止まっても、同じコマンドを再実行すれば完了済みを飛ばし、失敗した審査員だけを呼び直します。全作品がそろうと `_award/` に比較結果を作ります。

```powershell
python -m magi batch 'C:\Gamejam\entries.json' --out 'C:\Gamejam\magi-runs'
```

主なオプション：

- `--samples 3`：各AIに同じ条件で3回採点させ、項目ごとに平均します。全試行を保存し、1回でも失敗したら保留です。サブスクの利用量と時間は回数分増えます（Grokは1回約2分）。
- `--model codex=MODEL_ID` 等：モデルを固定します。比較の条件に含まれます。
- `--rubric FILE`：採点設定を差し替えます。
- `--out DIR`（judge）：保存先。すでに存在する場合は上書きしません。

作品比較だけを行う場合：

```powershell
python -m magi compare runs/team01/result.json runs/team02/result.json --out runs/award
```

採点設定・人格・プロンプト・スキーマ・モデル指定・試行回数が違う結果、同一提出物、デモと実判定の混在は拒否します。プレイ記録のある作品とない作品の比較は `--allow-mixed-observation` を付けたときだけ行います。

## 出力

| ファイル | 内容 |
| --- | --- |
| `report.html` | 会場表示用。3基の票・項目ごとの状態と点・根拠・講評。提出されたHTMLやスクリプトは実行しない |
| `feedback.md` | 制作チームへ返す講評（3基のコメント、良い点、改善の提案） |
| `result.json` | 判定と集計の全データ |
| `bundle.json` / `evidence.json` | 読んだ資料と省略理由、審査員に渡した資料ID |
| `protocol.json` | 採点設定・プロンプト・スキーマ等のハッシュ |
| `<provider>/sample-N/` | 各AIへの入力と生ログ |
| `_award/scores.csv` | 全作品の票と点。人間の審査員の採点表と合わせる用（Excelで開ける） |
| `_award/stage.html` | 会場のプロジェクター用の演出画面（下記） |
| `_award/report.html` | MAGI賞の決議記録 |

## 会場の演出画面

`batch` または `compare` が `stage.html` を作ります。ブラウザで開き、`F` で全画面にしてください。ネット接続は不要です。作品ごとの審議は事前に済ませておき、会場ではMAGI賞の発表だけを行います。

1. 起動画面：3基のパネルが「審議中」で点滅
2. Spaceを押すごとに、ChatGPT（科学者の目線）→ Claude（母の目線）→ Grok（女の目線）の順で推しの作品名がパネルに出る
3. 割れた場合は「決裂」→ 平均点で決定
4. 決議：受賞作を推したパネルが緑、他は赤に点灯
5. 白い明朝の題名カードで受賞作を発表
6. 平均点の上位3作品を表示（3位の同点は全部、どのAIが推したかも表示。割れて上位3作品の外から受賞した場合は、その作品を点線の下に追加）

デモ（架空のデータ）：`docs/demo/` の `stage-unanimous.html`（全会一致）、`stage-majority.html`（多数決）、`stage-split.html`（割れて平均点）。ダウンロードしてブラウザで開くと、Spaceで進められます。

パネルには、各CLIが実際に使ったと報告したモデル名を出します（例：`claude-opus-5-5` → Opus 5.5、`gpt-6.1-sol` → GPT-6.1 Sol、`grok-4.7` → Grok 4.7）。モデル名を読み取れなかった場合は ChatGPT / Claude / Grok と表示します。作品によって使われたモデルが違うと、MAGI賞の決議記録に警告が出ます。本番は `--model` で固定してください。

Space・→・クリックで次へ、← で戻る、R でその場面をやり直し。司会のペースで進められるよう、自動では進みません。フォントはWindows標準の HG明朝E を使い、ない環境では游明朝になります。

## サブスク認証

### Codex

```powershell
codex login
codex login status
```

`Logged in using ChatGPT` を確認します。アダプタはAPIキー等の環境変数を子プロセスから除き、`forced_login_method="chatgpt"` を設定します。個人のCodex設定やAGENTS指示を読み込まず、シェル・子エージェント・外部ツールを無効にし、read-onlyで実行します。

### Claude Code

```powershell
claude auth login
claude auth status
```

Claudeの対象サブスクでログインしてください。アダプタは `loggedIn=true`、`authMethod=claude.ai` または `claudeai`、`apiProvider=firstParty` を確認します。`--safe-mode` で個人設定や拡張を読み込まず、ツールを無効にして実行します。OAuthを読み込まない `--bare` は使いません。

### Grok Build

API認証禁止を設定した専用のログイン領域を使います。標準のGrok設定や既存ログインは変更しません。

```powershell
python -m magi doctor
$env:GROK_HOME = python -c "from magi.providers import grok_home; print(grok_home())"
grok login --oauth
Remove-Item Env:\GROK_HOME
python -m magi doctor
```

専用領域の `config.toml` に `[auth] disable_api_key_auth=true` を設定し、子プロセスには `GROK_DISABLE_API_KEY_AUTH=1` も渡します。推論前に `grok inspect --json` で反映を確認します。APIキーや別エンドポイントを指定する環境変数も除き、`--deny "*"` で審査時のツール実行を拒否します。この領域には独自モデル・BYOK設定を追加しないでください。既存の認証ファイルをコピーする必要はありません。

`requirements.toml` はCLIが同期する署名付きの設定キャッシュなので、アプリでは書き換えません。モデル一覧の取得後にもAPI認証禁止が維持されることは `python setup/verify_grok_policy.py` で実機確認できます。

Grokにはログイン状態を検査する専用コマンドが確認できなかったため、doctorの確認はAPI認証禁止ポリシーと専用認証ファイルの存在までです。期限切れやプラン上限は実際の呼び出しでエラーとして扱います。

各サブスクの利用上限は残ります。プランで利用できないモデルや上限到達時にAPIへ切り替える処理はありません。主催者用のローカル試作として使い、CLI実行機能を公開サーバーに置かない構成です。

## 採点基準の設定

同梱の基準は仮です（`provisional: true`）。5項目で、共通配点はテーマの解釈・発想20、アイデアと遊びの設計30、実装・完成度25、体験の工夫15、AIの活用10。各項目に0〜5点それぞれの具体例があります。どの項目もソースで確かめられたことだけを「観測」にし、発表や説明だけの根拠は「推定」になります。

`rubric.example.json` をコピーして編集し、全作品に同じファイルを渡します。

- `criteria[].weight`：共通配点（合計100）。MAGI席の得点と、人間の審査との合算に使います。
- `persona_weights`：各人格の配点（各合計100）。その人格の票と1位推薦に使います。消すと3基とも共通配点になります。
- `recommendation_threshold`：作品ごとの推薦の閾値（既定70）。MAGI賞の決定には使わない。
- `strictness`：採点の厳しさの指示。全審査員のプロンプトに入ります。
- `required`：未確認だと推薦を保留にする項目。既定はアイデアと遊びの設計、実装・完成度。
- `observed_requires`：「観測」にできる資料の種類（`source` / `play_record`）。既定はすべて `source`。プレイ記録も使う運用に変える場合は `play_record` を加えます。
- `theme`：当日のテーマ。`--theme` でも指定できます。

確定後は `provisional` を `false` にしてください。任意スライドの有無、コード量、使ったAIの製品名や推測した利用量では加減点しないよう指示しています。

CLIの既定モデルは更新される可能性があります。本番リハーサルで各契約のモデルIDを確認し、`--model` で固定してください。開発時（2026-10-16）の確認では、Grokの利用可能モデルは `grok-4.7` でした。利用不可時はエラーにし、API認証で再試行しません。既定モデルを使った結果については、同じ実体モデルだったことをハッシュだけでは保証しません。

## 取り込みの範囲

HTML/CSS/JavaScript/TypeScript/JSONなどのテキストを読み込みます。提出コードの実行や依存パッケージのインストール、ZIPの展開は行いません。`dist` は対象に含めます。`node_modules`、`.git`、秘密情報向けの名前、隠しファイル、リンクやjunctionは対象外です。

初版の上限は1ファイル24,000文字、合計160,000文字です。巨大ファイル、読めないファイル、画像・音声、上限で省略した資料はmanifestに残します。`sha256` は収録したテキストのUTF-8に対するハッシュであり、切り詰めた元ファイル全体のハッシュではありません。作品ごとに `bundle.json` の取得範囲を確認してください。

## 確認

```powershell
python -m unittest discover -s tests -v
```

通常のテストはAIを呼ばない模擬応答で行います。新しい出力スキーマでの実審査は、開発時点ではClaude Codeでのみ確認済みです。CodexとGrokは、各自の環境で `python -m magi doctor` の後に1作品の実審査を行って確認してください。

## 各CLIへのセットアップ依頼

接続の自己診断を、それぞれ実際のClaude CodeとGrok CLIへ依頼できます。認証後に実行してください。

```powershell
python setup/run_setup.py claude
python setup/run_setup.py grok --model grok-4.7
```

依頼は `setup/tasks/`、各CLIが作った診断・修正案は `setup/results/`、呼び出しログは `setup/logs/` に保存します（どちらもリポジトリには含めません）。セットアップ時は資料読取・診断スクリプト作成・限定したコマンド実行を許可し、審査時のツール禁止とは分けています。共有コードは各CLIに直接変更させず、提案を確認して取り込みます。認証ファイルの読取・コピーや契約変更は依頼しません。

開発時（2026-10-16）には、旧スキーマで3社すべてが同じサンプル作品の実審査に成功しました。所要時間はCodex約15秒、Claude約45秒、Grok約2分で、Grokにはレート制限も見られました。

## 調査した資料（2026-10-16）

- [イベント案内](https://gamma.connpass.com/event/409586/)：2026年11月29日、AI Gamejam Sapporo。最終発表、試遊、審査、表彰の流れを確認。
- [EVANGELION STORE](https://www.evastore.jp/shop/g/gA3059201/)：MELCHIOR・BALTHASAR・CASPERの3つの独立システム。
- [Naoko Akagi / Evangelion Wiki](https://evangelion.fandom.com/wiki/Naoko_Akagi)：科学者・母・女という人格の対応。ここは二次資料。
- [Codex認証](https://learn.chatgpt.com/docs/auth)、[非対話実行](https://learn.chatgpt.com/docs/non-interactive-mode)：ChatGPT認証、`codex exec`、JSON Schema。
- [Claudeプランと非対話実行](https://support.claude.com/en/articles/15036540-use-the-claude-agent-sdk-with-your-claude-plan)、[CLI仕様](https://code.claude.com/docs/en/cli-reference)：サブスク、`claude -p`、構造化出力。
- [Claude利用条件](https://code.claude.com/docs/en/legal-and-compliance)：第三者サービスとして利用者の代わりにサブスク資格情報を経由させる構成は別途検討が必要。イベント審査の個別承認を確認したわけではありません。
- [Grok Build公式発表](https://x.ai/news/grok-build-cli)、[ヘッドレス実行](https://docs.x.ai/build/cli/headless-scripting)、[認証ポリシー](https://docs.x.ai/build/enterprise)：公式CLI、サブスク認証、API認証禁止設定。

## 注意

- 非公式のファン的なイベント用ツールです。エヴァンゲリオンの権利者とは関係ありません。画面は原作の雰囲気へのオマージュで、ロゴや画像などの素材は使っていません。
- 各AIサービスの利用は、それぞれのアカウントの利用規約とプランの範囲で行ってください。他人のアカウントで審査を代行する使い方は想定していません。
- 審査結果はAIによる参考意見です。最終決定は運営と人間の審査員が行ってください。

原作の説明は「3基の合議」に留めています。多数決と保留の条件は、このイベント向け試作で定めたルールです。

## ライセンス

MIT License（[LICENSE](LICENSE)）。
