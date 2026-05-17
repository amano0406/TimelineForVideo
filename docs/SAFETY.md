# Safety

TimelineForVideo v1 treats source videos as read-only inputs.

## Source Video Rules

- Do not modify source videos.
- Do not delete source videos.
- Do not copy source videos into item outputs.
- Do not include source videos in ZIP exports.

## Generated Output Rules

Generated artifacts are written only under `outputRoot`.

`POST /items/remove` targets known generated files:

- item JSON records
- ffprobe, frame sample, frame OCR, and audio analysis raw outputs
- contact sheets
- generated frame sample JPGs
- generated frame OCR overlay JPGs
- generated MP3 audio derivatives
- generated download ZIPs
- generated latest manifest files

It prunes empty generated directories after deleting files. It does not remove
arbitrary files from `outputRoot`.

## Processing Boundaries

The v1 rebuild includes local OCR over generated frame images and source-safe
audio derivative analysis. The generated MP3 derivative is a local artifact under
`outputRoot`; it is removed by `POST /items/remove`, but it is not included in export
ZIPs.

The v1 rebuild intentionally excludes:

- scene detection
- face recognition
- person recognition
- external APIs
