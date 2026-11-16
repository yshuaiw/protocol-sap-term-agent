# Document-sourced term explanations

New AI register generation automatically adds an explanation stage. Existing projects use **Supplement / update explanations**. Opening a project makes no model calls. A legacy `definition` without supporting evidence is displayed as **Legacy model suggestion — unverified**; it is never promoted into a sourced explanation automatically.

The stage scans every selected readable project text range in bounded batches for each bounded group of concepts. It uses the operation's fixed text provider/model and existing request limits. This adds calls/tokens proportional to document and concept count; use [cancellation](llm-cancellation.md) when a test no longer needs to continue. No external knowledge or rule-generated explanation fills missing evidence.

Each proposed assertion is labelled **Document statement (model identified)** or **Synthesis from document evidence (model inference)**, with its own document role/name, page or DOCX unit, region, quotation, exact Unicode location and proposed support rationale. The backend accepts only uniquely exact quotations in the actual submitted source ranges. A bare term/name is rejected as definition evidence. Exact matching proves quotation location, not semantic entailment: a model can still misunderstand a statement or attach insufficient support. Human review is required.

Compatible details remain together as individually sourced claims. A separate model review labels complementary, conflicting or uncertain relationships without silently replacing either document's explanation. For conflicts, inspect both explanations and record accepted/rejected/pending decisions and notes per assertion. Model flags remain visible even after individual reviews; acceptance is not an automatic declaration that all conflicting statements agree.

Missing evidence, incomplete scans, rejected quotes and failed relationship reviews are explicit. Ordinary explanation failure retains the valid registry and already-validated claims; a failed update may retain older claims only if their source anchors still match. It does not automatically continue through another provider. Cancelling instead discards the entire current operation, including a new register not yet saved.

Visual transcriptions remain unverified and require original-source comparison. Claims anchor to current selected project text; after approved edits, affected quotations are marked as working text while the immutable original retains earlier wording. Changed source anchors prevent reviewer acceptance until explanations are updated. This stage does not perform new OCR or repair native-PDF timeouts.

## Verification boundaries

Offline contracts cover all seven adapters, exact/ambiguous/invented/out-of-range and bare-name evidence, Unicode, multi-source synthesis, conflict/missing/partial results, preservation and reviewer persistence. Browser fixtures deliberately simulate missing/conflicting/partial responses and never measure semantic model quality.

Free Groq synthetic text checks exercise real explanation calls and a separate synthetic PDF-to-register/review/new-Word/bundle workflow. Approval actions in that workflow are scripted test actions. These results do not establish clinical accuracy, full recall, scanned/complex-region coverage, remote request cancellation, other-provider live success or macOS compatibility. Local evidence and precise run counts remain in ignored `docs/` and `output/`.
