from __future__ import annotations

import json
from pathlib import Path
import sys
from typing import Any

from .api_server import run_refresh_job


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 2:
        print("usage: python -m timeline_for_video_worker.job_runner <job_id> <options_json>", file=sys.stderr)
        return 2

    job_id = args[0]
    options_path = Path(args[1])
    options: dict[str, Any] = {}
    if options_path.exists():
        loaded = json.loads(options_path.read_text(encoding="utf-8"))
        if isinstance(loaded, dict):
            options = loaded

    run_refresh_job(job_id, options)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
