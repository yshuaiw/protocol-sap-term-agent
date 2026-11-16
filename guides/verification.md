# Verification workflow

Keep the existing protections; test count is not a quality target. During iteration run affected checks, then run the full offline suite once on the final delivery candidate. Repeat successful checks only after a relevant change, failure or unresolved concern. A selected run must not be reported as a full-suite pass.

## Offline checks

- Focused example: `.venv/Scripts/python.exe -m pytest -q tests/test_git_hooks.py` for hook/installer work. Select other files using the responsibility guards in [AGENTS.md](../AGENTS.md).
- Broad application check: `.venv/Scripts/python.exe -m pytest -q --ignore=tests/test_git_hooks.py`. Only repository-installation tests are excluded; evidence, credentials, providers, rate limits, cancellation and deletion remain. Shared transport/routes/persistence/lifecycle changes require broad checks; use the full suite when impact is unclear.
- Before delivery: `.venv/Scripts/python.exe -m pytest -q` and `git diff --check`.
- Frontend changes also need `node --test frontend/tests/source-text.test.js frontend/tests/boundary-state.test.js` and, from `frontend/`, `node node_modules/vite/bin/vite.js build`. Documentation/test-fixture changes do not require a frontend build or browser/model calls.

Install with `.venv/Scripts/python.exe -m pip install -r requirements-dev.txt` once when setting up/updating the environment, not before each check. Python and frontend dependencies use the existing lockfiles. On macOS substitute `.venv/bin/python`; Windows is the verified platform.

Hook tests initialize one pristine repository per module and copy its complete files and `.git` directory for each case. Every case still runs real Git commits independently; refs, index and config are not shared. The actual checkout's size hook remains enabled on every commit. Installation and size-limit details belong to [AGENTS.md](../AGENTS.md) and the setup scripts.

## Browser checks by affected flow

| Changed flow | Script under `scripts/` |
|---|---|
| Import, register, approval, new Word, history/transfer | `browser-smoke.cjs` |
| Provider/model selection and credentials | `browser-settings.cjs` |
| Project deletion, stale tabs and confirmation | `browser-project-deletion.cjs` |
| Document-boundary suggestions and source review | `browser-boundaries.cjs` |
| Model RPM settings | `browser-rpm.cjs` |
| Cancellation, cancel/delete and sourced explanations | `browser-cancellation-explanations.cjs` |

Run affected flows. Shared navigation/API/persistence changes need smoke plus all affected flows; a demo release or broad/uncertain changes need all six once. Capture screenshots and check console/page errors; deliberately injected error cases must remain explicitly identified.

From the project root, create fixtures with `.venv/Scripts/python.exe scripts/make-fixtures.py`, then start `.venv/Scripts/python.exe scripts/serve-workflow-fixture.py` in a separate terminal. Set `DEMO_URL=http://127.0.0.1:8766` and run `node scripts/<script>`. This fixture supports all six flows with temporary projects/settings, dummy credentials, scripted provider content and blocked external connections. Run cancellation/explanations last because it configures delays; stop the fixture when finished. Never target real projects or the production demo. The older offline fixture lacks these delay controls.

Playwright is separate tooling, resolved through `PLAYWRIGHT_MODULE` or `NODE_PATH`; scripts use installed Edge by default. Screenshots stay under ignored `output/`. `BROWSER_OUTPUT_DIR` applies only to scripts explicitly supporting it.

## Real API checks are separate and opt-in

Offline tests block external sockets. Scripted responses verify plumbing/evidence gates, not model quality. Use a live check when relevant provider/prompt/schema/model-call behavior changes or fresh provider evidence is needed. UI layout, documentation and test-fixture cleanup need no new model calls.

| Evidence needed | Script under `scripts/` |
|---|---|
| Synthetic PDF-to-register/review/new-Word/bundle workflow | `live-provider-smoke.py` |
| Combined-document boundary decisions | `live-boundary-smoke.py` |
| Sourced explanations, missing evidence and conflict | `live-explanations-smoke.py` |
| Actual HTTP request pacing | `live-rpm-smoke.py` |

Scripts default to dry runs. `--live` uses an enabled Groq credential within the existing free-use authorization; it does not authorize paid providers or billing changes. The provider workflow accepts `--use-groq` without changing saved selections; otherwise Groq must be selected. Use synthetic data; real-document transmission needs the required file-specific authorization.

Retain evidence with its tested version/configuration. Relevant model changes need new calls before claiming current live success; UI-only changes do not invalidate unchanged model evidence. Distinguish offline implementation checks, real provider success and complete sample-workflow success, with untested services and limits. Synthetic success does not certify clinical accuracy, full recall, complex-region coverage or remote cancellation.
