# Review combined Protocol/SAP PDFs

Import one combined PDF, then explicitly select **Ask AI for boundary suggestions**. This sends structure excerpts to the configured text provider. With a configured visual route, pages without native text also go to the selected visual provider. Settings are fixed for this operation; there is no automatic provider or rule fallback.

The **AI boundary review** appears above the manual page ranges. It shows proposed roles/ranges, independent-document versus embedded-section classifications, confidence, reasons, source evidence, and native/visual/unreadable page counts. Open the original at the cited physical PDF page and compare the cover, study identifier, version and next document boundary. Printed page numbers may differ from physical PDF pages.

**Use suggested Protocol/SAP pair** applies a complete nonoverlapping pair. Individual **Use suggested … range** buttons let you choose among versions. Suggestions never change selections automatically. Visual evidence needs its own source-review checkbox before use; importing still requires the final independent-document/version review checkbox. Adjust the ranges manually if needed. Original files remain unchanged.

An embedded numbered statistics chapter is shown for review and cannot be applied as an independent SAP. Contents entries and promises of a future SAP do not establish an independent document. Multiple versions, uncertain boundaries and invalid model references require manual selection. An empty result means no usable proposal was returned; it does not prove that an independent SAP is absent. A failed rerun clears stale AI proposals while preserving the selected ranges.

## How the evidence is obtained

- Every physical PDF page receives a bounded structure index, including pages without extractable text. Index excerpts include early cover text, a line outside repeated running headers, broader title/section clue windows and page tails. These retrieval rules do not assign roles or choose final ranges.
- The model proposes candidate starts using program-issued source IDs. A second review receives expanded candidate/neighbor context, tentative starts and file-end evidence. It distinguishes continuations, independent documents, embedded sections and references. Inclusive end pages remain model proposals.
- The program resolves source IDs to exact original text and Unicode coordinates. Unknown references, missing/duplicate candidate decisions, invalid page ranges and overlapping independent proposals remain visible review problems. Uncertain starts prevent the pair shortcut. One invalid proposal does not hide other reviewable proposals.
- Batches count serialized metadata and text, with at most 24 index pages or six review targets and a 4,000–14,000 character budget derived from the text chunk setting. Oversized contexts stop explicitly; no page is silently dropped. This index is structure evidence, not a full-text reading or a guarantee of every boundary being found.
- Unreadable pages use the selected image/native-PDF route in groups of up to three. Visual transcription and page attribution remain unverified until checked. Native PDF sends the whole original, including pages outside the target group, with the existing 15 MiB limit. Text-only/missing-key cases report gaps.
- Boundary requests use the same configurable provider/model RPM caps as all other stages; see [request pacing](request-rate-limits.md). This replaces the former fixed Google boundary delay. Long/scanned files may take several minutes. Other quotas and network failures can still require manual action.

## Verification scope

Offline tests parse generated PDFs and exercise exact anchors, Unicode, full index coverage, scanned covers, invalid/missing/duplicate decisions, embedded sections, overlaps and multiple versions. The headless Edge workflow checks visible results, explicit application/import, original hashes, empty/error states, visual confirmation and mobile layout. Scripted provider responses are simulation evidence only.

On 2026-11-15, Groq `openai/gpt-oss-20b` completed four uncached calls on the final two **synthetic** cases: an independent pair spanning Protocol 1–3/SAP 4–6, and a single protocol with an embedded statistics chapter that was not accepted as a separate SAP. Earlier sparse fixtures exposed duplicate continuation starts and truncated ranges; those failures are retained locally. The final fixture includes explicit covers, document identity, continuation and end-page evidence. These results do not establish accuracy on sparse, clinical, long, scanned or multi-version documents. Other providers, visual/native-PDF calls and the full terminology/edit/export workflow were not live-tested in this boundary change.

To reproduce the synthetic live check, run `python scripts/live-boundary-smoke.py` first (dry run), then `--live` only with an authorized Groq account/key. It uses the locally enabled Groq credential without changing saved provider selections, existing projects or source files. The script sends synthetic PDFs only and saves safe local evidence under ignored `output/`.

Restart the backend after updating code, then refresh the browser. Startup commands are unchanged; see the root README.
