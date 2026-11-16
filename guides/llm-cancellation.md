# Stop LLM work

The workspace's **Active LLM operations** panel lists register generation, explanation updates, pre-import boundary suggestions, naming interpretation, replacement review and semantic audits. Click **Cancel LLM operation** to stop a task. The panel is visible across views and discovers active tasks after a page reload. Closing or refreshing the browser does **not** cancel or automatically restart work.

Cancellation immediately prevents subsequent model calls/retries once accepted, interrupts app RPM/cooldown waits, discards late responses, and prevents final persistence. While an HTTP call or local processing is still running, the panel says **Cancelling…**. It reports completion only after local work exits and cleanup finishes. Synchronous in-flight HTTP work may need to return or time out first; this feature does not guarantee immediate remote termination, refunds or erasure of provider usage/logs.

Cancelled operations leave no new local result, run entry, history snapshot or model cache. Pre-existing project data/cache remain. New accepted cache entries stay in memory until the operation commits; cancelled entries are discarded. Shared app RPM usage remains, because already-submitted requests still count against quotas. A backend restart clears transient task status; it is not checkpoint/resume support.

Cancellation and final saving share a lock: accepted cancellation blocks saving; a final save that wins first cannot be undone by cancellation. Refresh to inspect the completed result. Ordinary errors remain ordinary errors and may save the existing failed-run record; they are not reported as cancellation.

## Delete during LLM work

**Delete** remains available during processing. When the selected project has active LLM work, its identity/details dialog offers **Cancel tasks and permanently delete**. This reserves deletion, blocks new work, requests cancellation, waits for workers to stop, then removes project-internal data. It never reports success while work can still write back.

Other active exports/downloads/local operations still block deletion. A changed revision requires refreshed details and renewed confirmation. External originals, downloaded files, independent project copies and machine API settings remain untouched. Existing filesystem-lock/partial-removal limitations still apply. No recycle bin, secure erase, batch deletion or completed-operation undo is added.

One backend process per data store is required. Cancelling an unrelated project is never an implicit side effect of deletion. Verification scripts operate only on disposable fixtures; they do not cancel/delete saved user projects.

## Verification

`tests/test_cancellation.py` uses delayed offline transports, real project files and concurrent HTTP to verify all action types, RPM/retry interruption, deferred caches, source preservation and cancellation/commit/deletion races. `scripts/browser-cancellation-explanations.cjs` runs against `scripts/serve-workflow-fixture.py` on isolated port 8766, with refresh survival, explicit cancellation and cancel/delete states. This verifies local cancellation behavior, not remote-provider abort guarantees. See [sourced explanations](term-explanations.md) for the companion feature.
