# TimelineForVideo

手元にある動画ファイルを、ChatGPT などの LLM に渡しやすいタイムライン資料へ変換するローカルツールです。

[English README](README.md) | [サンプルタイムライン](docs/examples/sample-timeline.ja.md) | [第三者ライセンス](THIRD_PARTY_NOTICES.md) | [モデルと実行環境メモ](MODEL_AND_RUNTIME_NOTES.md) | [セキュリティと安全性](docs/SECURITY_AND_SAFETY.md) | [公開前チェック](docs/PUBLIC_RELEASE_CHECKLIST.md) | [ライセンス](LICENSE)

## Public Release Status

現在の public release 系列は `TimelineForVideo v0.4.0 Tech Preview` です。

現時点の public contract:

- baseline support: Windows + Docker Desktop + CPU mode
- macOS: source-based experimental path
- GPU mode: optional, NVIDIA-only, best-effort
- 話者分離は optional で、`pyannote/speaker-diarization-community-1` の gated approval と Hugging Face token が必要
- これは local-first の CLI tool であり、hosted SaaS ではありません

## このアプリがやっていること

このアプリは、手元にある動画ファイルを、LLM に渡しやすいタイムライン資料と ZIP に変換するためのものです。

内部では、主に次のことを行います。

1. 動画の音声を読み取って文字にします
2. 画面に映っている文字や内容を拾います
3. 会話と画面の変化を時系列のタイムラインとして整理します
4. 最終結果を ZIP にまとめます

使う側がモデル名や細かい内部処理を理解する必要はありません。

## どんな用途に向いているか

- 会議の振り返り
- 会話ログの分析
- 家族や友人との会話の整理
- 画面録画の振り返り
- 古い動画資産のテキスト化

## 基本的な流れ

1. `data/input` に動画ファイルを置く
2. CLI コマンドで実行する
3. 完了まで待つ  
   高度な AI 処理を行うため、ある程度時間がかかります
4. `jobs archive` で ZIP を作る
5. 必要なら、その ZIP を ChatGPT や Claude などの LLM に渡して活用する

たとえば、次のような使い方ができます。

- 会議内容を要約する
- 決定事項や宿題を抜き出す
- 自分の説明の癖を振り返る
- 会話パターンを分析する
- 動画の蓄積を検索しやすいメモにする

## ZIP に入るもの

作成される ZIP は、できるだけコンパクトにしています。

主に入るのは次の 3 つです。

- `README.md`
- `TRANSCRIPTION_INFO.md`
- `timelines/<撮影日時>.md`
- 一部失敗や warning がある場合は `FAILURE_REPORT.md`
- 一部失敗や warning がある場合は `logs/worker.log`

例:

```text
TimelineForVideo-export.zip
  README.md
  TRANSCRIPTION_INFO.md
  timelines/
    2026-03-26 18-00-00.md
    2026-03-25 09-14-12.md
```

`timelines/` の中の Markdown が、動画ごとの最終成果物です。

ジョブが一部失敗でも一部成功していれば、ZIP は作成できます。その場合は成功した timeline に加えて、失敗内容の要約と worker log も同梱されます。

## 再利用と再実行

以前に処理したことがあるファイルを処理すると、CLI は再利用できる既存結果があるかを先に確認します。

- 再利用可能な timeline が残っている場合は、既定では既存結果を再利用します
- 意図的に再処理したい場合は `--reprocess-duplicates` を使います
- 計算モード、処理精度、話者分離まわりを変えたい場合は、先に `settings save` で設定を変えてから実行します

## 内部作業フォルダと ZIP の違い

Docker 内では、処理のためにもう少し大きな作業フォルダを持っています。

そこには、たとえば次のようなものが入ります。

- request / status の JSON
- worker ログ
- 中間の文字起こしファイル
- 画面差分メモ
- 一時ファイル

これらはアプリ内部で使うものです。普段ユーザーが見るのは、作成した ZIP の中身だけで十分です。

## クイックスタート

Windows:

```powershell
.\start.bat
```

Docker ベースの CLI 実行環境を準備し、固定フォルダを作成します。

macOS:

```bash
./start.command
```

こちらは `v0.4.0` では experimental な source-based path です。Docker ベースの CLI 実行環境を準備します。

その後、動画をここに置きます。

```text
data/input/
```

ジョブを作って実行します。

```powershell
docker compose run --rm worker jobs create --directory /data/input
```

ジョブ一覧を確認します。

```powershell
docker compose run --rm worker jobs list
```

ZIP を作成します。

```powershell
docker compose run --rm worker jobs archive --job-id job-YYYYMMDD-HHMMSS-xxxxxxxx
```

結果は `data/output` に出力されます。

## 必要なもの

- primary supported path としての Windows
- experimental な source-based path としての macOS
- Docker Desktop
- 初回のコンテナ・モデル取得用のインターネット接続
- `pyannote` 話者分離を使う場合のみ Hugging Face token
- `pyannote` 話者分離を使う場合のみ gated approval
- GPU モードを使う場合は NVIDIA GPU と Docker GPU 対応

## 計算モード

public release の baseline は CPU mode です。

- `CPU`
  - 幅広い環境で使える
  - 速度は遅め
- `GPU`
  - Docker から使える NVIDIA GPU が必要
  - 主な AI 処理が高速になる
  - `v0.4.0` では best-effort 扱い

処理精度:

- `Standard`
  - `WhisperX medium`
- `High`
  - `WhisperX large-v3`
  - GPU モードかつ十分な VRAM がある場合のみ使用可能

この開発環境では `NVIDIA GeForce RTX 4070` で GPU 実行を確認しています。

## 対応する入力形式

主な対応形式:

- `.mp4`
- `.mov`
- `.m4v`
- `.avi`
- `.mkv`
- `.webm`

実際に読み込めるかどうかは、ランタイムイメージ内の `ffmpeg` に依存します。

## CLI

通常利用の入口は CLI です。

主なコマンド:

- `settings status`
- `settings save`
- `jobs create`
- `jobs list`
- `jobs show`
- `jobs run`
- `jobs archive`

例:

```powershell
docker compose run --rm worker settings status
docker compose run --rm worker settings save --token hf_xxx --terms-confirmed
docker compose run --rm worker settings save --compute-mode cpu --processing-quality standard
docker compose run --rm worker jobs create --file /data/input/clip.mp4
docker compose run --rm worker jobs create --directory /data/input
docker compose run --rm worker jobs list
docker compose run --rm worker jobs archive --job-id job-YYYYMMDD-HHMMSS-xxxxxxxx
```

`jobs archive` を使うと、LLM に渡しやすい ZIP 形式で出力できます。

## テスト

現在のテストは軽めです。

- Python worker の unit test
- 実データでの手動 smoke test

worker unit test:

```powershell
$env:PYTHONPATH=".\worker\src"
python -m unittest discover .\worker\tests
```

commit 前に lint を有効にする場合:

```powershell
git config core.hooksPath .githooks
```

## ライセンス

このリポジトリは MIT License です。詳細は [LICENSE](LICENSE) を参照してください。
