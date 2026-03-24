# 公開用サンプルタイムライン

このサンプルは、実際に生成されたタイムラインをもとに、氏名・組織名・具体的な内容を伏せ字化した公開用サンプルです。

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

補足:

- `Speech:` には時間帯ごとの文字起こしをまとめています。
- `Screen:` では OCR と画像説明を要約して載せます。
- `Screen change:` では前フレームとの差分が大きいかどうかを示します。
- タイムスタンプは元動画の時刻を保持します。
