# video2timeline

手元にある動画ファイルを、ChatGPT などの LLM で扱いやすいタイムライン資料に変換するローカル実行アプリです。

[English README](README.md) | [サンプルタイムライン](docs/examples/sample-timeline.ja.md) | [第三者ライセンス一覧](THIRD_PARTY_NOTICES.md) | [モデル・ランタイム情報](MODEL_AND_RUNTIME_NOTES.md) | [安全性メモ](docs/SECURITY_AND_SAFETY.md) | [公開前チェックリスト](docs/PUBLIC_RELEASE_CHECKLIST.md) | [ライセンス](LICENSE)

`video2timeline` は、手元にある動画ファイルを LLM 向けの構造化タイムライン資料に変換します。

このプロジェクトの主目的は、既存の動画資産を LLM で効率よく活用できる状態にすることです。具体的には、ローカルの動画ファイルを構造化されたテキスト中心の資料に変換し、確認しやすくし、ZIP 化して ChatGPT などの LLM に渡しやすくすることを目指しています。

主なユースケース:

- 会議内容の振り返り
- 会話ログの分析
- 自分のコミュニケーション傾向の見直し
- ChatGPT 向けの ZIP パッケージ作成

## スクリーンショット

### Settings

![Settings](docs/screenshots/settings.png)

### New Job

![New Job](docs/screenshots/new-job.png)

### Jobs

![Jobs](docs/screenshots/jobs.png)

### Run Details

![Run Details](docs/screenshots/run-details.png)

## 生成されるもの

1 回の run ごとに、主に次の成果物を生成します。

- 動画ごとの `timeline.md`
- 生の文字起こし結果 (`raw.json`, `raw.md`)
- 画面メモと画面差分
- 無音カット時の元タイムライン対応を残す `cut_map.json`
- LLM 投入用の `batch-*.md` と `timeline_index.jsonl`

基本的な流れ:

1. ローカルで実行する
2. 生成されたタイムライン資料を確認する
3. 完了した run を ZIP でダウンロードする
4. その ZIP を ChatGPT などに渡して分析する

## サンプルタイムライン

以下のサンプルは、実際に生成したタイムラインを元に、名前や機微情報を伏せて公開用に整えたものです。

全文: [docs/examples/sample-timeline.ja.md](docs/examples/sample-timeline.ja.md)

```md
# Video Timeline

- Source: `/shared/inputs/example/customer-followup-call.mp4`
- Media ID: `2026-03-09-12-15-56-example`
- Duration: `70.417s`

## 00:00:11.179 - 00:00:57.194
Speech:
SPEAKER_00: こんにちは、[PERSON_A]です。[ITEM_GROUP_A] の返品依頼について確認のため連絡しました。梱包物の中に必要な資料が入っていなかった理由を確認したいです。

Screen:
OCR detected text. Top lines: Please add more detail / Speech recognition did not catch that / OBS 32.0.4 - Profile: Untitled

Screen change:
初期フレーム。

## 00:00:57.174 - 00:01:03.400
Speech:
SPEAKER_00: 承知しました。失礼しました。

Screen:
大きな画面変化はありません。

Screen change:
省略。
```

## 主な挙動

- ローカル実行が基本です。通常フローでクラウド文字起こしは不要です。
- CPU / GPU の両モードがあります。worker が NVIDIA GPU を使える環境なら GPU の方が高速です。
- 無音カットは内部最適化として使いますが、最終タイムラインは元動画時刻に合わせます。
- OCR と画像メモは、画面変化が十分に意味を持つときだけ出力します。
- 話者分離は、必要な Hugging Face token と gated model 承認が揃っているときだけ実行します。
- GUI は保守寄りの設計で、同時に 1 ジョブだけ動かす前提です。

## インターフェース

- 通常利用の主入口は GUI です。
- 上級者向けに worker 側 CLI もあります。
- GUI と CLI は同じ run ディレクトリ形式 (`request.json`, `status.json`, `result.json`, `timeline.md`, `batch-*.md`) を生成します。

## 必要環境

- Windows または macOS
- Docker Desktop
- 初回のイメージ / モデル取得用のインターネット接続
- `pyannote` 話者分離を使う場合は Hugging Face token
- `pyannote` 用 gated model の利用承認
- GPU モードを使う場合は NVIDIA GPU と Docker GPU 対応

## クイックスタート

Windows:

```powershell
.\start.bat
```

macOS:

```bash
./start.command
```

その後の流れ:

1. `start.bat` / `start.command` が `.env` を自動生成します
2. `.env` で入力パスと出力パスを設定します
3. `http://localhost:38090` を開きます
4. 最初に `Settings` を完了します
5. `Settings` で `CPU` または `GPU` モードを選びます
6. 話者分離を使うなら Hugging Face token を保存します
7. 必要な model approval を済ませます
8. ファイルをアップロードするか、ディレクトリを選びます
9. ジョブを開始します
10. 完了した ZIP をダウンロードします

start スクリプトでは次も確認します。

- Docker Desktop が入っているか
- Docker engine が実際に起動しているか
- `.env` にプレースホルダのままのパスが残っていないか
- `web` と `worker` が両方起動したか
- ローカル Web UI が応答してからブラウザを開く
- NVIDIA GPU が見つかった場合は GPU 用 compose override を使う

停止:

```powershell
.\stop.bat
```

## 対応入力形式

主な対応形式:

- `.mp4`
- `.mov`
- `.m4v`
- `.avi`
- `.mkv`
- `.webm`

実際のデコード可否は、ランタイムイメージ内の `ffmpeg` ビルドに依存します。

## 多言語対応

UI にはサイドバーから切り替えられる言語セレクタがあります。

現在の対応ロケール:

- `ja`
- `en`
- `zh-CN`
- `zh-TW`
- `ko`
- `es`
- `fr`
- `de`
- `pt`

可能な場合はブラウザ言語を既定値に使い、手動選択は cookie に保存します。対応エイリアスや地域別の寄せ先は [web/Resources/Locales/languages.json](web/Resources/Locales/languages.json) で定義しています。

## CLI

worker 側には、直接ローカル実行や自動化に使える CLI があります。

主なコマンド:

- `settings status`
- `settings save`
- `jobs create`
- `jobs list`
- `jobs show`
- `jobs run`
- `scan`
- `compare-images`
- `run-job`
- `daemon`

例:

```powershell
$env:PYTHONPATH=".\worker\src"
python -m video2timeline_worker settings status
python -m video2timeline_worker settings save --token hf_xxx --terms-confirmed
python -m video2timeline_worker jobs create --file C:\path\to\clip.mp4
python -m video2timeline_worker jobs create --directory C:\path\to\folder
python -m video2timeline_worker jobs list
```

公開向けの主入口は GUI ですが、CLI でも同じ run 契約でジョブを作成・実行できます。スクリプト実行、デバッグ、上級者向け運用を想定しています。

## 出力構成

```text
run-YYYYMMDD-HHMMSS-xxxx/
  request.json
  status.json
  result.json
  manifest.json
  RUN_INFO.md
  TRANSCRIPTION_INFO.md
  NOTICE.md
  logs/
    worker.log
  media/
    <media-id>/
      source.json
      audio/
        extracted.mp3
        trimmed.mp3
        cut_map.json
      transcript/
        raw.json
        raw.md
      screen/
        screenshot_01.jpg
        screenshots.jsonl
        screen_diff.jsonl
      timeline/
        timeline.md
  llm/
    timeline_index.jsonl
    batch-001.md
```

## テスト

現在のテストは、実用上の確認を重視しています。

- Python worker の unit test
- ASP.NET Core UI の Playwright E2E smoke test
- 実データによる軽量 smoke run

worker unit test:

```powershell
$env:PYTHONPATH=".\worker\src"
python -m unittest discover .\worker\tests
```

ブラウザ E2E:

```powershell
.\scripts\test-e2e.ps1
```

commit 時に lint を自動実行したい場合:

```powershell
git config core.hooksPath .githooks
```

現在の Playwright smoke では、次を確認しています。

- ルートから設定フローへ移動できること
- Settings ページの表示
- Jobs 一覧の表示
- 実行中ジョブ詳細の表示
- 完了済みジョブの ZIP ダウンロード

## ライセンス

このリポジトリは MIT License です。詳細は [LICENSE](LICENSE) を参照してください。

第三者コード / ランタイム関連:

- [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)
- [MODEL_AND_RUNTIME_NOTES.md](MODEL_AND_RUNTIME_NOTES.md)

## ステータス

`video2timeline` v1 はローカル利用向けに調整中です。この公開時点では `NVIDIA GeForce RTX 4070`、driver `560.94`、Docker GPU 対応ありの環境で GPU 実行確認済みです。
