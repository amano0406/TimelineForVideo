# Testing

Run from WSL or the local development shell:

```bash
PYTHONPATH=worker/src python3 -m unittest discover -s worker/tests -v
python3 -m compileall -q worker/src worker/tests
git diff --check
docker compose config
docker compose -f docker-compose.yml -f docker-compose.gpu.yml config
docker compose -f docker-compose.yml -f docker-compose.gpu.yml up -d --build --no-deps worker
docker compose -f docker-compose.yml -f docker-compose.gpu.yml exec -T worker python -m timeline_for_video_worker health --json
docker compose -f docker-compose.yml -f docker-compose.gpu.yml exec -T worker python -m timeline_for_video_worker models list --json
```

The test suite covers:

- settings validation
- discovery
- ffprobe parsing with fixture JSON
- bounded sampling
- local frame OCR output shape
- frame visual feature output shape
- audio derivative and speech candidate output shape
- model inventory output shape
- audio model `auto` and `required` mode behavior
- item record shapes
- ZIP source video exclusion
- ZIP MP3 derivative exclusion
- remove source-safety behavior
- worker command JSON behavior
- CPU and GPU compose configuration

For full smoke validation, create a short generated sample video with audio, run
`process all`, list items, download, dry-run remove, and actual remove. Confirm
the source video still exists after remove and the ZIP contains no source video
or generated MP3 audio derivative.

For live pyannote/faster-whisper validation, provide a Hugging Face token through the
environment and run `audio analyze --audio-model-mode required` on a short
generated speech video. Do not store the token in committed files.
