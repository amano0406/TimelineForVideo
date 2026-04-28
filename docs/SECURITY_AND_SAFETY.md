# Security And Safety Notes

`TimelineForVideo` is a local-first CLI tool packaged through Docker. It is not a multi-tenant hosted service and it does not attempt to sandbox the host machine.

That changes what matters most for safety.

## Main Safety Boundary

The primary concern is not remote attack surface. The primary concern is whether the app reads or deletes files outside the directories it is supposed to manage.

Current guardrails:

- input videos are read from the fixed input root
- generated jobs and ZIP packages are written under the fixed output root
- cleanup scripts do not delete original input videos
- Hugging Face tokens are stored under `data/app-data`, which is ignored by git

## What This App Does Not Claim

- no OS-level sandbox
- no hardened secret manager
- no guarantee against misuse if the user intentionally points the app at sensitive paths

This is acceptable for a personal local tool, but it should be stated clearly.

## Practical Risk Level For A Public Repo

For a public code repository, the risk is mostly about:

- accidentally committing private data
- shipping unsafe default paths
- deleting the wrong directories
- unclear behavior around token storage

Those are easier to manage than the risks of a hosted service.

## Recommended Ongoing Checks

- keep sample configs generic
- keep `.env`, `data/`, and run output ignored
- review delete paths whenever cleanup logic changes
- keep CLI smoke coverage on settings, job creation, and ZIP archive creation
- avoid adding broad recursive delete behavior without explicit root checks
