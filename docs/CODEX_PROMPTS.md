# Codex App Prompts

Use these in a new Windows Codex app thread with the project folder set to:

```text
C:\apps\TimelineForVideo
```

## Prompt 1

```text
日本語で回答してください。

C:\apps\TimelineForVideo は、既存実装を削除済みの空リポジトリです。以前のTimelineForVideo実装は完全に無視し、復元しないでください。

まず以下を読んでください。

1. AGENTS.md
2. docs/CODEX_HANDOFF.md
3. docs/DECISIONS.md
4. docs/OUTPUT_CONTRACT.md
5. docs/ACCEPTANCE_CRITERIA.md
6. docs/IMPLEMENTATION_MILESTONES.md

参照元として C:\apps\TimelineForAudio と C:\apps\TimelineForImage を必要最小限だけ読んでください。参照専用です。編集、import、コードコピーは禁止です。

ChatGPT設計スレッドはDockForChatGPTで取得済みです。必要なら次のsnapshotを読んでください。
C:\Codex\workspaces\dockforchatgpt\chat_conversations\snapshots\20260506-114835-69f96218-7de4-83a9-b46b-d660584e0639-a7f37b4b-62b8-443c-905d-c71a0e9c6d78.json

このターンではコード変更しないでください。

やること:
- 現在の空repo状態を確認する
- handoff docsを読み、v1 rebuild計画を整理する
- reference productsから読むべき最小ファイルを列挙する
- Milestone 1からMilestone 7までの実装順序を確認する
- 次ターンで実装すべきMilestone 1の変更予定ファイルを列挙する

制約:
- 旧TimelineForVideoを復元しない
- source videoを変更、削除、ZIP同梱しない
- TimelineForAudio/Imageは処理契約の参照元。import、共有ライブラリ化、旧Video復元は禁止
- frame OCRとaudio evidenceはVideo内で独立実装する
- v1ではscene detection、人物認識、顔認識、外部APIを実装しない
- 古い互換性のためだけのパラメータやlegacy shimは作らない
```

## Prompt 2

```text
前回の計画を前提に、Milestone 1を実装してください。

対象:
- Python package scaffold
- Dockerfile
- docker-compose
- Windows launcher
- settings file
- health
- POST /settings/init, POST /settings/status, POST /settings/save
- 最小README更新

必ず守ること:
- 旧TimelineForVideoを復元しない
- TimelineForAudio/Imageのコードをimportしない
- source videoを変更しない
- 小さく理解可能な差分にする
- 実行できるテストを実行して結果を報告する
```
