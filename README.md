# kindle_shot

電子書籍のスクリーンキャプチャ・PDF読込・トリミング・PDF変換・OCR統合ツール（Windows / macOS）

Kindle・楽天Kobo・Google Play ブックスなどのビューアで表示中のページを自動キャプチャしたり、手元の
PDF（自炊スキャン・購入済PDF）を読み込んで、トリミング・PDF化・テキスト抽出（OCR）まで一連の処理を
行います。

```
[1a. キャプチャ]  ┐
                  ├→ 2. トリミング → 3. 変換（PDF / Markdown）
[1b. PDF読込  ]  ┘
```

## この README の読み方（想定読者）

- **GUI だけ使う人は、この README を読む必要はありません。** `setup.bat` → `run.bat`
  （macOS は `setup.command` → `run.command`）で起動し、
  画面の案内（ウィザード）に従えば取り込みから書き出しまで完結します。読むのは
  [セットアップ](#セットアップ) の節だけで十分です。
- **この README の本体は CLI 利用者向けです。** 無人実行・バッチ処理・エージェントからの呼び出し、
  出力形式やOCRの細かい制御、プロファイルの自作といった「GUI に出していない操作」をここにまとめています。
- GUI に出していない設定はすべて CLI と `core/config.json` に残っています（機能は減っていません）。

---

## セットアップ

### 動作環境

- Windows 10 / 11、または macOS 12 以降（Apple シリコン / Intel。macOS は [macOS で使う](#macos-で使う) を参照）
- Python 3.11〜3.13
  - 依存パッケージ（numpy・Pillow・opencv など）が 3.11〜3.13 向けのビルド済み wheel しか配布して
    いないため、3.14 以降・3.10 以前ではインストールに失敗します
  - **「embeddable」版は使えません**。tkinter を含まないため GUI が起動しません。python.org の
    通常インストーラー版を使ってください

### setup.bat（推奨）

1. `kindle_shot.zip` を右クリック →「すべて展開」
2. 展開したフォルダの `setup.bat` をダブルクリック
3. 完了表示が出たら `run.bat`（GUI）または `kindle_shot.bat`（CLI）を使う

`setup.bat` は次を順に実行します。

1. **システム Python の検出**（3.11〜3.13 か・tkinter を含むか）
2. **`python` が無い／対象外バージョン（3.14 など）なら、py ランチャーで既にインストール済みの
   3.13 → 3.12 → 3.11 を探し、あればそれを使う**（winget は使いません）
3. **それも無ければ、winget で Python 3.12 を自動インストール**
   （`winget install --id Python.Python.3.12 -e --silent`）。
   既存の Python は残したまま 3.12 を併用導入します
4. 仮想環境 `kindle_env` の作成と `requirements.txt` の `pip install`
5. NDLOCR-Lite の取得（git があれば clone、無ければ PowerShell で zip 取得）と依存インストール

初回は 5〜10 分ほどかかります。

自動インストールに関する注意:

- インストール直後は**同じウィンドウの PATH が更新されない**ため、setup.bat は py ランチャーと
  python.org 版の既定インストール先（`%LocalAppData%\Programs\Python\Python312`、
  `%ProgramFiles%\Python312`、`%SystemDrive%\Python312`）を直接探して続行します。
  それでも見つからない場合は「新しいウィンドウで setup.bat を再実行してください」と案内して止まります
- 別の Python の py ランチャーが「全ユーザー向け」に入っている PC では、管理者権限なしの winget が
  ランチャーの更新で失敗（終了コード 1625）して全体が巻き戻されるため、setup.bat は自動的に
  **py ランチャーを含めない設定で再試行**します（既存のランチャーから `py -3.12` で使えます）
- winget が無い環境（古い Windows 10 など）や再試行も失敗した場合は、python.org からの手動導入を
  案内して停止します
- 既に 3.11〜3.13 の Python がある場合（`python` が別バージョンでも py ランチャーから見つかれば）は自動インストールに入りません
- `run.bat` はアプリがエラーで終了してもウィンドウを閉じず、メッセージを残します

### macOS で使う

はじめての方は、上から順番にやれば使えるようになります（所要 20〜30 分、初回だけ）。

#### 手順 1. Python（パイソン）を入れる

このアプリを動かすための土台です。

1. Safari などで https://www.python.org/downloads/macos/ を開く
2. 「Python 3.12.○」（○は数字）の下にある **「macOS 64-bit universal2 installer」** をクリックしてダウンロード
   - 3.13 や 3.11 でも動きます。**3.14 以降は動かない**ので注意
3. ダウンロードした `python-3.12.○-macos11.pkg` をダブルクリックし、「続ける」「同意する」「インストール」と進む
   （Mac のパスワードを聞かれたら入力）
4. 「インストールが完了しました」と出たら閉じる

#### 手順 2. ターミナルを開く

ターミナルは、文字で Mac に指示を出すアプリです。

1. **Command + スペース** を押して Spotlight 検索を出す
2. `ターミナル`（または `terminal`）と入力して **return** キー
3. 白か黒の文字だけのウィンドウが開けば OK

#### 手順 3. セットアップ（初回だけ）

1. kindle_shot の zip をダブルクリックして展開する（「kindle_shot」フォルダができます）
2. ターミナルに `cd` と入力し、**半角スペースを1つ**入れる（まだ return は押さない）
3. Finder から **kindle_shot フォルダをターミナルのウィンドウへドラッグ＆ドロップ**する
   → フォルダの場所が自動で入力されます
4. **return** キーを押す
5. 次の1行を入力して **return**

   ```sh
   bash setup.sh
   ```

6. 文字がたくさん流れます。数分〜10分ほど待ち、最後に **「セットアップが完了しました」** と出れば成功
   - 「Python が見つかりません」と出たら、手順 1 をやり直してから、ターミナルで手順 3 の 2〜5 をもう一度

#### 手順 4. Mac の許可を出す（初回だけ・キャプチャに必須）

Mac は安全のため、アプリが「画面を撮る」「キーを押す」には許可が必要です。**どちらか1つでも欠けると
キャプチャできません。**

1. 画面左上の **りんごマーク → システム設定** を開く
2. 左の一覧から **プライバシーとセキュリティ** を選ぶ
3. 右側を下へスクロールして **画面収録**（macOS 15 以降は「画面収録とシステムオーディオ録音」）を開く
4. 一覧の **ターミナル** のスイッチをオンにする
   - 一覧に無いときは、下の **＋** を押す →「アプリケーション」→「ユーティリティ」→「ターミナル」を選んで「開く」
   - パスワードや指紋を求められたら入力する
5. 「プライバシーとセキュリティ」に戻り、今度は **アクセシビリティ** を開いて、同じように **ターミナル** をオンにする
6. **ターミナルを一度完全に終了する**（ターミナルを前面にして **Command + Q**）
   → 許可はターミナルを開き直してから有効になります

#### 手順 5. アプリを起動する（2回目以降はここだけ）

1. ターミナルを開く（手順 2）
2. `cd` + 半角スペース → kindle_shot フォルダをドラッグ＆ドロップ → **return**（手順 3 の 2〜4 と同じ）
3. 次を入力して **return**

   ```sh
   bash run.sh
   ```

4. kindle_shot の画面が開けば成功。あとは画面の案内どおりに進めてください
   - アプリを使っている間、**ターミナルは閉じないでください**（閉じるとアプリも終了します）
   - 終わるときはアプリの画面を閉じれば OK

#### キャプチャのときのコツ

- 「キャプチャ開始」を押すと数秒の待ち時間があります。その間に本の画面で
  **Control + Command + F**（3つ同時押し）を押して全画面にしてください（Windows の F11 の代わり）
- キャプチャ中はマウスやキーボードを触らないでください
- 「ウィンドウが見つかりません」「権限が許可されていません」と出たら、手順 4 の許可と
  ターミナルの再起動をもう一度確認してください

#### 詳しい人向けの補足

- `setup.sh` は Python 3.11〜3.13（tkinter 付き）を探して仮想環境 `kindle_env` を作り、依存パッケージと
  NDLOCR-Lite を導入します。Python の自動インストールはしません
- Homebrew の Python を使う場合は tkinter が別パッケージです: `brew install python@3.12 python-tk@3.12`
- CLI は `bash kindle_shot.sh <コマンド>`。Finder からダブルクリックで起動できる `setup.command` / `run.command`
  もありますが、ダウンロードしたファイルは Mac のセキュリティで止められることがあるため、上の
  ターミナル手順をおすすめします
- 権限の用途: 画面収録 = ウィンドウ名の取得・画面キャプチャ、アクセシビリティ = ページめくりのキー送信・ウィンドウの前面化

**Windows との違い**

- 全画面化のキーは **F11 ではなく Control+Command+F**（Chrome・Kindle アプリ共通）。GUI の案内や
  `open` コマンドの自動全画面化も macOS ではこのキーを使います
- プロファイルの `process_name`（`chrome.exe` / `Kindle.exe`）は macOS ではアプリ名
  （`Google Chrome` / `Kindle`）に自動で読み替えます。カスタムプロファイルではアプリ名をそのまま
  書いても構いません
- Retina ディスプレイでは物理ピクセル（ポイントの2倍など）でキャプチャします。手動クロップ
  （`manual_left` / `manual_right`）の座標もこの画像上のピクセルです
- `click_position: "top_left"`（Kindle アプリ）は macOS ではクリックしません（左上に閉じる/最小化
  ボタンがあるため。前面化だけでキー入力が届きます）
- スリープ抑止は `caffeinate` で行います
- 検索可能PDF・テキストPDFの埋め込みフォントは、ヒラギノが reportlab で読めない形式のため
  `Arial Unicode`（macOS 標準）を使います。`NotoSansJP-Regular.ttf` を `~/Library/Fonts` に
  入れておくとそちらを優先します
- CLI の例の `kindle_shot.bat` は `./kindle_shot.sh` に、`C:\books` のようなパスは `~/books` などに
  読み替えてください

### 手動セットアップ

```bat
cd kindle_shot
python -m venv kindle_env
kindle_env\Scripts\activate
pip install -r requirements.txt
git clone https://github.com/ndl-lab/ndlocr-lite.git
pip install -r ndlocr-lite\requirements.txt
```

macOS:

```sh
cd kindle_shot
python3.12 -m venv kindle_env
source kindle_env/bin/activate
pip install -r requirements.txt
git clone https://github.com/ndl-lab/ndlocr-lite.git
pip install -r ndlocr-lite/requirements.txt
```

### トラブルシュート

| 症状 | 対処 |
|------|------|
| `[ERROR] 対応する Python（3.11 - 3.13）が必要です。` | winget が使えない環境。python.org の通常インストーラーで 3.12 を入れ、「Add python.exe to PATH」にチェックして setup.bat を再実行 |
| `[INFO] winget は完了しましたが、このウィンドウからは Python 3.12 が見つかりません。` | ウィンドウを閉じて**新しいウィンドウ**で setup.bat を再実行。それでも同じなら winget の出力にエラーが無いか確認し、python.org から手動導入 |
| `[ERROR] この Python には tkinter / tcl / tk がありません。` | embeddable 版・最小構成の Python。python.org の通常インストーラー版を入れ直す |
| `[ERROR] 依存パッケージのインストールに失敗しました。` | Python のバージョンか、ネットワーク／プロキシ／アンチウイルスの遮断。pip の出力を確認する |
| `[WARN] NDLOCR-Lite の取得に失敗しました。` | OCR なしでも動く（キャプチャ・トリミング・画像PDF は可）。後述の手動導入で追加できる |

### OCR エンジン（NDLOCR-Lite）

テキストPDF / 検索できるPDF / Markdown には OCR が必要です。**画像PDF には不要です。**
本ツールは国立国会図書館の **NDLOCR-Lite** 単一構成で、`kindle_shot/ndlocr-lite/` に配置されます
（GPU 不要・CPU のみで動作）。

自動取得に失敗した場合は後から手動で導入できます。

```bat
git clone https://github.com/ndl-lab/ndlocr-lite.git
kindle_env\Scripts\activate
pip install -r ndlocr-lite\requirements.txt
```

導入できているかは `kindle_shot.bat check` で確認できます。

---

## GUI

`run.bat` をダブルクリックすると GUI（ウィザード）が起動します。

- 1画面ずつ進む一本道です。**画面の案内に従って操作してください**（ホーム → 取り込み → 余白を整える
  → 書き出す → 完了）。主要なボタンは常に画面下部のバーに出ます
- 取り込み方は「電子書籍を画面から取り込む」「手持ちのPDFを取り込む」の2択
- 出力形式は「画像PDF（既定）／検索できるPDF／Markdown」の3択
- **キャプチャは「キャプチャ開始」を押してから数秒の待機があります。その間にビューアを F11（macOS は Control+Command+F）で
  全画面にしてください**（すでに全画面ならそのまま待つ）。残り秒数は画面に表示されます
- キャプチャ設定の「保存先フォルダ」はページ画像を置く**作業用フォルダ**です（初期値は
  `%USERPROFILE%\Documents\kindle_shot`。この下に「タイトル」名のフォルダを作ります）。
  PDF / Markdown の**書き出し先は「書き出す」画面で別に選びます**
- 待機時間・OCR前処理・置換辞書・Markdown の詳細などは GUI には出していません。`core/config.json` の
  既定値で動きます。変えたいときは CLI か config.json を使ってください
- 取り込み範囲の手動指定（左右のピクセル座標）は GUI にはありません。`core/config.json` のプロファイルで
  `boundary_method` / `manual_left` / `manual_right` を指定してください（[プロファイル](#カスタムプロファイル--ビルトインの差分上書き)）

コマンドラインから起動する場合:

```bat
kindle_env\Scripts\activate
python app.py
```

---

## CLI リファレンス

GUI と同じ処理を `cli.py` からコマンドラインで実行できます。エージェントやバッチスクリプトからの
無人運用を想定しており、**ダイアログを一切出さず**、進捗・結果は標準出力と終了コードで返します。

```bat
kindle_shot.bat <コマンド> [オプション]
rem または
kindle_env\Scripts\python.exe cli.py <コマンド> [オプション]
```

各コマンドの全オプションは `kindle_shot.bat <コマンド> --help` で確認できます。

### コマンド一覧

| コマンド | 内容 |
|---------|------|
| `run` | 1冊を通しで実行（open → capture → validate → trim → convert） |
| `batch` | 複数冊を JSON リストから一括実行（各本を `run` と同じ手順で処理。完成済みはスキップして再開） |
| `open` | Kindle Cloud Reader で本を開き、全画面化して先頭ページに合わせる |
| `capture` | 電子書籍ビューアのページを自動キャプチャ |
| `pdf` | 外部PDFを画像フォルダに展開（trim / convert の入力を作る） |
| `trim` | 画像フォルダの余白を一括トリミング |
| `convert` | 画像フォルダを PDF / Markdown に変換（必要に応じて OCR） |
| `validate` | キャプチャ結果の機械検証（白紙・重複・サイズ違い・ページ数） |
| `check` | 環境診断（OCR エンジン・依存パッケージ・対象ウィンドウ） |
| `profiles` | キャプチャプロファイルの一覧表示 |

### 目的別の最短ルート

```bat
rem A. Kindle の本を1コマンドで検索可能PDFにする（open → capture → validate → trim → convert）
kindle_shot.bat run --asin B0XXXXXXXX --title 本のタイトル --out C:\books

rem B. NotebookLM に入れる Markdown を作る
kindle_shot.bat run --asin B0XXXXXXXX --title 本のタイトル --out C:\books --format markdown

rem C. 手元の PDF をテキスト化する
kindle_shot.bat pdf     --in C:\books\本.pdf --out C:\books\本 --dpi 200
kindle_shot.bat trim    --in C:\books\本 --out C:\books\本_trimmed --auto
kindle_shot.bat convert --in C:\books\本_trimmed --out C:\books --format markdown --name 本

rem D. 複数冊を一括処理
kindle_shot.bat batch --books books.json --out C:\books

rem 事前確認: 環境と対象ウィンドウの検出可否
kindle_shot.bat check --profile kindle_cloud
```

- ASIN は Amazon の商品ページ URL（`.../dp/B0XXXXXXXX/...`）または「登録情報」欄で確認できます
- A の出来上がりは `C:\books\本のタイトル.pdf`。途中生成物として `C:\books\本のタイトル\`（キャプチャ
  画像）と `C:\books\本のタイトル_trimmed\`（トリミング済み画像）が残ります
- 初めて使うときは `--max-pages 20` を付けて短く試すのが安全です
- **キャプチャ中は PC を占有します**（マウス・キーボードに触れない）
- 先頭ページへの巻き戻しは Kindle の読書位置（Whispersync）を動かします。読みかけの本は注意

### `run` — 1冊通し実行

| オプション | 既定 | 意味 |
|-----------|------|------|
| `--title` | （必須） | タイトル。保存フォルダ名・出力ファイル名になる |
| `--out` | （必須） | 保存先フォルダ |
| `--asin` / `--url` | なし | 指定すると Cloud Reader で本を開くところから実行。省略時はキャプチャから（本を開いておくこと） |
| `--profile` | `kindle_cloud` | キャプチャプロファイル |
| `--format` | `searchable_pdf` | `image_pdf` / `text_pdf` / `searchable_pdf` / `markdown` |
| `--page-turn` | プロファイルの値 | ページめくりキー（`right` / `left` / `pagedown` / `pageup` / `down` / `up`） |
| `--page-wait` | プロファイルの値 | ページ変化検出のポーリング間隔（秒） |
| `--max-pages` | なし | キャプチャの上限ページ数（暴走防止・お試し実行に） |
| `--expect-pages` | なし | validate で確認する期待ページ数（不足ならエラー停止） |
| `--safety` | `8` | トリミング自動検出の安全マージン（px） |
| `--min-margins L,R,T,B` | kindle_cloud のみ `0,0,80,80` | トリミングで最低限削る余白（ビューアの常時表示UI除去用） |
| `--no-ui-bands` | オフ（検出は有効） | ページ間の変化からビューアの固定UI帯（書名ヘッダー・ページ番号フッター）を検出して削る処理を無効にする |
| `--overwrite` | オフ | 保存先・トリミング先の既存画像を削除してから実行 |
| `--no-rewind` / `--max-rewind` / `--load-wait` | - / `1000` / `45` | open の巻き戻し・読み込み待ちの調整 |
| `--ocr-workers` | config の `ocr.workers` | ndlocr-lite の並列プロセス数 |
| `--faithful` / `--no-cleanup` / `--split-words` | - | Markdown の形式・クリーニング・分割出力（[Markdown 出力](#markdown-出力notebooklm-最適化)） |

### `batch` — 複数冊の一括実行

| オプション | 既定 | 意味 |
|-----------|------|------|
| `--books` | （必須） | 本リストの JSON ファイル（[batch ファイル形式](#batch-ファイル形式)） |
| `--out` | （必須） | 全本共通の保存先フォルダ（直下に `<title>.pdf` / `.md` が並ぶ） |
| `--profile` / `--format` / `--page-turn` / `--page-wait` / `--expect-pages` / `--max-pages` / `--max-rewind` / `--load-wait` / `--no-rewind` / `--safety` / `--min-margins` / `--no-ui-bands` / `--ocr-workers` / `--faithful` / `--no-cleanup` / `--split-words` | `run` と同じ | **全本の既定**。JSON 側の本ごとの指定がこれを上書きする |
| `--overwrite` | オフ | 完成済み（出力ファイルがある）本も再処理する。既定は完成済みをスキップして途中から再開 |
| `--stop-on-error` | オフ | 1冊でも失敗したらバッチを中断（既定は続行して末尾に成功/失敗の一覧を出す） |

途中で失敗しても残りは処理を続け、末尾の `batch_summary` で成功/失敗/スキップ数と失敗した本の一覧を
報告します（1冊でも失敗すると終了コードは非0）。同じコマンドを再実行すると完成済みの本は自動で
スキップされます。

### `open`

Kindle Cloud Reader で「URL で本を開く → 読み込み完了を待つ → F11 全画面 → UI バーを非表示化 →
ページが変化しなくなるまで戻して先頭ページへ」を自動で行います。

`--asin` / `--url`（どちらか必須）, `--profile`（既定 `kindle_cloud`）, `--page-turn`,
`--no-fullscreen`, `--no-rewind`, `--max-rewind`（既定 1000）, `--load-wait`（既定 45 秒）

### `capture`

`--profile`（必須）, `--title`（必須）, `--out`（必須）, `--page-turn`, `--page-wait`,
`--max-pages`, `--overwrite`

- 保存先は `<--out>/<title>/`。画像は `001.png`, `002.png`, … の連番
- 最終ページに到達（ページが変化しなくなる）すると自動停止します
- 完了時に保存先へ `manifest.json` を書き出します
- 実行前に対象ビューアで本を開き、**先頭ページを表示**しておくこと

### `pdf`

`--in`（必須・PDFファイル）, `--out`（省略時は PDF と同じ場所の `<PDF名>_pages`）,
`--dpi`（既定 200。OCR 目的なら 200〜300、印刷向けなら 300〜400）,
`--format`（`png` / `jpg`、既定 `png`）, `--overwrite`

### `trim`

| オプション | 意味 |
|-----------|------|
| `--in`（必須） | 入力画像フォルダ |
| `--auto` / `--margins L,R,T,B` | どちらか必須。全ページ走査の自動検出 / 直接指定 |
| `--out` | 出力フォルダ（`--dry-run` 時は省略可） |
| `--dry-run` | マージンの決定と検証だけ行い、トリミングは実行しない（値の下見に便利） |
| `--safety` | `--auto` 時に検出値から差し引く安全マージン（既定 8px） |
| `--min-margins L,R,T,B` | `--auto` 時に最低限削る余白。ビューアの常時表示UI（書名ヘッダー・ページ番号フッター）の除去に使う |
| `--no-ui-bands` | `--auto` 時に、ページ間の変化からビューアの固定UI帯を検出して削る処理を無効にする（既定は有効） |
| `--threshold` | 背景との輝度差しきい値（既定 12）。余白検出と全面表示ページの判定に使う |
| `--passthrough` / `--no-passthrough` | 全面表示と判定したページ（表紙・購入画面など）を無加工でコピーする / しない。既定は `--auto` 時 ON・`--margins` 時 OFF |
| `--no-check` / `--force` | `--margins` 指定時の「内容が切れないか」検証をスキップ / 切れても強行 |
| `--overwrite` | 出力フォルダの既存画像を削除してから実行 |

`--auto` は全ページを走査して「どのページの内容も切らない」余白を求め、そこから `--safety` を
差し引いた値を使います。内容が切れるページがあると終了コード 6 で中止します。

### `convert`

`--in`（必須）, `--out`（必須）, `--format`（必須）, `--name`（省略時は入力フォルダ名）

| フラグ | 意味 |
|--------|------|
| `--no-preprocess` | OCR 前処理（アップスケール・コントラスト強調）を無効化 |
| `--upscale X` | OCR 前処理の拡大倍率を上書き（例: 1.5） |
| `--no-replacements` | OCR 後の置換辞書適用を無効化 |
| `--replacements-path PATH` | 置換辞書 JSON のパスを上書き |
| `--no-bookmarks` | 章しおりの自動検出・埋め込みを無効化 |
| `--faithful` | Markdown をページ忠実型で出力（既定は NotebookLM 最適化） |
| `--no-reflow` | 段落自動整形を無効化（`--faithful` 時のみ有効） |
| `--embed-images` | ページ画像を併記（`--faithful` 時のみ有効） |
| `--no-cleanup` | Markdown の行内クリーニングを無効化 |
| `--split-words N` | 推定 N 語超で分割出力 |
| `--source TEXT` | Markdown フロントマターに出典（ASIN 等）を記録 |
| `--ocr-workers N` | ndlocr-lite の並列プロセス数（CPU 推論は 1 プロセスで全コアを使うため通常 1 が最速） |

出力形式:

| `--format` | 説明 | OCR | 主な用途 |
|------------|------|-----|---------|
| `image_pdf` | 画像をそのまま1つのPDFに結合 | 不要 | タブレットで閲覧、印刷 |
| `text_pdf` | OCR で抽出したテキストのみの軽量PDF | 必要 | GoodNotes に取り込み、テキスト検索 |
| `searchable_pdf` | 画像 + 不可視OCRテキストのPDF | 必要 | 見た目は画像PDFのまま Ctrl+F で検索可能 |
| `markdown` | OCR テキストを `.md` として出力 | 必要 | NotebookLM などの AI に読ませる |

`text_pdf` は GUI には出していません（CLI 専用）。PDF 出力時は章しおりが既定で埋め込まれます。

### `validate` / `check` / `profiles`

- **`validate`**: `--in`（必須）, `--expect-pages`, `--strict`（白紙・重複・サイズ違いの警告もエラー扱いに）
- **`check`**: `--profile` を付けると対象ウィンドウの検出まで確認する。OCR エンジンと依存パッケージ
  （cv2 / PIL / numpy / reportlab / pyautogui / customtkinter）の可否を出力
- **`profiles`**: 利用可能なプロファイルのキー・名前・ウィンドウキーワード・プロセス名・待機時間を一覧表示

### Markdown 出力（NotebookLM 最適化）

`--format markdown` は既定で **NotebookLM 最適化モード**で出力します。

- **ページをまたいで段落を結合**（見開き・改ページで文が途切れない）
- `<!-- page -->` コメントやページ区切り `---` を出さない
- 見出し階層は **H1=書名 / H2=章 / H3=節**
- **行内クリーニング**: OCR が挿入した句読点直後の余分な半角スペース等を除去
  （例「食いこませ、 気管」→「食いこませ、気管」）
- ビューアの定型注意書きページ・単独ページ番号行を除去
- 変換後に**分量の目安**（文字数・推定語数・MB）を表示し、NotebookLM の 1 ソース上限
  （50万語 / 200MB）に対する余裕を確認できる

関連フラグ:

| フラグ | 意味 |
|--------|------|
| `--faithful` | ページ忠実型（`<!-- page -->`・`---` を残す従来形式。原画像へ戻る導線が要るとき） |
| `--no-cleanup` | 行内クリーニングを無効化 |
| `--split-words N` | 推定語数が N を超えたら章（H2）境界を優先して `<名前>_1.md`, `_2.md`… に分割（目安は `450000`）。各部のフロントマターに `part: 1/3` が入り、H1 は「書名（1/3）」になる。`--faithful` 時は無効 |
| `--source TEXT` | フロントマターに出典を記録。`run` では `--asin` の値が自動で入る |

> 注: OCR の文字認識そのものの誤り（例「絞殺貝」→「絞殺具」）は機械処理では直せません。認識精度は
> 前処理・置換辞書側で対応します。

**段落自動整形**（`--faithful` 時に効く整形。NotebookLM 最適化では常に適用）:

- 行末が句点（`。．.!?！？`）や閉じ括弧で終わる行で段落を区切る
- そうでない行は次の行と結合する（日本語は無空白、英語は半角スペースを挟む）
- 英文行末のハイフン分割（`inter-` + `national`）は結合して `-` を除去
- 空行は段落区切りとしてそのまま残す
- 見出し・箇条書き・表・HTMLコメント・フロントマターは整形対象外

単体でも使えます。

```bat
python -m core.text_reflow 入力.md 出力.md
```

### 補助スクリプト

**`scripts\make_books.py`** — 蔵書一覧ダンプ + 選書定義 → batch 用 books.json

```bat
python scripts\make_books.py --library kindle-library-2026-07-29.json --select selection.json --out-dir C:\books
```

ダンプは Amazon の「コンテンツと端末の管理」から書き出した JSON
（`{"fetchedAt": ..., "count": N, "items": [...]}` 形式、または本オブジェクトの配列。各項目が `asin` と
`title` を持てば可）。選書定義の雛形は `scripts\selection.example.json`。

```json
{
  "groups": [
    { "name": "マンガ", "output": "books_a.json", "match": "^名探偵コナン",
      "sort": "volume", "take": 35, "defaults": { "format": "image_pdf" } },
    { "name": "教科書", "output": "books_c.json", "match": "SQL|pandas",
      "defaults": { "format": "searchable_pdf", "page_turn": "right" } }
  ]
}
```

- `match` はタイトルへの正規表現（部分一致）、`exclude` で除外もできる
- `sort: "volume"` はタイトル中の巻数（全角数字可）で数値ソート。`take` で先頭 N 冊に絞れる
- `defaults` はそのグループ全冊にコピーされる batch 設定
- タイトルはファイル名に使えない文字を自動除去し、`title_replace` で整形もできる
- 書き出した JSON は batch 本体と同じ検証を通してから保存される。`--dry-run` で一覧だけ確認できる

**`scripts\convert_2nd.py`** — `<書名>_trimmed` から2形式目を作る（キャプチャ不要）

```bat
python scripts\convert_2nd.py --books books_c.json --out C:\books --format markdown --log C:\books\logs\convert_2nd.jsonl
```

- `--books` は batch に渡したのと同じリスト（`asin` は `--source` としてフロントマターに記録される）
- **出力済みの本と `<書名>_trimmed` が無い本はスキップ**するので、途中で止めても同じコマンドで再開できる
- `--log` で `convert` の JSON Lines をファイルに追記。`--dry-run` で対象一覧だけ確認できる
- この工程は**画面を使わない**ので PC を占有しない

### エージェント・スクリプト向けの仕様

以下は自動化が依存する外部契約です。

- **`--json`**（全コマンド共通）: 進捗と結果を JSON Lines（1行1イベント）で出力
- **終了コード**:

  | コード | 意味 |
  |-------|------|
  | 0 | 成功 |
  | 1 | 処理中のエラー |
  | 2 | 引数・入力の不正 |
  | 3 | キャプチャ対象ウィンドウが見つからない / プロセス名不一致 |
  | 4 | OCR エンジンが利用不可 |
  | 5 | 画像が見つからない / 0ページ |
  | 6 | トリミングで内容が切れるページがある（`--force` で強行可） |
  | 7 | validate で検証エラー |

- **`manifest.json`**: `capture` 完了時に保存先へ書き出す実行記録。キー は
  `tool` / `title` / `profile_key` / `profile`（解決済みプロファイル全体）/ `total_pages` /
  `save_dir` / `stopped_reason` / `started_at` / `finished_at` / `duration_seconds`
- **分量イベント**: `--format markdown` の完了時に `markdown_stats` イベント
  （`chars` / `words_est` / `bytes`）を出力
- **誤爆防止**: プロファイルにプロセス名がある場合、タイトルは一致してもプロセスが異なるウィンドウ
  （例: タイトルに "kindle" を含むエディタ）は拒否します
- **残骸防止**: 保存先・出力先に前回の画像が残っている場合は中止します（`--overwrite` で消去して実行）
- **スリープ抑止**: キャプチャ中は画面消灯・スリープを抑止します（長時間の無人実行向け）

### CLI の注意事項

- `capture` は対象ウィンドウを前面化しマウスを占有するため、**実行中は PC の他の操作はできません**。
  並列実行もできません
- `trim` / `convert` / `validate` / `pdf` はバックグラウンド安全です（キャプチャ済み画像に対する処理）

---

## プロファイル

キャプチャ対象のビューアごとの設定（ウィンドウ名のキーワード・ページ送りキー・待機時間など）です。
`--profile <キー>` で指定します。一覧は `kindle_shot.bat profiles` でも確認できます。

### ビルトインプロファイル（6種）

| キー | ビューア | 検証 | ページ送り | 待機 | ウィンドウ名キーワード | プロセス名 |
|------|---------|------|-----------|------|----------------------|-----------|
| `kindle_cloud` | Kindle Cloud Reader（ブラウザ） | ✔ | `left` | 0.3 | `Kindle` | chrome.exe |
| `kobo_web` | 楽天Kobo（ブラウザ） | ✔ | `left` | 0.3 | `Kobo Reader` | chrome.exe |
| `google_play_web` | Google Play ブックス（ブラウザ） | ✔ | `right` | 0.3 | `Google Play ブックス` | chrome.exe |
| `dmm_web` | DMMブックス（ブラウザ） | ✔ | `left` | 0.3 | **本ごとに指定**（下記） | chrome.exe |
| `cmoa_web` | コミックシーモア（ブラウザ） | ✔ | `left` | 0.3 | `シーモア` | chrome.exe |
| `kindle` | Kindle（PCアプリ） | ✔ | `right` | 0.15 | `kindle` | Kindle.exe |

- **ビルトインはすべて実機検証済み**です。`kindle_cloud` は 2026-07 に Chrome で、ブラウザ版4種
  （`kobo_web` / `google_play_web` / `dmm_web` / `cmoa_web`）は 2026-08-16 に、`kindle` は
  2026-08-27 に実機で確認した値です
- **PC アプリ版プロファイル5種（`google_play` / `rakuten_kobo` / `bookwalker` / `dmm_books` /
  `kinoppy`）は未検証のため 2026-08-27 に削除しました。** 必要なら `core/config.json` の
  カスタムプロファイルとして自分で追加できます（下記「カスタムプロファイル」参照）。
  削除したキーが手元の `config.json` に保存値として残っている場合は、GUI のサイト一覧に
  「カスタム: <名前>」として出ます（不要なら config.json から消してください）
- ブラウザ版はいずれも **Chrome で F11 全画面**にしてから使います。クリックすると UI バーが出るため、
  前面化時にクリックしない設定（`click_position: none`）です
- 取り込み範囲はすべて `full`（ウィンドウ全体）。余白は後段のトリミングで除去します
- ページ送りキーは本によって変わります（縦書き・漫画は `left`、横書きは `right` など）。
  合わないときは `--page-turn` で上書きしてください
- honto / BookLive / ebookjapan は PC アプリが存在しない（ブラウザ閲覧のみ）ため、ビルトインには
  ありません

**`dmm_web` は本ごとにウィンドウ名のキーワードが要ります。** DMM のブラウザビューアはウィンドウ
タイトルに書名しか入らないため、既定のキーワードを持っていません。CLI から使う場合は
`core/config.json` に本の書名の一部を書いてください（GUI では「本のタイトルの一部」欄に入力します）。

```json
{ "capture": { "profiles": { "dmm_web": { "window_title_keyword": "書名の一部" } } } }
```

### Kindle Cloud Reader の注意点

- **先頭ページへの巻き戻しは Kindle の読書位置（Whispersync）を動かします**（他端末にも同期される）
- 全画面では**見開き2ページ**で表示されます（1キャプチャ = 2ページ分。NDLOCR は見開きの読み順を
  正しく処理できることを確認済み）
- 画面上部の書名ヘッダーと下部のページ番号フッターは**常時表示**のため、自動トリミング
  （`trim --auto` / `run`）がページ間の変化から UI 帯として検出して削ります。`run` の kindle_cloud
  実行時はさらに保険として `--min-margins 0,0,80,80` を既定で適用します（4K 全画面での実測値。
  辺ごとに大きい方を採用）
- 手動で使う場合: `https://read.amazon.co.jp/?asin=<ASIN>` を開く → 先頭ページに戻す →
  F11 で全画面 → `--profile kindle_cloud` でキャプチャ

### カスタムプロファイル / ビルトインの差分上書き

プロファイルは **ビルトイン → `core/config.json` の保存値 → コマンドラインの指定** の順に重ねて
解決されます（CLI・GUI 共通）。config はビルトインへの**差分上書き**として効くので、変えたい項目だけ
書けば足ります。

ビルトインの `page_wait` だけ変える例:

```json
{
  "capture": {
    "profiles": {
      "kindle": { "page_wait": 0.4 }
    }
  }
}
```

ビルトインに無いビューアを追加する例（キー名は自由。`--profile my_viewer` で指定できる）:

```json
{
  "capture": {
    "profiles": {
      "my_viewer": {
        "name": "My Viewer",
        "display_name": "自作ビューア",
        "window_title_keyword": "MyViewer",
        "process_name": "MyViewer.exe",
        "page_turn_key": "left",
        "page_wait": 0.5,
        "boundary_method": "full"
      }
    }
  }
}
```

プロファイルの全フィールド:

| フィールド | 既定 | 意味 |
|-----------|------|------|
| `name` | `""` | プロファイル名（CLI 出力・manifest 用） |
| `display_name` | `""` | GUI に出す日本語表示名（空なら `name` → キー） |
| `verified` | `false` | GUI に「動作確認済み」バッジを出すか |
| `title_keyword_is_book_title` | `false` | `true` なら `window_title_keyword` は「本のタイトルの一部」の意味（GUI が入力欄を出す） |
| `window_title_keyword` | `""` | 対象ウィンドウのタイトルに含まれる文字列（大文字小文字を区別しない） |
| `page_turn_key` | `right` | ページ送りキー（`right` / `left` / `pagedown` / `pageup` / `down` / `up`） |
| `page_wait` | `0.5` | ページ変化検出のポーリング間隔（秒） |
| `fullscreen_wait` | `5.0` | 全画面化後の待機（秒） |
| `boundary_method` | `full` | 取り込み範囲。`full`＝ウィンドウ全体 / `manual`＝手動指定の左右範囲 |
| `manual_left` / `manual_right` | `0` | `manual` 時のウィンドウ相対の左右ピクセル座標 |
| `click_position` | `center` | 前面化時のクリック位置。`center` / `top_left` / `none`（クリックしない） |
| `use_bring_to_top` | `false` | 前面化に BringWindowToTop を使う |
| `process_name` | `""` | プロセス名フィルタ（誤爆防止。空なら無効） |
| `timeout_seconds` | `5.0` | ページ変化待ちのタイムアウト（秒） |
| `max_retries` | `3` | リトライ回数 |
| `settle_enabled` | `false` | 静止待ちキャプチャ（ロード中のスピナー画面を撮らない） |
| `settle_frames` | `2` | 連続でこの回数静止したらロード完了とみなす |
| `settle_threshold` | `0.0005` | 静止と判定する変化ピクセル率（%） |
| `settle_change_threshold` | `0.1` | 前ページから変化したと判定する変化ピクセル率（%） |
| `settle_load_timeout` | `20.0` | 変化後、静止しないまま待てる上限（秒） |

※ 旧方式の取り込み範囲 `pixel_compare` / `canny_edge` は廃止済みです（設定に残っていても `full` として
扱われます）。

---

## config.json リファレンス

ユーザー設定の実体は **`core/config.json`**（初回起動時に自動生成・git 管理外）。雛形は
`config.example.json` です。書いた項目だけが既定値へ再帰的にマージされます。

| キー | 既定 | 意味 |
|------|------|------|
| `capture.active_profile` | `"kindle"` | GUI のサイト選択の初期値（GUI がキャプチャ開始時に最後に使ったサイトで更新する） |
| `capture.profiles` | `{}` | カスタムプロファイルとビルトインへの差分上書き（[プロファイル](#カスタムプロファイル--ビルトインの差分上書き)） |
| `gui.last_save_folder` | `""` | GUI が覚えている前回の保存先フォルダ（キャプチャ画像を置く作業用フォルダ。空なら `%USERPROFILE%\Documents\kindle_shot`） |
| `gui.last_output_folder` | `""` | GUI が覚えている前回の書き出し先フォルダ（PDF / Markdown の置き場。空なら未選択のまま） |
| `trim.left_margin` ほか3辺 | `0` | 現在はどの処理からも参照されません（ウィザードの余白調整は自動検出値を使い、CLI の `trim` も config を読みません） |
| `ocr.workers` | `1` | ndlocr-lite の並列プロセス数（CLI の `--ocr-workers` が上書き）。CPU 推論は 1 プロセスで全コアを使うため通常 1 が最速 |
| `ocr.preprocess.enabled` | `true` | OCR 前処理の有効化（`--no-preprocess` で無効化） |
| `ocr.preprocess.upscale` | `1.5` | 拡大倍率（`--upscale` で上書き） |
| `ocr.preprocess.enhance_contrast` | `true` | コントラスト強調 |
| `ocr.preprocess.binarize` / `binarize_threshold` | `false` / `180` | 二値化とそのしきい値 |
| `ocr.replacements.enabled` | `true` | 置換辞書の適用（`--no-replacements` で無効化） |
| `ocr.replacements.path` | `""` | 置換辞書のパス（空なら同梱の `replacements.json`。`--replacements-path` で上書き） |
| `ocr.chapter_bookmarks.enabled` | `true` | 章しおりの自動検出・埋め込み（`--no-bookmarks` で無効化） |
| `ocr.reflow_paragraphs` | `true` | 段落自動整形。**`--faithful` 時のみ効きます**（NotebookLM 最適化では常に適用） |
| `ocr.markdown.style` / `ocr.markdown.embed_images` | `"notebooklm"` / `false` | GUI の Markdown 詳細設定を廃止したため、**現在はコードから参照されていません**。Markdown の形式は CLI の `--faithful` / `--embed-images` で切り替えます |

ビルトインプロファイルの複製は `DEFAULT_CONFIG` に含めていません（正本は
`core/capture_profiles.py` のみ）。

`config.example.json` は `DEFAULT_CONFIG` から再生成できます。

```bat
python -c "import json; from core.config import DEFAULT_CONFIG; open('config.example.json','w',encoding='utf-8').write(json.dumps(DEFAULT_CONFIG, indent=2, ensure_ascii=False) + '\n')"
```

---

## replacements.json

OCR の誤認識を機械的に直す置換辞書です。リポジトリ直下の `replacements.json` を直接編集します
（`ocr.replacements.path` / `--replacements-path` で別のファイルも指定できます）。

```json
{
  "_comment": "アンダースコアで始まるキーは無視されます",
  "literal": {
    "誤": "正"
  },
  "regex": [
    { "pattern": "(?<=\\d)O(?=\\d)", "replace": "0" },
    { "pattern": "(?<=\\d)l(?=\\d)", "replace": "1" }
  ]
}
```

- `literal` は単純な文字列置換。**長いキーから順に適用**されます
- `regex` は配列の順に適用される正規表現置換
- `_` で始まるキーはコメントとして無視されます（各エントリ内の `_comment` も可）
- 本ごとの誤認識の癖をここに足していく運用を想定しています

---

## batch ファイル形式

`batch --books` に渡す JSON です。本オブジェクトの配列、または `{"books": [...]}` 形式。

```json
[
  { "asin": "B0ABCDEFG1", "title": "吾輩は猫である" },
  { "asin": "B0ABCDEFG2", "title": "坊っちゃん", "format": "markdown", "max_pages": 400 },
  { "asin": "B0ABCDEFG3", "title": "漫画X", "page_turn": "left" }
]
```

- `asin`（または `url`）は必須。`title` を省略すると ASIN を代用します
- 同じタイトルを2回書くことはできません（出力ファイル名が衝突するため検証で弾かれます）。
  2形式目は `scripts\convert_2nd.py` で作ります
- 本ごとに上書きできるキー: `format` / `max_pages` / `expect_pages` / `page_turn` / `page_wait` /
  `min_margins` / `ui_bands` / `profile` / `safety` / `ocr_workers` / `faithful` / `no_cleanup` / `split_words` /
  `max_rewind` / `load_wait` / `no_rewind`
  （`min_margins` は `[0,0,80,80]` の配列か `"0,0,80,80"` の文字列、`ui_bands` は true/false）
- CLI フラグはバッチ全体の既定で、JSON 側の指定が本ごとにそれを上書きします

---

## よくある質問

### キャプチャが途中で止まる / 最初の1ページで止まる

- 対象ビューアが**前面に表示されているか**、最小化されていないか確認してください
- 待機時間が短すぎると、ページ描画が間に合わず「変化なし」と判定されます。`--page-wait` を長くするか、
  プロファイルの `page_wait` を config で上げてください
- 画像のロードが遅いビューアでは `settle_enabled: true`（静止待ちキャプチャ）が有効です

### ウィンドウが見つからない（終了コード 3）

- 対象ビューアが起動しているか、最小化されていないか確認してください
- `kindle_shot.bat check --profile <キー>` でウィンドウ検出だけ試せます
- `window_title_keyword` が実際のウィンドウ名に含まれているか確認してください（大文字小文字は区別しません）
- `dmm_web` は本ごとにキーワードの指定が必要です（[プロファイル](#ビルトインプロファイル6種) 参照）
- プロファイルに `process_name` があると、タイトルが一致してもプロセスが違うウィンドウは拒否されます

### ページ送りキーがわからない

- ページ送りキーは本・ビューアによって変わります（縦書き・漫画は `left`、横書きは `right` など）
- GUI のキャプチャ設定画面には「自動で調べる」ボタンがあり、候補6キー（`left` → `right` →
  `pagedown` → `pageup` → `up` → `down`）で試し撮りして判定します
- CLI では `--page-turn` で指定するか、`--max-pages 3` の短いキャプチャで当たりを付けてください

### キャプチャに余計なもの（他のウィンドウ・UI）が写る

- ビューアを**全画面表示**にしてからキャプチャしてください
- 常時表示のヘッダー・フッターは自動トリミング（`--auto`）がページ間の変化から検出して削ります。
  検出が効かない場合は `trim --min-margins` で最低限削る帯を指定します
- 特定の左右範囲だけ取り込みたい場合は、`core/config.json` のプロファイルで `boundary_method` を `manual` にし、
  `manual_left` / `manual_right`（ウィンドウ相対の左右ピクセル座標）を指定します

### 「既存の画像があります」で止まる（終了コード 2）

- 前回実行の画像が残ったまま実行すると、後段の PDF に古いページが紛れ込むため意図的に止めています
- CLI: `--overwrite` を付けると削除して実行します
- GUI: キャプチャ開始時にダイアログで確認します

### トリミングの余白をどう決めればいい？

- まず `trim --auto --dry-run` で、どのページの内容も切らない値を確認してください
- そこから値を増やして余白を詰めるときは `--margins` で直接指定します（内容が切れるページがあると
  終了コード 6 で中止。`--force` で強行できます）
- Kindle Cloud Reader の書名ヘッダー・ページ番号フッターは `--auto` が UI 帯として自動検出して削ります。
  検出が効かない場合は `--min-margins 0,0,80,80` 程度で削ります（4K 全画面での実測値）
- GUI では進入時に自動検出が走り、プレビューを見ながら4辺の数値を調整できます

### OCR エンジンが利用不可（終了コード 4）

- `ndlocr-lite` フォルダが `kindle_shot/` 直下にあるか確認してください
- `kindle_shot.bat check` で状態を確認できます。導入手順は [OCR エンジン](#ocr-エンジンndlocr-lite) を参照
- 画像PDF（`--format image_pdf`）は OCR 不要で動きます

### NotebookLM に入れるファイルはどう作ればいい？

- `--format markdown` で既定の NotebookLM 最適化スタイルになります
- 完了時の `markdown_stats`（文字数・推定語数・MB）で 1 ソース上限（50万語 / 200MB）に収まっているか
  確認してください。超えるときは `--split-words 450000` で分割します

---

## ファイル構成

```
kindle_shot/
├── app.py                  # GUI エントリポイント（ウィザード）
├── cli.py                  # CLI エントリポイント（無人運用・エージェント向け）
├── core/                   # UI 非依存のコアロジック
│   ├── pipeline.py         # trim/convert/validate/run/batch のオーケストレーション
│   ├── capture_runner.py   # キャプチャ実行手順（ウィンドウ検出→engine→manifest）
│   ├── reader_navigator.py # Kindle Cloud Reader の open（全画面化・巻き戻し）
│   ├── capture_engine.py   # キャプチャエンジン（ページ変化検出・静止待ち・保存）
│   ├── capture_profiles.py # プロファイル定義（ビルトイン6種 + カスタム）
│   ├── page_turn_probe.py  # ページ送りキーの自動判定
│   ├── boundary_detector.py# 余白検出と取り込み範囲（full/manual）
│   ├── validator.py        # キャプチャ結果の機械検証
│   ├── pdf_extractor.py    # 外部PDFを画像に展開（pypdfium2 ベース）
│   ├── trimmer.py          # 画像トリミング処理
│   ├── pdf_builder.py      # PDF生成（画像PDF・テキストPDF・検索可能PDF・しおり）
│   ├── ocr_engine.py       # OCR 処理（NDLOCR-Lite）
│   ├── ocr_preprocess.py   # OCR 前処理（アップスケール・コントラスト強調）
│   ├── chapter_detector.py # 章見出しの自動検出
│   ├── markdown_writer.py  # Markdown 出力（NotebookLM 最適化 / ページ忠実）
│   ├── text_reflow.py      # 段落自動整形
│   ├── text_cleanup.py     # 行内クリーニング
│   ├── text_replacements.py# 置換辞書（replacements.json）
│   ├── text_stats.py       # 分量見積り
│   ├── text_patterns.py    # テキスト処理共通の文字クラス・正規表現
│   ├── image_files.py      # 画像拡張子定義と列挙
│   ├── platform_utils.py   # OS 依存処理の窓口（Windows / macOS を切り替え）
│   ├── win32_utils.py      # Win32 API（ウィンドウ操作・スリープ抑止）
│   ├── macos_utils.py      # macOS 版（Quartz / AppKit / Accessibility・mss・caffeinate）
│   ├── dpi.py              # DPI 認識の初期化（GUI/CLI 共用）
│   └── config.py           # 設定管理（core/config.json の読み書き）
├── ui/                     # GUI（customtkinter・ウィザード）
│   ├── main_window.py      # ヘッダー/ボディ/フッターの3層・ステップ遷移
│   ├── wizard.py           # ステップ間の状態とステップ基底
│   ├── steps/              # 各ステップ画面（ホーム/キャプチャ/PDF読込/余白/書き出し/完了）
│   ├── profile_choices.py  # サイト選択リスト
│   ├── theme.py            # フォント・余白・色の定数
│   ├── tab_utils.py        # ログ・フォルダ選択・進捗・GuiEmitter
│   └── widgets.py          # 共通UIパーツ
├── scripts/                # 補助スクリプト
│   ├── make_books.py       # 蔵書ダンプ + 選書定義 → batch 用 books.json
│   ├── convert_2nd.py      # _trimmed から2形式目を作る
│   └── selection.example.json
├── tests/                  # pytest（純ロジック + CLI JSON 契約）
├── config.example.json     # 設定の雛形（DEFAULT_CONFIG から機械生成）
├── replacements.json       # OCR テキストの置換ルール
├── requirements.txt
├── setup.bat / run.bat / kindle_shot.bat   # 環境構築 / GUI 起動 / CLI ランチャー（Windows）
├── setup.sh / run.sh / kindle_shot.sh      # 同（macOS。setup.command / run.command は Finder 用）
├── kindle_env/             # 仮想環境（setup.bat で自動生成）
└── ndlocr-lite/            # OCR エンジン（setup.bat で自動取得）
```

---

## 注意事項

- キャプチャ中はマウスやキーボードの操作を避けてください。pyautogui がキー入力でページをめくっている
  ため、操作が干渉します
- キャプチャ対象は**全画面表示**にしておくと、余白が少なくきれいに撮れます
- 数百ページをキャプチャする場合は保存先のディスク容量に注意してください（1ページあたり数百KB〜数MB）
- このツールは個人の学習目的での使用を想定しています

## ライセンス

kindle_shot 本体は MIT ライセンスです（同梱の `LICENSE` を参照）。変換する電子書籍・PDF の著作権は
別の話で、私的利用の範囲にとどめてください。OCR エンジンの NDLOCR-Lite は国立国会図書館の
配布条件に従います。

## 開発メモ

- テスト: `kindle_env\Scripts\python.exe -m pytest`（純ロジックと CLI の JSON 契約。Win32 実行系・
  OCR 実行系は対象外）
- lint: `kindle_env\Scripts\python.exe -m ruff check .`
- 依存の変更: `pyproject.toml` を編集 → `uv pip compile pyproject.toml --universal --python-version 3.11 -o requirements.txt`
  （`--universal` で Windows / macOS 両方のロックになる。macOS 専用の pyobjc・mss は環境マーカー付き）
