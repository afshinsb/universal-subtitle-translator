# Controlled Coyote vs. Acme pilot — completed

Completed on Prime, 2026-10-14, after explicit approval for one 1080p movie,
GPT-6 Luna Medium, 32768 completion tokens and USD 1.50 total including repairs.
No service hooks or production replacement were authorized or performed.

## Delivered output

~~~text
/tank/share/media/movies/Coyote vs. Acme (2026)/Coyote vs Acme 2026 1080p AMZN WEB-DL DDP5 1 Atmos H 264-BYNDR.fa.srt
~~~

Source: matching MKV, ordinary embedded English SubRip stream 2. Source SHA256:
7393d3129a901c689cae6370108a29e48988c2bb960024ac34c839753c88747d.
1498 cues, 38 batches, natural_conversational style and existing dialogue context.
The actual persistent queue was populated by exact-file reconciliation, not a
service hook or whole-library scan. One queue attempt completed successfully.

The subtitle is UTF8, UID/GID1000:1000, mode0644, and was published without
overwriting a pre-existing subtitle. Exact original cue IDs, order and all
millisecond timestamps match. No blank or missing cues, extra credit/watermark
cues, model labels or advertising were added.

## Usage and timing

| Measurement | Result |
| --- | --- |
| Model/effort | gpt-6-luna / medium |
| Completion cap/tier | 32768 / default |
| Paid completion requests | 39 |
| Input tokens | 134008 |
| Cached input tokens | 3550 |
| Cache-write tokens | 130341 |
| Completion/output tokens, including reasoning | 56335 |
| Reasoning tokens | 21739 |
| Actual usage cost at verified rates | USD 0.044507325 |
| Permanent worst-case reservations | USD 0.700823375 |
| Approved total ceiling | USD 1.50 |
| Queue-to-completion time, including extraction | 586.28 seconds (9m46s) |
| Sum of API call latencies | 486.79 seconds (8m07s) |
| Provider failures / ambiguous usage | 0 |
| Alignment repair attempts | 1 |

Cost uses standard short-context Luna rates: normal input0.10, cached0.01,
cache-write0.125 and output0.50 USD per million. Output includes reasoning; it
is not charged twice. Cache-write usage was exposed on every request. These
are provider usage charges, not a tax-inclusive invoice. Reservations are
conservative maximums, not actual charges. They remain in the original SQLite
ledger and were never refunded, reset or bypassed.

Pricing: https://developers.openai.com/api/docs/models/gpt-6-luna

## Validation findings and correction

One batch initially failed cue alignment and the existing engine repaired it
within the same guarded provider path. All final alignment checks passed.

Cue1043 contained translated Persian but a missing greater-than delimiter in
the opening italic tag. After pausing, the first pilot-generated subtitle was
preserved in private rollback storage; only that newly generated output was
quarantined. A deterministic formatting correction inserted the delimiter,
without changing dialogue, IDs or timing, then republished atomically with
no-overwrite semantics. No additional AI call was made for this correction.
Every final cue's HTML tags passed a structural check.

The reusable subtitle formatter now restores this known missing-delimiter
pattern BEFORE protecting tags during wrapping. A mocked end-to-end regression
test verifies readable Persian, paired italic tags and exact original cue timing.
All 156 tests and Ruff passed.

Two intentional Latin-only cues are retained faithfully: company brand Acme
(cue240) and the literal spelled-letter sequence A-R-E-Y (cue1373).
They are explicitly recorded as reviewed exceptions, not silently counted as
translated Persian dialogue. All other cues contain Persian-script text.
Human review of overall translation quality remains useful; automated checks
prove structure/alignment and sampled meaning, not every creative choice.

## Jellyfin proof

The selected 1080p item is 40016011-E644-EE8D-06BD-8340053E40E1.
The separate 2160p movie was not processed.
The live server reports Jellyfin12.2.0. Existing authenticated access worked
using the Authorization MediaBrowser header; the old X-Emby-Token probe returned
401. No API token was created or service authentication configuration changed.

Realtime monitoring discovered the sidecar automatically: external=true,
language=fas, codec=subrip, exact matching-basename path. The API served a
145879-byte UTF8 SRT. Its 1498 cue IDs, millisecond timestamps AND text exactly
match the final file on disk. No item or whole-library refresh was performed.
Beginning/middle/end dialogue was inspected from the served subtitle.

## Preservation and final state

The MKV's full SHA256 before/after is unchanged:
3a7818af2b6efd41a8069567efb8bc4c3c61449f995a3ed898dc04b9880c98de.
Size and modification time also match. All458 original SRT/ASS/SSA/VTT/SUB/IDX
files in Movies/Shows retained their hashes. The only added library subtitle
is the approved standard Persian sidecar.

All pre-existing Docker containers except the deliberately recreated development
backend retained their start times/restart counts during this pilot.
Production UST remains healthy v1.4.0 on2288. Sonarr/Radarr notification objects
and Bazarr YAML match fresh preflight backups. Legacy subs-translator remains
untouched/sleeping, with no invocation. No ownership changes were made.

Development is healthy on loopback2289 with hot reload and Luna Medium32768.
Automation is paused, original four-file fixture scope/mappings restored,
AUTOMATION_REAL_LIBRARY_PROCESSING=false, and UST_PILOT_BUDGET_FILE is unset.
The approved guard config and ledger remain archived; no other media was queued
or processed. Earlier queue rows are unchanged; the one pilot row remains done.

Private evidence, original generated subtitle and API usage records:
dev/runtime/data/coyote-pilot/.
Persistent cost ledger:
dev/runtime/data/final-integration-backup/approval-medium.json.sqlite.
None of these runtime files, translated media or credentials are committed.

## Next approval

Review the delivered movie subtitle in Jellyfin, then approve only the staged
production promotion in production-promotion.md. Preserve stack14, stopped-writer
data/environment backups and original rollback images; stage a non-root data
copy with secure production authentication and independent queue/budget/token.
Keep automation paused and live hooks unchanged during promotion acceptance.

After production acceptance, separately approve Radarr/Bazarr for ONE actual
new movie import, then Sonarr for ONE episode. Only after both real import tests
pass should event-only new-library scope and an approved daily ceiling expand.
This pilot proves real translation/publication/Jellyfin serving; it does not
claim that live download notifications or unrestricted automation are enabled.
