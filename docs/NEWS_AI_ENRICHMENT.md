# News AI enrichment (decision NEWS-CONTENT; built 2026-10-22; LIVE from 2026-10-22 16:46 IST)

**What it does:** every 30 min, `ops/runbooks/news_ai.sh` sends each news item of the last 48 h that has no enrichment yet to an AWS Bedrock model (Converse API, temperature 0). The model returns a closed JSON schema (`app/news/ai.py`, prompt `news-ai-v1`):
- `summary`, `entities`, `event_type`;
- `market_scope`, `potential_impact`, `impact_direction`;
- `confidence`, `key_facts`, `risk_flags`.

The prompt says "use only the text given, do not predict prices".

**What it is not:**
- It is enrichment, never a source fact. It never overwrites an item field.
- Stage 3/4 do not read it. Using it as features needs weeks of data and a new, separately pre-registered model (not E5, which is frozen).
- No order is ever touched.

## Point in time

`news_ai_enrichment.knowable_at = generated_at`: the moment the answer was received (DB CHECK `knowable_at >= generated_at`), never the item's own time. A future feature reads an enrichment only when `knowable_at < as_of`, like every other input. An enrichment of an item first seen at 08:50 but generated at 09:20 is therefore invisible to that day's PRE_SESSION (08:59:59) snapshot.

## Storage and versions

- **Row contents:** `model_id`, `model_version` (the `x-amzn-bedrock-model-version` header), `prompt_version`, `input_sha256` (prompt version + model + the exact prompt), `output` or `error`, and the status.
- **Stored once:** OK and INVALID (unique per item, model, prompt and input).
- **Not stored:** ERROR and TIMEOUT (throttling, network). They are counted in the run's log line and retried by the next run.
- **Model change:** a new model id or prompt version enriches every item again under its own key. The old rows stay.

## Limits (cost guard)

- At most 400 calls per run and 4 concurrent calls.
- At most 4,000 stored enrichments per IST day.
- 20 s timeout per call.
- Measured volume: 1,200–2,000 items per weekday (7 sources, mostly NSE announcements) and ~220 characters per item. That is roughly 350 input and 200 output tokens per call.

## Status (2026-10-22)

- **Configured:** `backend/.env` has `PRAJNA_NEWS_AI_ENABLED=true`, model `amazon.nova-pro-v1:0` and region `us-east-1`. Backup: `var/backups/env_20261022T164152.bak`.
- **Scheduled:** the cron line is installed.
- **Key:** the user chose to keep the existing Bedrock API key (2026-10-22), rather than rotating it after it was pasted into a chat.
- **First run (16:46 IST, 5 items):** 5 OK, 0 errors, about 1 s each, `knowable_at = generated_at` on every row. `model_version` comes back empty for Nova Pro: the header is not sent.
- **Known limit, prompt `news-ai-v1`:** `event_type` is free text, so the labels vary in form (`PRODUCT_LAUNCH`, `Market Analysis`, `policy_announcement`). A feature must normalise them, or a `news-ai-v2` prompt with a closed list is needed before E6.

## Enable (the user)

1. Rotate the Bedrock API keys that were pasted into a chat on 2026-10-22, then create a new one.
2. In `backend/.env`:
   ```
   PRAJNA_NEWS_AI_ENABLED=true
   PRAJNA_NEWS_AI_MODEL_ID=amazon.nova-pro-v1:0
   PRAJNA_NEWS_AI_REGION=us-east-1
   AWS_BEARER_TOKEN_BEDROCK=<new key>
   ```
   The key travels from `.env` into the job's environment only. It is never in argv and never printed. boto3 ≥ 1.39 reads it (the `ai` extra).
3. Cron: `10,40 * * * *  cd $B && ops/runbooks/news_ai.sh >> var/logs/cron.log 2>&1`.

**Off:** unset `PRAJNA_NEWS_AI_ENABLED`, or engage the news kill switch (`prajna news kill on`). The command then refuses with exit 3, makes no model call, and the runbook logs `NEWS_AI rc=3 REFUSED`.

**Log:** `var/logs/daily/news_ai_<day>.log`, one `NEWS_AI` line per run. Telegram alerts when every call of a run failed (credentials, model access, quota).
