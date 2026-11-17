# Bounded semantic linking

Long registers no longer resend the whole concept ledger with complete evidence paragraphs in every request. Linking uses compact concept cards with all names/aliases, definitions, exact quotations and source pointers. Large alias lists span multiple index fragments; every fragment is checked before proposing a new concept.

Candidate groups shrink to fit the complete serialized provider request, including prompts, schema and metadata. The default maximum remains eight candidates (`TERM_AGENT_LINK_BATCH_SIZE`). Index pages and evidence packets stay below 60,000 serialized characters. This is an application input guard, not a token count or a guarantee about a particular model's context window.

Possible existing matches receive a separate source check. The original candidate and representative evidence blocks remain local in full and are submitted in overlapping, program-owned ranges when needed. Conflicting pages, unknown references, inconsistent names/categories and insufficient evidence remain separate and unresolved. Missing, duplicated or invented candidate IDs stop the operation. Quotation location and model agreement do not establish semantic correctness; human review remains required.

The active operation shows completed linking candidates, current index pages, cache hits and actual linking HTTP attempts. The saved run also shows total index/evidence checks and legacy batches reused. A checked page is an intermediate result, not a completed register.

Previously accepted legacy linking batches are read only when their original request identity matches exactly, in order, without issuing old-style HTTP requests. After the first miss, linking uses the bounded stages and their separate cache version. Discovery/vision inputs, prompts and settings are unchanged by this fix. Cache gaps, changed source/model or earlier changed decisions can still require new requests; this is not a promise of complete or cross-provider resume.

Pagination and evidence verification can add requests even though each input is smaller. Existing RPM and run budgets, explicit cancellation and manual provider switching still apply. Outputs can still be refused, invalid or exceed provider limits. This change does not fix native-PDF timeouts or certify long-document completion, recall or clinical accuracy.

Checks: `tests/test_bounded_linking.py` covers large/late index matches, all aliases, full long evidence including tail conflicts, exact candidate IDs, cache-only legacy replay and seven provider envelopes. `scripts/browser-linking.cjs` verifies progress and zero-HTTP cache replay against the isolated scripted fixture. Real-provider evidence is recorded separately from these simulations.
