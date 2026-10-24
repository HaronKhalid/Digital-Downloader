# Development

## Commands

```powershell
python -m pytest                       # all tests (offline, ~3 s)
python e2e/server.py & python e2e/run.py   # optional browser checks (see e2e/README.md)
python -m pytest backend/tests/test_urls.py -q
uvicorn backend.app.main:app --host 127.0.0.1 --port 8000 --reload
```

Always run from the repository root; imports are `backend.app...`.

## Conventions

- Security-relevant code (`utils/urls.py`, `utils/filenames.py`, `services/file_service.py`, `core/security.py`) changes only together with tests. Never loosen a check to make something work.
- Subprocesses: argument lists only, with timeout, captured output and `controlled_env()`. No shell.
- Frontend: assign text with `textContent`; no inline scripts or styles (CSP).
- Raise `AppError` subclasses with user-readable messages; put technical detail in `reason` (logged, never shown).
- New dependency? Add it to `backend/requirements.txt` pinned, and justify it in `architecture.md`.
- Tests that need DNS must inject a resolver or monkeypatch `socket.getaddrinfo`; the suite must pass offline.

## Session checklist

Read → understand → plan → implement → test → review → document.
