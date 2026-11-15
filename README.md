# Protocol and SAP Terminology Agent

A local FastAPI + React workspace for importing PDF document pairs, reviewing terminology evidence, approving individual naming changes and exporting separate Word working copies. No account, database service or API key is required for this first rule-based release.

**This is a midterm technical baseline.** AI concept linking, OCR, complete terminology recall, automatic version compatibility and faithful reconstruction of complex tables/native Word footnotes are unfinished. Every selected PDF page is scanned; unsupported content is flagged and retained as unchanged source-page images in the Word appendix.

Development handoff notes in `docs/` and the course's `Presentation 2.txt` / `Presentation 3.txt` are local-only materials and are not included in current source checkouts. They are not required to run the application. Earlier commits/tags may still contain them; ignore rules do not erase Git history.

## Install on Windows

Install Python 3.12 (with **Add Python to PATH**), Node.js 22.12 or later, and Git. Clone the current main branch into a writable folder:

```powershell
git clone --branch main https://github.com/yshuaiw/protocol-sap-term-agent.git
cd protocol-sap-term-agent
powershell -ExecutionPolicy Bypass -File scripts/setup.ps1
powershell -ExecutionPolicy Bypass -File scripts/start.ps1
```

Open **http://127.0.0.1:8765**. Keep the terminal open; Ctrl+C stops the server. Setup downloads dependencies; the app itself makes no cloud/model requests. Built React assets are served by FastAPI, so one local server is sufficient.

For development environments with Python/pnpm outside PATH, `setup.ps1` accepts `-Python <executable>` and `-Pnpm <executable>`. The application contains no dependency on Codex's bundled runtime or any developer-specific absolute path.

## macOS

Designed for macOS, **not yet tested on macOS**. Install Python 3.12 and Node.js 22.12+, then run:

```bash
bash scripts/setup.sh
bash scripts/start.sh
```

## Use the workflow

1. **Import PDFs**: choose two files, or a combined PDF containing independent Protocol and SAP documents. Review the proposed page ranges, title/version evidence and compatibility note. Do not treat a statistical analysis chapter as a standalone SAP. Unselected versions remain intact in the original file but are excluded from indexing.
2. **Terminology register**: review rule candidates, correct standard names and aliases, add missing concepts, and correct individual occurrence associations. Adding a known form searches it across all selected text blocks. Confirming a concept confirms its unambiguous exact forms; ambiguous collisions remain unresolved. Registry edits do not modify document text.
3. **Replacement review**: select a concept and explicitly map each form, including abbreviations, to its replacement. Unmapped forms are preserved; unconfirmed and numeric/design changes are blocked. Historical references are conservatively preserved. Inspect context and source links, then approve individual update rows.
4. **Export**: acknowledge coverage limits and apply the selected changes. Download both Word working copies, `verification.json`, `change-log.json` and the reindexed `mention-index.json`. Word contains an editable transcription and an unchanged source-image appendix. Old names in that appendix are intentional and are not revised content.
5. **History and transfer**: restore any snapshot as a new revision, or export the complete project ZIP. On another computer, open the ZIP using **Open project bundle**. Originals, registry edits, decisions, Word files and history travel together. Transfer archives contain the documents; share them only with intended collaborators.

The workspace is stored in `data/projects/` next to the application, not in browser local storage. Set `TERM_AGENT_DATA` to change that location. Do not delete `data/` to upgrade code. Project ZIPs are independent of Git commits and are excluded from version control.

## Prepared real demo

The user's source PDFs are deliberately excluded from Git. On the development computer, the prepared packages are:

- `output/DAPA-CKD-demo-project.zip`: full selected original editions, ready for review.
- `output/DAPA-CKD-reviewed-demo-project.zip`: four explicitly reviewed abbreviation-list changes with preserved and unresolved matches and verified exports.
- `output/screenshots/`: browser backup screenshots; synthetic workflow and real project screenshots are distinct.

To reproduce locally when the original files are in `Protocols/`:

```powershell
.venv/Scripts/python.exe scripts/prepare-demo.py
# With the app running:
.venv/Scripts/python.exe scripts/verify-real-demo.py
```

The selected Protocol is version 1.0 (26 October 2016), PDF pp3–79; SAP is edition 1.0 (1 February 2017), PDF pp1–30. Same study code and original-edition timing are verified; explicit SAP-to-protocol version compatibility remains unconfirmed. The demonstration is a partial naming edit, not a validated clinical revision or reference benchmark.

## Development and checks

```powershell
.venv/Scripts/python.exe -m pip install -r requirements-dev.txt
.venv/Scripts/python.exe -m pytest -q
cd frontend
npx --yes pnpm@11.25.0 install --frozen-lockfile --ignore-scripts
node node_modules/vite/bin/vite.js build
```

`requirements.txt` pins direct production dependencies; `requirements-lock.txt` records the complete tested Windows/Python 3.12 environment, including QA packages. The pnpm lockfile fixes frontend resolution. Use `pip install -r requirements-lock.txt` to recreate the full tested Python dependency set.

For browser QA, install Playwright separately (`npm install --no-save playwright` in a disposable tooling folder), expose it through `NODE_PATH` or `PLAYWRIGHT_MODULE`, run `.venv/Scripts/python.exe scripts/make-fixtures.py`, and run `node scripts/browser-smoke.cjs` from the repository root with the app running. It uses installed Edge by default; set `BROWSER_CHANNEL=chrome` if necessary. This creates local synthetic QA projects and screenshots. `scripts/capture-real-demo.cjs` captures the prepared real project.

No benchmark precision/recall or held-out accuracy has been established. Additional development notes and source-data audit records are maintained locally outside version control.
