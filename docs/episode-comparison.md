# Full-episode model comparison

scripts/compare_episode.py reuses the context-aware batch translator,
alignment/repair engine, Persian validation, wrapping and atomic SRT writer.
It runs in a separate development process; it never changes normal automation
scope, provider settings in the web process, production, service hooks or source
selection policy. An explicitly selected English HI sidecar is permitted here.

Default variants:
- gpt-4o-mini (temperature 0.1, 8192 completion cap)
- gpt-6-luna-none (reasoning_effort none, 8192)
- gpt-6-luna-medium (reasoning_effort medium, 32768)
- gpt-5.4-mini (reasoning_effort none, 8192)
- gpt-5.6-terra (reasoning_effort none, 8192)

Reasoning variants omit temperature. All use standard service tier, identical
source cues, natural_conversational style, 40-cue/12000-character batches,
two neighboring English cues, 15-second scene gaps and bounded reference text.
One common quality instruction preserves voice, humor, profanity, HI labels,
sound descriptions and lyrics without censorship, invention or credits.

Outputs are <exact-video-basename>.<variant-id>.fa.srt. Never create the ordinary
.fa.srt. Existing outputs are preserved; malformed existing files cause refusal.
IDs, order and exact timestamps must match. No watermark, credit or model label
is added inside the subtitle content.

## Commands (development container only)

Copy the verified benchmarks/models.json into private development data as
dev/runtime/data/comparison-pricing.json, without any credential in the JSON.
Supply exact absolute container video/source paths, not a folder or pattern.

~~~sh
docker exec ust-dev-backend python /smoke/compare_episode.py \
  --video "/media/shows/EXACT/EPISODE.mkv" \
  --source "/media/shows/EXACT/EPISODE.en.hi.srt" \
  --pricing-file /app/data/comparison-pricing.json --budget-usd 5
~~~

This prepares the immutable plan and ledger, hashes both originals, validates
every source cue, prices all planned complete translations and makes NO inference
calls or library writes. If its conservative first-pass reservation exceeds the
approved limit, it stops. Metadata lookup is not an inference compatibility test.

Only after explicit spending authorization, repeat the SAME command with
--allow-paid. Use a detached docker exec and private log under /app/data/comparisons
for long runs. Normal automation must stay paused and the real-library
automation gate must stay false. No development container recreation is needed.
The existing development key is consumed privately from application settings.

The 3 Body Problem S01E03 five-variant comparison was explicitly authorized
with a USD 5 total cap. Its English source has 736 cues and 19 batches per variant.
At verified standard rates, its complete first-pass worst-case reservation is
USD 4.0008761, including potential Luna/Terra cache writes and Luna Medium's
hidden reasoning within the completion cap. The remaining USD 0.9991239 is the
maximum extra allowance for retries/repairs. This is not the expected bill.
Medium reasoning is not presumed better. The 96-request synthetic benchmark
is not part of this workflow.

## Durable spending and restart behavior

Private state is DATA_DIR/comparisons/<stable-video/source-path-hash>/:
- plan.json: hashes, exact paths, style, batch/prompt hashes, variants and prices
- cost.sqlite: immutable plan, request reservations, raw usage, request/model
  identifiers, latency, errors, reasoning tokens and validated batch checkpoints
- results.json: output paths/hashes, structural checks and per-variant totals
- run.lock: exclusive writer lock released automatically after process exit

Each request commits a worst-case reservation before submission. Reservations
are never refunded, even after ambiguous timeout/error. The limit includes
reserved first calls for unfinished variants, so early repairs cannot consume
their allowance. SDK retries are disabled. Alignment and language repairs use
the same ledger. The guard can stop before completion; never delete its ledger,
raise its limit or move to a fresh run directory to bypass spending authorization.

Restart the same command/config. It refuses changed source, prompts, model
parameters, prices or budget in the existing ledger. Completed outputs are
validated and preserved; unfinished models resume from validated cached batches.
Requests interrupted before their response/checkpoint remain conservatively
charged and need another reservation before retrying. No paid batch is resent
when a completed checkpoint exists.

Reasoning output tokens are INCLUDED in total completion tokens, not added again
to the bill. Cost uses ordinary/cached/cache-write input tokens when exposed and
the verified rates. If cache-write usage is absent for a premium-write model,
usage_cost_usd is a lower estimate and usage_cost_upper_usd conservatively prices
the unclassified tokens. Preserve raw usage and disclose any unresolved billing
range or failed request with unknown usage; do not call estimates invoice charges.

## Validation and quality review

Every batch is checked against its exact original IDs/timestamps, blanks,
unchanged English and Persian-script content. Mixed Latin words are also
reported for human review: proper names/acronyms may be legitimate, while an
ordinary English phrase inside a Persian cue may remain partially untranslated.
These flags must not be hidden by a passing whole-cue script check. A bad language cue can be repaired
using its original source/context through the same engine and budget. Full
outputs are validated again before and after atomic no-overwrite publication.
Original video/source SHA-256 and existing subtitle hashes are checked unchanged.

Jellyfin recognition is separate: inspect only the selected episode's MediaStreams
for five distinct external SubRip Persian tracks, each with its model/effort title
and matching sidecar path. Existing embedded Persian remains untouched. If
real-time monitoring does not detect them, refresh that episode only without
replacing metadata/images. Never request a global library refresh.

Review models at the same dialogue timestamps. Record meaningful differences
in semantics, naturalness, character voice, humor/profanity, and context use.
Compare Luna None/Medium separately with their measured reasoning usage and
latency. Do not declare an automatic quality winner.


## Explicit additional Luna Low variant

The user additionally authorized a complete gpt-6-luna translation with
reasoning_effort=low, still inside the SAME USD 5 total ceiling.
Its output suffix is .gpt-6-luna-low.fa.srt. Temperature is omitted; its 32768
completion cap includes hidden reasoning. Source, segmentation and prompts
remain identical to the five original variants.

Repeat the existing command with --add-luna-low (prepare), then the same flag
plus --allow-paid (live). This appends only that explicitly permitted variant
to the existing plan. It records the previous/new plan in the amendments table,
preserves all original request reservations/usage/checkpoints, and checks
reserved requests plus newly pending tasks against the unchanged cap in one
transaction. A price, budget, source, prompt or original variant change remains
forbidden. No fresh ledger is created and no reservation is refunded.

Six first passes have a conservative planned total of USD 4.34471235.
After the five actual runs' repairs, adding Low's first-pass reservations gives
USD 4.521482275, below the approved USD 5. Low repairs must still fit the same
remaining balance. The original five outputs are validated and preserved,
never retranslated or overwritten. Keep --add-luna-low on future resumptions
of this amended six-variant comparison.

Private results-five.json preserves the first five-model report; results.json
reports the amended run. Combine their processing durations for the six
translations. Read per-variant usage directly from the shared cost ledger.
