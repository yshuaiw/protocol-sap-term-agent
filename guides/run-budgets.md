# Long-document run budgets

In **API settings → Run budgets**, save the maximum **output tokens per response** and **HTTP attempts per run**. Defaults are **16,384 tokens** and **10,000 attempts**; allowed application ranges are 512–131,072 and 1–1,000,000. A model may support less. These are maximums, not a request to generate that many tokens, but larger budgets can increase usage. Boundary scan/transcription retain smaller task-specific output caps.

Settings persist privately beside provider/RPM settings and apply to the next operation. Running operations keep their snapshots. Saved UI budgets override the legacy `TERM_AGENT_MAX_OUTPUT_TOKENS` and `TERM_AGENT_MAX_CALLS` environment defaults; those files remain compatible. Updating code requires a backend restart and browser refresh.

Every real HTTP attempt counts, including retries, provider errors and network failures. Accepted cache hits use no attempt and no RPM slot. The earlier limit incorrectly counted cache hits as model calls; it no longer blocks cached replay at 500 results. The limit remains finite and stops further requests when reached.

After an ordinary failed generation, accepted results can be reused. Retry still walks the pipeline; it is not a jump to a saved batch number. Runtime attempt/output budgets and RPM do not invalidate accepted caches. Older cache filenames are reconstructed using compatible saved run configurations. Matching still requires the same provider/model, semantic configuration, exact input/media, schema, prompt and adapter identity. All source/evidence checks still run. Files are not bulk-rewritten or migrated. A project bundle does not transfer AI caches.

Explicit cancellation still discards the current operation's new results/cache and preserves older data/RPM history. Changing provider or document content is a new operation; cross-provider checkpoint resume is not supported.

Output-limit truncation, refusal/incomplete output, invalid JSON and schema failure now have distinct safe errors with stage information. Partial output is never accepted; no rule/provider fallback or unlimited retry is added. Increasing budgets cannot guarantee that a model will produce complete or semantically correct output. Reported tokens still omit unavailable usage from failed responses.

Offline contracts: `tests/test_run_budgets.py`; browser settings: `scripts/browser-run-budgets.cjs`. See the [verification workflow](verification.md) for check selection. A successful synthetic provider probe does not establish full long-document completion or clinical accuracy.
