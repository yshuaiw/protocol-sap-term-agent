# Protocol and SAP Terminology Agent

Local FastAPI + React workspace for PDF/DOCX document pairs, AI terminology discovery and linking, reviewer corrections, per-occurrence naming approvals, separate revised Word files and portable project history.

**Version 0.2 has sample-level live verification, not general semantic accuracy certification.** On 2026-11-15, a small native-text PDF pair (28 blocks) completed quoted discovery and semantic linking using real Groq responses: 34 occurrences, 21 proposed concepts and seven ambiguous associations requiring review. Previously captured real discovery responses were revalidated and reused while linking was verified live. Vision, complete recall, semantic accuracy, sustained quota and other documents remain unverified. Automated tests use scripted responses and label runs as simulated.

## Windows setup

Use Python 3.12 and Node.js 22.12 or later. From a writable folder:

```powershell
git clone --branch feat/groq-ai https://github.com/yshuaiw/protocol-sap-term-agent.git
cd protocol-sap-term-agent
powershell -ExecutionPolicy Bypass -File scripts/setup.ps1
```

Put a raw Groq key in **local `API.txt`**, or use `GROQ_API_KEY=...` in that file, a JSON object with `GROQ_API_KEY`, a local `.env`, or an environment variable. Keys stay in the backend and never appear in the settings response or project bundles. `/API.txt`, `.env`, source documents, local notes, environments and runtime data are ignored by Git. Do not remove these exclusions.

Copy `.env.example` to `.env` to customize models. The example starts with `TERM_AGENT_OFFLINE=1`, which blocks every model request. Explicitly set it to `0` when ready for real calls. Existing environment variables override `.env`; `GROQ_API_KEY` takes precedence over `API.txt`.

```powershell
# Inspect without model requests:
powershell -ExecutionPolicy Bypass -File scripts/start.ps1 -Offline
# For live operation: use a fresh terminal, configure TERM_AGENT_OFFLINE=0, then:
powershell -ExecutionPolicy Bypass -File scripts/start.ps1
```

Open **http://127.0.0.1:8765**. Stop the previous server with Ctrl+C before changing mode. Importing files, loading projects and refreshing settings do not call models. **AI register generation, boundary suggestions, request interpretation, Groq replacement review and semantic audit** explicitly send relevant document content to Groq.

Default text model: `openai/gpt-oss-20b` (`GROQ_MODEL`). Default vision model: `qwen/qwen3.8-27b` (`GROQ_VISION_MODEL`). Account access can vary; vision access has not been live-verified. See [structured outputs](https://console.groq.com/docs/structured-outputs), [vision](https://console.groq.com/docs/vision), and [models](https://console.groq.com/docs/models). Model/quota errors are reported without silent rule fallback.

## Workflow

1. Import separate Protocol/SAP files: two PDFs, two DOCX files or a mixed pair. A combined **PDF** supports nonoverlapping page ranges. **DOCX imports the whole document**; split combined DOCX documents first. Review titles, versions and optional AI boundary advice; model advice does not certify compatibility.
2. Save originals, then explicitly generate the AI register. Every text block is submitted in bounded discovery batches, followed by semantic linking against a concept ledger. Proposed evidence must match anchored source text. Invalid or missing batch decisions fail the run without replacing the existing register. History retains earlier states.
3. Review standard names, aliases and occurrence associations. Same spelling does not prove identity. Model links require human confirmation; visual transcriptions require individual source comparison before modification.
4. Select a concept and replacement forms, or ask AI to interpret a natural-language request and review its proposed mappings. Groq reviews update/preserve/unresolved decisions with evidence. Model advice cannot override human-preserved/unconfirmed occurrences, numeric protections or unsupported source regions.
5. Approve individual rows and export. **PDF and DOCX originals remain unchanged. Every export is a new Word file.** Native DOCX export patches a copied OOXML package, preserving unrelated parts and run formatting. PDF export reconstructs text/tables and appends unchanged source images. Exact text and approved differences are reread and checked.
6. Optionally request an AI semantic audit of changed before/after paragraphs. This is advisory, not proof of correctness or a replacement for deterministic checks.
7. Export a project ZIP to continue on another computer. Inputs, corrections, model-run metadata, approvals, exports and snapshots travel together; keys and transient AI caches do not. Restore creates a new revision.

The **explicit rule baseline** remains separately labeled for comparison and makes no model calls. Legacy projects remain loadable. Existing real-demo preparation scripts intentionally use the rule baseline; they are not AI evaluation results.

## Routing and coverage

- This Groq adapter uses text and image requests, not native PDF ingestion. In `vision` mode every selected PDF page is rendered locally and sent with native text. Additional model transcriptions remain unverified. PDF-to-Word is not a model prerequisite.
- In `text` mode native text/table structure is submitted; missing image/scanned content is reported as a coverage gap, not complete editable coverage.
- DOCX indexing includes body paragraphs, nested tables, headers, footers, footnotes/endnotes, comments and text boxes. Names split across runs share a paragraph anchor. Fields, tracked revisions and comments are preserved but blocked from automatic edits.
- Embedded PNG/JPEG files can use vision. Other media, charts, equations and alternate-content imports are retained with explicit limitations. A text patch cannot rewrite pixels inside an original DOCX image.
- PDF paragraph grouping/reading order, complex structures, transcription accuracy and final layout require review. All-region scope remains a requirement; successful processing or valid JSON does not establish complete terminology recall.

Metadata records model IDs, request hashes, stage, cache use and reported token usage. `TERM_AGENT_MAX_CALLS` bounds operations; `TERM_AGENT_CHUNK_CHARS` controls batch size. Evidence-validated responses may be reused after failure. Free-tier limits can interrupt runs; partial work is not silently marked complete.

Discovery limits each batch to eight text units (`TERM_AGENT_CHUNK_UNITS`) and budgets serialized units conservatively, preserving all selected blocks and long-block overlapping ranges. One long unit can exceed that serialized budget. Neighboring text is retained for semantic linking but is not duplicated into discovery targets: real testing found the model extracting neighboring context under the wrong block ID. GPT-OSS discovery and evidence repair use `reasoning_effort=low`; other stages retain model defaults. `TERM_AGENT_MAX_OUTPUT_TOKENS` sets the output budget (default 4096). Linking uses at most eight candidates per batch (`TERM_AGENT_LINK_BATCH_SIZE`) with short local candidate/ledger references mapped back to persistent IDs. More batches can require more calls and time. These settings do not certify recall.

Provider JSON rejections are analyzed in memory for syntax/schema status and validation error types. Only structural summaries enter error messages/history; generated text, arbitrary field names and provider error bodies are withheld. `scripts/diagnose-groq.py` defaults to a dry run; `--live` explicitly sends at most two synthetic probes, not project documents.

Discovery asks for explicitly described `term_text` and `context_quote`, not character counts or a generic `text` field that can be confused with the whole input block. The program computes Unicode offsets from unique exact quotations within submitted ranges. A rejected proposal receives at most one model repair pass: the model must provide a verified correction, explicitly classify it as out of scope with a visible reason, or leave it unresolved and stop the run. No bad span is accepted, no silent rule fallback, case folding, approximate matching or first-match guessing is used. Missing/duplicated candidate IDs still stop linking. Unknown concept references and conflicting model group metadata remain separate, unresolved associations for manual review; they cannot overwrite a ledger concept or be bulk-confirmed as unambiguous.

For HTTP 400 `json_validate_failed` from strict output, the adapter retries once with the same model/input in JSON-object mode; local validation remains mandatory. Each format permits at most two rate-limit waits, totaling at most 60 seconds, using `Retry-After` plus a small timing margin. Longer quota waits stop the operation. One server-error retry is allowed (at most seven HTTP attempts per model operation). The app never upgrades accounts or changes billing. Reported tokens cover successful responses, not a complete billing total for rejected attempts; cached responses do not report fresh usage.

## Offline checks

Setup installs the versioned `.githooks/pre-commit` hook for this checkout. Existing checkouts can run `.venv/Scripts/python.exe scripts/install-hooks.py` (macOS: `.venv/bin/python`). An existing unrelated hook configuration is retained and requires integration. Source blobs larger than 20,000 staged bytes are rejected; split by responsibility and retry. Lockfiles and explicitly named generated/build files are exempt; unstaged edits do not affect the check. `TERM_AGENT_HOOK_PYTHON` can select an interpreter for separate tooling environments. The pre-existing oversized `frontend/src/main.jsx` must be split when it is next changed.

```powershell
.venv/Scripts/python.exe -m pip install -r requirements-dev.txt
.venv/Scripts/python.exe -m pytest -q
node --test frontend/tests/source-text.test.js
cd frontend
node node_modules/vite/bin/vite.js build
```

Tests deny external socket connections and use `httpx.MockTransport` for model contracts. They exercise real local persistence, parsing, new-file export, unchanged source bytes and approval guards. Scripted answers test plumbing and evidence checks, **not model accuracy**. `requirements-lock.txt` records the tested Python environment; the pnpm lockfile fixes frontend dependency resolution.

For one small browser smoke flow, install Playwright separately in a tooling environment and expose it via `PLAYWRIGHT_MODULE` or `NODE_PATH`. Run `scripts/make-fixtures.py`, start `scripts/serve-offline-fixture.py`, then set `DEMO_URL=http://127.0.0.1:8766` and run `node scripts/browser-smoke.cjs`. The smoke script refuses servers without the offline-fixture marker. The fixture uses a dummy key, scripted transports, isolated `tmp/` storage and an external-socket block. Never use it for real projects or report its results as model quality. Screenshots stay in local `output/screenshots/`.

## Storage and other platforms

Projects persist in `data/projects/`, independent of browser sessions and code Git history. `TERM_AGENT_DATA` can choose another folder. Run one backend process; multiple workers sharing storage are unsupported. Teammates should create their own environments and import a project ZIP, not copy `.venv`.

macOS scripts (`bash scripts/setup.sh`, `bash scripts/start.sh --offline`) are supplied but untested on macOS. The teammate's actual computer is also untested. Local `docs/` and Presentation text files are intentionally excluded from source checkouts and are not needed to run the app.
