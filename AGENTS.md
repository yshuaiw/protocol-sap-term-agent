# Project guidance

- When local `docs/development-handoff.md` is present, start by reading it for scope, verified state and next steps. The `docs/` folder and `Presentation 2.txt` / `Presentation 3.txt` are intentionally local-only and must not be added to Git. In a fresh clone without those files, start with `README.md` and inspect the implementation/tests instead.
- When available locally, `docs/decisions-protocol-sap-agent.md` is the chronological decision log. Later confirmed decisions supersede earlier alternatives; in particular, local operation replaced cloud deployment.
- When available locally, read the source proposal DOCX and `Presentation 2.txt` for detailed requirements. The user's confirmed PDF input and other later decisions take precedence over the original proposal where they differ.
- The selected architecture is Python/FastAPI plus React, running locally with a browser interface. Design for Windows/macOS; verify Windows first for the midterm. Do not introduce an online account system as a prerequisite.
- Retain the agreed full-document, all-region terminology scope. Verify actual coverage and report concrete limitations rather than silently narrowing it.
- Development began on 2026-11-14 after explicit user authorization. Read local `docs/implementation-notes.md` and `docs/verification.md` when present for actual implementation and limits; otherwise use `README.md`. Do not mistake the earlier planning baseline for current status or claim unfinished OCR/AI/complex-region work is complete.
- GitHub repository supplied by the user: `https://github.com/yshuaiw/protocol-sap-term-agent`. Check current local Git state and remote authentication before acting; the handoff does not establish remote accessibility or existing contents.
- Use Git CLI for small, reviewed commits and tags for verified demo versions. Keep API keys, local environments, caches, and personal runtime data out of version control.
- Application history must persist with the local project and support transfer to the teammate's computer. Code Git history alone does not implement this feature.
- Inspect available data and tools before asking the user to repeat confirmed requirements or investigate facts that can be checked locally. Record meaningful implementation choices and actual verification results in the project documentation.
- Before adding a function or rule, search the existing implementation for an equivalent responsibility.
- If the pre-commit size guard rejects a file, split it by responsibility, stage the smaller files and retry; see `scripts/check-file-size.py` for the 20,000-byte limit and generated-file exemptions.

| Development rule | Verification guard |
|---|---|
| Bound discovery output pressure without dropping source spans: count serialized context/metadata, cap units per batch, and keep GPT-OSS discovery reasoning explicit. | `tests/test_discovery_budget.py`; real-provider success must be reported separately from simulated tests. |
| Compute discovery character offsets from unique exact quotations within submitted ranges; never delegate character counts to the model or guess ambiguous matches. Keep browser evidence slices in the same Unicode coordinates. | `tests/test_discovery_anchors.py` and `frontend/tests/source-text.test.js`, including Unicode, repeated terms, overlapping chunks and rejected invented/out-of-range evidence. |
| Send only target records to discovery; neighbor context belongs in linking. Require one explicit model correction/scope decision for rejected spans; keep unknown/conflicting concept references separate and unresolved. Respect bounded provider cooldowns without upgrading accounts. | `tests/test_discovery_target_scope.py`, `test_discovery_repair.py`, `test_link_conflicts.py`, `test_rate_limits.py`; real-provider evidence is separate from scripted tests. |
