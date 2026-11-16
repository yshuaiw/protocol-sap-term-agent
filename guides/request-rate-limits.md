# Configure request rate limits

Open **API settings → Request rate limits**. Choose the provider and exact model ID, enter **Requests per minute (RPM)** and select **Save model RPM limit**. Use **Edit text model limit** or **Edit visual model limit** to copy the saved task selection into the editor. Rate editing does not change task selections or credentials. Unsaved task selections must be saved separately first.

Each provider/model has an independent saved cap. Switching models or reopening the page retains the overrides. **Use app starting cap** removes that model's override; it does not delete a key. Profiles remain in ignored machine-local `.env.providers.json`. The API accepts integer RPM values from 1 through 1000, up to 64 overrides per provider. This validation range is an application setting range, not a claim about provider quotas.

Starting caps are Groq 20, Google 4 and other adapters 10 RPM. They are conservative application starting values only and are **not verified free-tier/account limits**. Read your provider dashboard and adjust the cap below the applicable allowance, leaving room for other clients where needed. Saving or viewing settings never calls a model. Current account limits vary: [Google rate-limit documentation](https://aistudio.google.com/docs/rate-limits), [Groq rate-limit documentation](https://console.groq.com/docs/rate-limits).

## Sending behavior

- One shared gate in the backend covers discovery, repair, linking, vision/native PDF, boundary review, naming review, interpretation and audit. It checks a rolling 60-second request window and spaces starts at approximately `60 / RPM` seconds, with a small safety margin. It replaces the former fixed, boundary-only Google delay.
- Text and visual calls using the same provider/model share one bucket across projects, operations and browser tabs. Different provider/model combinations have independent buckets; a wait never holds the global gate lock. Different aliases that share a provider-side quota pool are not automatically identified as one model.
- Every actual HTTP attempt consumes a slot, including failed requests and bounded format/server/429 retries. Validated local cache hits consume none. Accepted call records show `rpm_limit` and `rate_wait_seconds` for diagnosis.
- Settings are copied once per operation. Saving a cap affects new operations, and does not reset recent usage or mutate an active operation. Recently stricter settings may keep a raised cap slower until their request window expires. Changing a key does not reset the bucket.
- Bounded HTTP429 Retry-After cooldowns are shared with other calls to that provider/model. A long or exhausted retry budget still stops with an error; no fallback provider or account upgrade is attempted. Low RPM can create pauses longer than the existing HTTP request timeout, because admission waits happen before the HTTP request starts.

Run one backend process per workspace/data store. The gate is in memory: restarting resets local request history, and multiple processes or external apps do not share it. Restarting is not a way to reset provider quotas; allow earlier traffic to age out before starting another run.

## Limits and verification

RPM pacing does not enforce TPM, daily quotas, provider-wide shared pools, capacity or usage by other applications. It does not fix network/read timeouts or the current native-PDF strategy that sends the whole original for each target page. Providers may still return429; lower the appropriate model cap or check the separate quota before manually retrying.

Offline contracts verify settings persistence/privacy, operation snapshots, concurrent admission, shared text/visual buckets, retries, cooldowns, cache bypass and independent models. The settings browser workflow verifies real local save/reload/reset behavior, task/key preservation and desktop/mobile layout using an isolated fixture. Scripted provider bodies are not live model evidence.

On 2026-11-15, three uncached Groq `openai/gpt-oss-20b` calls with synthetic text and a 3 RPM cap started at 0, 20.063 and 40.125 seconds; 3,707 reported tokens. This proves the tested request spacing and successful API responses, not full terminology quality or a complete project workflow. Other providers' live RPM enforcement was not tested. `python scripts/live-rpm-smoke.py` is a dry run; use `--live` only with an authorized Groq account. It sends synthetic text only and does not change saved settings or projects.

Startup commands are unchanged. After updating the code, restart the backend once and refresh the browser. Later RPM saves apply to new operations without a restart.
