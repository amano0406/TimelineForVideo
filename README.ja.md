# video2timeline

ChatGPT などの LLM に渡しやすい形で、ローカル動画をタイムライン化するツールです。

[English README](README.md) | [サンプルタイムライン](docs/examples/sample-timeline.ja.md) | [第三者ライセンス一覧](THIRD_PARTY_NOTICES.md) | [モデル・ランタイム注意事項](MODEL_AND_RUNTIME_NOTES.md) | [ライセンス](LICENSE)

`video2timeline` は、ローカルにある動画ファイルを次のような用途向けに整理されたタイムライン資料へ変換します。

- 会議内容の振り返り
- 会話ログの分析
- 自分のコミュニケーション傾向の見直し
- ZIP にまとめて ChatGPT に渡し、要約・分析・比較に使う

## スクリーンショット

### ダッシュボード

![Dashboard](docs/screenshots/dashboard.png)

### 設定

![Settings](docs/screenshots/settings.png)

### 実行詳細

![Run Details](docs/screenshots/run-details.png)

## 何が出力されるか

1 回の run で主に次の成果物が出ます。

- 動画ごとの `timeline.md`
- 生の文字起こし (`raw.json`, `raw.md`)
- 画面メモと画面差分
- 無音カットと元動画時刻の対応を残す `cut_map.json`
- LLM に渡しやすい `batch-*.md` と `timeline_index.jsonl`

想定フローは次のとおりです。

1. ローカルで実行する
2. 生成されたタイムライン資料を確認する
3. 完了した run を ZIP でダウンロードする
4. その ZIP を ChatGPT にアップロードして分析に使う

## サンプルタイムライン

以下のサンプルは、実際に生成されたタイムラインをもとに、氏名や具体的な内容を伏せ字化した公開用サンプルです。

全文: [docs/examples/sample-timeline.ja.md](docs/examples/sample-timeline.ja.md)

```md
# Video Timeline

- Source: `/shared/inputs/example/customer-followup-call.mp4`
- Media ID: `2026-03-09-12-15-56-example`
- Duration: `70.417s`

## 00:00:11.179 - 00:00:57.194
Speech:
SPEAKER_00: [PERSON_A] です。[ITEM_GROUP_A] の返送依頼について確認したくご連絡しました。梱包内に含まれているはずの対象物が見当たらなかった理由を確認したいです。

Screen:
OCR detected text. Top lines: 付け加えてください / 聞き取れませんでした。 / OBS 32.0.4 - プロファイル: 無題

Screen change:
Initial frame.

## 00:00:57.174 - 00:01:03.400
Speech:
SPEAKER_00: 承知しました。申し訳ありません。

Screen:
大きな画面変化はありません。

Screen change:
省略
```

## 主な挙動

- ローカル完結が基本です。通常経路ではクラウド文字起こしを前提にしません。
- 現状は CPU 前提です。GPU エンジンは今後公開予定です。
- 無音カットは内部最適化であり、最終タイムラインは元動画時刻を基準にします。
- OCR と画面説明は、意味のある画面変化があったときだけ厚く出します。
- 話者分離は Hugging Face token と gated model 承認が揃っている場合のみ有効です。
- GUI は保守的な設計で、同時に 1 ジョブだけ動かす前提です。

## 必要環境

- Windows または macOS
- Docker Desktop
- 初回起動時のイメージ・モデル取得用インターネット接続
- 必要に応じて Hugging Face token
- `pyannote` を使う場合は gated model の利用条件確認

## クイックスタート

Windows:

```powershell
C:\apps\video2timeline\start.bat
```

macOS:

```bash
/Users/.../video2timeline/start.command
```

起動後は次の順番です。

1. `http://localhost:8090` を開く
2. `Settings` で Hugging Face token を保存する
3. 必要ならモデル承認ページを開いて承認する
4. ファイルまたはディレクトリを選ぶ
5. ジョブを開始する
6. 完了したら ZIP をダウンロードする

停止:

```powershell
C:\apps\video2timeline\stop.bat
```

## 対応入力形式

主対応:

- `.mp4`
- `.mov`
- `.m4v`
- `.avi`
- `.mkv`
- `.webm`

実際のデコード可否はランタイム内の `ffmpeg` ビルドに依存します。

## 多言語対応

ヘッダーから UI 言語を切り替えられます。

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

可能な場合はブラウザ言語を既定値に使い、手動選択は cookie に保存します。地域別のマッピングは [web/Resources/Locales/languages.json](web/Resources/Locales/languages.json) に定義しています。

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

## ライセンス

このリポジトリ自体は MIT License です。詳細は [LICENSE](LICENSE) を参照してください。

第三者コード・ランタイム関連:

- [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)
- [MODEL_AND_RUNTIME_NOTES.md](MODEL_AND_RUNTIME_NOTES.md)

## ステータス

`video2timeline` v1 は CPU 前提のローカル処理版として公開可能な状態です。GPU エンジンはまだ公開版には含めておらず、今後追加予定です。
