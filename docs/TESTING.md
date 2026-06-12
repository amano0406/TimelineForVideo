# Testing

Run from WSL or the local development shell:

```bash
python -m pytest worker/tests
python -m compileall -q worker/src worker/tests scripts
git diff --check
docker compose config
docker compose -f docker-compose.yml -f docker-compose.gpu.yml config
docker compose -f docker-compose.yml -f docker-compose.gpu.yml up -d --build --no-deps worker
curl.exe http://127.0.0.1:19500/health
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:19500/models/list -Body '{}' -ContentType 'application/json'
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:19500/items/refresh -Body '{"maxItems":1,"samplesPerVideo":3,"frameDiffVlmMode":"auto"}' -ContentType 'application/json'
```

Run the Python checks sequentially. The API job tests start a short-lived
refresh subprocess, so running `pytest` at the same time as `compileall` or
other tools that touch Python cache files can make the status-job test flaky.

The test suite covers:

- settings validation
- discovery
- ffprobe parsing with fixture JSON
- bounded sampling
- local frame OCR output shape
- frame visual feature output shape
- adjacent-frame visual gate output shape
- local frame-difference VLM output shape and skip/failure behavior
- audio derivative and speech candidate output shape
- model inventory output shape
- audio model `auto` and `required` mode behavior
- item record shapes
- ZIP source video exclusion
- ZIP MP3 derivative exclusion
- remove source-safety behavior
- worker API action and worker API JSON behavior
- CPU and GPU compose configuration

For full smoke validation, create a short generated sample video with audio, run
refresh, list items, download, dry-run remove, and actual remove. Confirm
the source video still exists after remove and the ZIP contains no source video
or generated MP3 audio derivative.

For live pyannote/faster-whisper validation, provide a Hugging Face token through the
environment and run the audio analysis path with `audioModelMode: "required"` on a short
generated speech video. Do not store the token in committed files.

For live Qwen validation, use the GPU worker image and run
`POST /items/refresh` with `frameDiffVlmMode: "required"` on one item. Confirm
`raw_outputs/frame_diff_vlm.json` exists, `timeline.json` contains
`frame_diff_vlm` visual events when candidates were analyzed, and no external
analysis API is called.
