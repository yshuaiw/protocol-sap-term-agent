# Protocol and SAP Terminology Agent

Local FastAPI + React workspace for PDF/DOCX document pairs, AI terminology discovery and linking, reviewer corrections, per-occurrence naming approvals, separate revised Word files and portable project history.

**Provider switching is implemented with separate text/visual settings and private local credentials.** Groq, Google, OpenAI, Anthropic, DeepSeek, Qwen and Kimi have offline-tested adapters. Only Groq has fresh live evidence: on 2026-11-15, three uncached requests completed discovery, linking and naming review on a synthetic native-text PDF pair (8 occurrences, 4 concepts; 6,794 reported tokens). Scripted reviewer actions approved two changes; separate revised Word files and a portable bundle passed deterministic verification, with original hashes unchanged. This is a synthetic sample workflow, not human semantic validation or general project completion. Vision/native PDF and the other providers have no live verification.

The earlier larger native-text Groq sample (34 occurrences, 21 concept proposals, seven ambiguous associations) remains historical evidence: it reused validated captured discovery responses and made fresh linking requests. Automated tests always use scripted provider responses and do not establish model accuracy.

## Windows setup

Use Python 3.12 and Node.js 22.12 or later. From a writable folder:

```powershell
git clone --branch feat/groq-ai https://github.com/yshuaiw/protocol-sap-term-agent.git
cd protocol-sap-term-agent
powershell -ExecutionPolicy Bypass -File scripts/setup.ps1
```

Open **API settings** in the sidebar to select text and visual providers/models independently, save or replace a key, or delete it. No project is required. Keys persist in plain text in local `.env.providers.json`; only configured/not-configured status is returned. Saving/refreshing settings makes no provider requests. Keys are never stored in browser local storage, project history, exports, bundles or Git. The existing `.env.*` exclusion also covers the atomic temporary file. Keep all existing ignore rules.

Groq remains compatible with raw local `API.txt`, `GROQ_API_KEY=...`, JSON containing `GROQ_API_KEY`, `.env`, or environment variables. Without a managed credential, environment variables override `.env`, and `GROQ_API_KEY` overrides `API.txt`. A saved UI credential overrides those legacy sources. **Delete key** removes the managed key and persists a disabled marker so an older file/environment key is not silently reactivated; the original file/environment remains unchanged. Save a new key to re-enable that provider.

Copy `.env.example` to `.env` for offline mode and advanced batch limits. Its initial `TERM_AGENT_OFFLINE=1` blocks requests; explicitly change it to `0` and restart when ready. Saved provider/model settings apply to the **next AI operation without a restart**. Each operation snapshots its settings and credentials; later changes cannot switch an active operation. Offline mode and environment changes require a backend restart. Failures require a manual provider change and new operation; cross-provider checkpoint resume is not supported.

```powershell
# Inspect without model requests:
powershell -ExecutionPolicy Bypass -File scripts/start.ps1 -Offline
# For live operation: use a fresh terminal, configure TERM_AGENT_OFFLINE=0, then:
powershell -ExecutionPolicy Bypass -File scripts/start.ps1
```

Open **http://127.0.0.1:8765**. Stop the previous server with Ctrl+C before changing mode. Importing files, loading projects and refreshing settings do not call models. **AI register generation, boundary suggestions, request interpretation, AI replacement review and semantic audit** explicitly send relevant document content to the selected providers.

## Provider adapters and verification

Set independent provider/model RPM caps in **API settings → Request rate limits**; see [request pacing](guides/request-rate-limits.md). All model stages and retries share these caps. Other quotas and network timeouts remain separate.

| Provider / channel | Credential environment fallback | Implemented input | Live verification |
|---|---|---|---|
| Groq | `GROQ_API_KEY` / `API.txt` | Text, images | Text sample workflow only |
| Google Gemini API | `GOOGLE_API_KEY` / `GEMINI_API_KEY` | Text, images, original PDF | Not tested: no authorized live credentials/budget |
| OpenAI direct API | `OPENAI_API_KEY` | Text, images, original PDF | Not tested: no authorized live credentials/budget |
| Anthropic direct API | `ANTHROPIC_API_KEY` | Text, images, original PDF | Not tested: no authorized live credentials/budget |
| DeepSeek direct API | `DEEPSEEK_API_KEY` | Text only in this adapter | Not tested: no authorized live credentials/budget |
| Qwen Model Studio, Singapore | `DASHSCOPE_API_KEY` | Text, images | Not tested: no authorized live credentials/budget |
| Kimi international API | `MOONSHOT_API_KEY` | Text, images | Not tested: no authorized live credentials/budget |

All rows have offline request/response/error contract tests. The fixed regional endpoints require matching credentials; regional/enterprise gateways and arbitrary base URLs are not supported in this version. Model fields are editable examples, not a guarantee of availability, pricing or capabilities. Defaults preserve Groq `openai/gpt-oss-20b` and `qwen/qwen3.8-27b`; a different model must accept its adapter's JSON/media parameters. Unsupported model/request combinations stop with a sanitized error; there is no silent provider or rule fallback.

Adapter references: [Groq JSON](https://console.groq.com/docs/structured-outputs), [Groq vision](https://console.groq.com/docs/vision), [Google generation contract](https://ai.google.dev/api/generate-content), [OpenAI Chat](https://platform.openai.com/docs/api-reference/chat/create), [OpenAI PDF](https://platform.openai.com/docs/guides/pdf-files), [Anthropic JSON](https://platform.claude.com/docs/en/build-with-claude/structured-outputs), [Anthropic PDF](https://platform.claude.com/docs/en/build-with-claude/pdf-support), [DeepSeek](https://api-docs.deepseek.com/api/create-chat-completion), [Qwen compatibility](https://help.aliyun.com/zh/model-studio/compatibility-of-openai-with-dashscope), [Kimi Chat](https://platform.moonshot.ai/docs/api/chat). Only official contracts were consulted; reading them is not live-provider evidence.

## Workflow

For combined PDFs, see [boundary review](guides/boundary-review.md): all-page structure indexing, expanded AI review, optional unreadable-page transcription, visible evidence and explicit range application. Empty results are labelled unresolved; an embedded statistics chapter is not an independent SAP.

1. Import separate Protocol/SAP files: two PDFs, two DOCX files or a mixed pair. A combined **PDF** supports nonoverlapping page ranges. **DOCX imports the whole document**; split combined DOCX documents first. Review titles, versions and optional AI boundary advice; model advice does not certify compatibility.
2. Save originals, then explicitly generate the AI register. Every text block is submitted in bounded discovery batches, followed by semantic linking against a concept ledger. Proposed evidence must match anchored source text. Invalid or missing batch decisions fail the run without replacing the existing register. History retains earlier states.
3. Review standard names, aliases and occurrence associations. Same spelling does not prove identity. Model links require human confirmation; visual transcriptions require individual source comparison before modification.
4. Select a concept and replacement forms, or ask AI to interpret a natural-language request and review its proposed mappings. The configured text provider reviews update/preserve/unresolved decisions with evidence. Model advice cannot override human-preserved/unconfirmed occurrences, numeric protections or unsupported source regions.
5. Approve individual rows and export. **PDF and DOCX originals remain unchanged. Every export is a new Word file.** Native DOCX export patches a copied OOXML package, preserving unrelated parts and run formatting. PDF export reconstructs text/tables and appends unchanged source images. Exact text and approved differences are reread and checked.
6. Optionally request an AI semantic audit of changed before/after paragraphs. This is advisory, not proof of correctness or a replacement for deterministic checks.
7. Export a project ZIP to continue on another computer. Inputs, corrections, model-run metadata, approvals, exports and snapshots travel together; keys and transient AI caches do not. Restore creates a new revision.

The **explicit rule baseline** remains separately labeled for comparison and makes no model calls. Legacy projects remain loadable. Existing real-demo preparation scripts intentionally use the rule baseline; they are not AI evaluation results.

## Permanently delete a project

Use **Delete** beside one project in **Saved projects**. Review the confirmation dialog: project name and ID, document names, first/last saved times, concept/occurrence counts, history snapshots and exports. **Cancel** (or Escape) keeps the project. **Permanently delete** removes that project's register, occurrences, all snapshots, model cache/run records, previews/approvals, generated files and internally stored source copies. No typed confirmation or application recycle bin is used. There is no batch deletion.

External originals, previously downloaded ZIP/Word copies, independently imported projects and API settings/credentials remain intact. An exported ZIP can still be imported as a new project later. This is normal filesystem deletion, not a secure disk erase or deletion of backups held elsewhere.

Active LLM work can be cancelled and then deleted after confirmation; other active exports/downloads still block deletion. Changed projects require refreshed confirmation. See [LLM cancellation](guides/llm-cancellation.md). One backend process per data store is required; late writes cannot recreate deleted projects.

Deletion does not require intact input files. If Windows file locks or permissions interrupt removal, the app reports failure and warns that some files may already be gone; it retains the manifest where possible for a visible retry. Close files using the project, refresh its deletion details and retry. Linked project directories/descendants are refused before removal, so the action cannot traverse those links into external files. A corrupt project JSON or independent filesystem changes can require manual repair; no transactional rollback is promised for an interrupted filesystem deletion.

## Routing and coverage

- In `vision` mode every selected PDF page is rendered locally and sent with native text to the visual provider. Additional transcriptions remain unverified. PDF-to-Word is not a prerequisite.
- In `native` mode Google/OpenAI/Anthropic adapters submit the **original PDF bytes once per selected page**, with an explicit original page target and locally anchored native text. The full original, including pages outside the selected version/range, is sent. This can substantially increase tokens and cost. Originals above **15 MiB** are rejected with an explicit suggestion to choose page images; there is no automatic route switch. Page attribution/transcription remains model evidence requiring source review; it is not certified localization. Other adapters reject native PDF input.
- In `text` mode native text/table structure is submitted; missing image/scanned content is reported as a coverage gap, not complete editable coverage.
- DOCX indexing includes body paragraphs, nested tables, headers, footers, footnotes/endnotes, comments and text boxes. Names split across runs share a paragraph anchor. Fields, tracked revisions and comments are preserved but blocked from automatic edits.
- Embedded PNG/JPEG files can use vision. Other media, charts, equations and alternate-content imports are retained with explicit limitations. A text patch cannot rewrite pixels inside an original DOCX image.
- PDF paragraph grouping/reading order, complex structures, transcription accuracy and final layout require review. All-region scope remains a requirement; successful processing or valid JSON does not establish complete terminology recall.

Metadata records provider/model IDs, a non-secret configuration snapshot, request hashes, stage, cache use and reported token usage. Cache identity includes both task selections, processing mode, batch/output settings, schema, prompt version and simulation status; legacy Groq caches cannot collide with the new adapter identities. Credential values are excluded. `TERM_AGENT_MAX_CALLS` bounds operations; `TERM_AGENT_CHUNK_CHARS` controls batch size. Evidence-validated responses may be reused after failure. Free-tier limits can interrupt runs; partial work is not silently marked complete.

Discovery limits each batch to eight text units (`TERM_AGENT_CHUNK_UNITS`) and budgets serialized units conservatively, preserving all selected blocks and long-block overlapping ranges. One long unit can exceed that serialized budget. Neighboring text is retained for semantic linking but is not duplicated into discovery targets: real testing found the model extracting neighboring context under the wrong block ID. GPT-OSS discovery and evidence repair use `reasoning_effort=low`; other stages retain model defaults. `TERM_AGENT_MAX_OUTPUT_TOKENS` sets the output budget (default 4096). Linking uses at most eight candidates per batch (`TERM_AGENT_LINK_BATCH_SIZE`) with short local candidate/ledger references mapped back to persistent IDs. More batches can require more calls and time. These settings do not certify recall.

Provider JSON rejections are analyzed in memory for syntax/schema status and validation error types. Only structural summaries enter error messages/history; generated text, arbitrary field names and provider error bodies are withheld. `scripts/diagnose-groq.py` defaults to a dry run; `--live` explicitly sends at most two synthetic probes, not project documents.

Discovery asks for explicitly described `term_text` and `context_quote`, not character counts or a generic `text` field that can be confused with the whole input block. The program computes Unicode offsets from unique exact quotations within submitted ranges. A rejected proposal receives at most one model repair pass: the model must provide a verified correction, explicitly classify it as out of scope with a visible reason, or leave it unresolved and stop the run. No bad span is accepted, no silent rule fallback, case folding, approximate matching or first-match guessing is used. Missing/duplicated candidate IDs still stop linking. Unknown concept references and conflicting model group metadata remain separate, unresolved associations for manual review; they cannot overwrite a ledger concept or be bulk-confirmed as unambiguous.

For Groq HTTP 400 `json_validate_failed` from strict output, the adapter retries once with the same model/input in JSON-object mode; local validation remains mandatory. Each format permits at most two rate-limit waits, totaling at most 60 seconds, using `Retry-After` plus a small timing margin. Longer quota waits stop the operation. One server-error retry is allowed (at most seven HTTP attempts per model operation). The app never upgrades accounts or changes billing. Reported tokens cover successful responses, not a complete billing total for rejected attempts; cached responses do not report fresh usage.

## Offline checks

Setup installs the versioned `.githooks/pre-commit` hook for this checkout. Existing checkouts can run `.venv/Scripts/python.exe scripts/install-hooks.py` (macOS: `.venv/bin/python`). An existing unrelated hook configuration is retained and requires integration. Source blobs larger than 20,000 staged bytes are rejected; split by responsibility and retry. Lockfiles and explicitly named generated/build files are exempt; unstaged edits do not affect the check. `TERM_AGENT_HOOK_PYTHON` can select an interpreter for separate tooling environments. `frontend/src/main.jsx` now owns navigation only; registry, review, document/history and settings screens are split by responsibility.

```powershell
.venv/Scripts/python.exe -m pip install -r requirements-dev.txt
.venv/Scripts/python.exe -m pytest -q
node --test frontend/tests/source-text.test.js
cd frontend
node node_modules/vite/bin/vite.js build
```

Tests deny external socket connections and use `httpx.MockTransport` for model contracts. They exercise real local persistence, parsing, new-file export, unchanged source bytes and approval guards. Scripted answers test plumbing and evidence checks, **not model accuracy**. `requirements-lock.txt` records the tested Python environment; the pnpm lockfile fixes frontend dependency resolution.

For one small browser smoke flow, install Playwright separately in a tooling environment and expose it via `PLAYWRIGHT_MODULE` or `NODE_PATH`. Run `scripts/make-fixtures.py`, start `scripts/serve-offline-fixture.py`, then set `DEMO_URL=http://127.0.0.1:8766` and run `node scripts/browser-smoke.cjs`. Also run `node scripts/browser-project-deletion.cjs` to test cancellation, permanent removal of a newly created populated project, a same-name neighbor, stale confirmation/tab handling and mobile layout. It deletes only its own newly created fixture projects and retains a downloaded ZIP; never point it at a real project server. Run `node scripts/browser-settings.cjs` for separate task selection, reload persistence, credential save/replace/delete, no key echo and mobile settings checks. All browser scripts refuse servers without the offline-fixture marker. The fixture uses a dummy key, scripted transports, isolated `tmp/` project and settings storage and an external-socket block. Never use it for real projects or report its results as model quality. Settings screenshots stay in local `output/screenshots/provider-settings/`; workflow smoke artifacts use a fresh `output/browser-smoke-<timestamp>/` folder (or `BROWSER_OUTPUT_DIR`) so previous runs are retained.

## Opt-in live sample

After offline verification, `.venv/Scripts/python.exe scripts/live-provider-smoke.py --live` exercises a fresh synthetic PDF pair, real Groq text discovery/linking/review, scripted approval, new Word outputs and bundle privacy. Without `--live` it makes no requests. It refuses non-Groq text selection, missing credentials and offline mode. It uses isolated `tmp/` projects and writes evidence under local `output/live-provider-*/`; it does not modify existing projects, credentials or billing. This script makes real calls and does not attest account tier: run it only within your authorized Groq allowance. Other providers need separate credential/budget authorization before live verification.

## Storage and other platforms

Projects persist in `data/projects/`, independent of browser sessions and code Git history. `TERM_AGENT_DATA` can choose another folder. Run one backend process; multiple workers sharing storage are unsupported. Teammates should create their own environments and import a project ZIP, not copy `.venv`.

macOS scripts (`bash scripts/setup.sh`, `bash scripts/start.sh --offline`) are supplied but untested on macOS. The teammate's actual computer is also untested. Local `docs/` and Presentation text files are intentionally excluded from source checkouts and are not needed to run the app.

Sourced definitions and review: [Term explanations](guides/term-explanations.md).
