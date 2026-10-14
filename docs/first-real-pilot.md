# First real Persian subtitle pilot — prepared, NOT activated

Read-only preparation dated 2026-10-14. The private exact-file plan is
dev/runtime/pilot/plan.json on Prime, with rejected activation drafts beside it.
Do not commit that inventory or private credentials. No provider inference was
made. No file was created in either real library. Existing production 1.4.0,
legacy subs-translator, and all media hooks remain unchanged.

## Verified selection and source

117 Movies videos were inspected with FFprobe, including ALL subtitle streams
(text and bitmap), language tags and Persian/Farsi titles. Existing Persian
sidecars and embedded fa/fas/per tracks excluded a video regardless of forced
flags. The selected two movie directories contain only their original video.
Both directories are UID/GID 1000:1000 mode 0755; videos mode 0644.
Backend UID 1000 has write/traverse permission without a permissions change.
Jellyfin UID 112/GID 117 can traverse both directories. No library write probe
was performed. The underlying Movies mount is ZFS. Filesystem checks establish permission,
not a tested write.

The recommended film and alternative, exact host/container paths, durations,
English stream indexes, source checksums and complete-source checks are in the
private plan. Recommendation has 1,498 nonblank, positive-duration, uniquely
numbered cues; 38 batches using 40 cues/12,000 characters and two neighboring
cues bounded to 500 characters and 15-second gaps. Its English dialogue/credits
run from 00:00:36.871 to 01:42:35.859 in a 01:42:55.216 video.
Alternative has 1,479 valid cues, 37 batches, ending 01:44:39.083 in 01:47:53.056.
Both are ordinary non-forced, non-commentary English SubRip streams, with no
Persian sidecar or embedded Persian. Extraction occurred only in development
data/temp/pilot-inspection, never beside a real video. English provenance is
known and full-length coverage is plausible; audiovisual line-by-line alignment
and human quality remain pilot acceptance checks.

Scary Movie extended-cut sidecar was not approved as a candidate: its final cue
is over twelve minutes before video end. That may be credits, but this inspection
cannot establish an exact-cut full source. Do not silently use it as a pilot.

## Models and costs

Current configured app model remains gpt-4o-mini. Non-inference models.retrieve
succeeded for gpt-4o-mini, gpt-5.4-mini, gpt-5.6-terra and gpt-6-luna. This proves
metadata access, not inference success. All four document Chat Completions.
Official pricing/request sources are in benchmarks/models.json and
docs/persian-quality.md. No quality winner is claimed.

For the recommended movie, USD estimates (standard, short-context, no taxes):

| Model | Heuristic normal first pass | Conservative capped first pass |
| --- | --- | --- |
| gpt-4o-mini | 0.030–0.045 | 0.2591 |
| gpt-6-luna | 0.023–0.035 | 0.2159 |
| gpt-5.4-mini | 0.188–0.297 | 1.7622 |
| gpt-5.6-terra | 0.502–0.792 | 4.9399 |

Heuristic estimates use actual prompt characters/4 plus message overhead and
0.5–1 Persian output tokens per English dialogue character. They are not
tokenizer measurements or a quality guarantee. Capped bounds use actual full
UTF-8 prompt bytes plus 1,024 tokens/request overhead and 8,192 maximum output
tokens per request. They charge every input token at the highest recorded
input/cache-write rate (Luna 0.125; Terra 2.5 per million). No cache discount,
Batch/Flex discount, Fast tier, regional premium or >272K request is assumed.
They exclude retries. The total across requests may exceed 272K; each request
must independently remain below the short-context threshold.

Proposed separate approvals: blind benchmark maximum USD 1.20, then ONE movie
with gpt-6-luna maximum USD 0.50, total at most USD 1.70. If blinded quality or
first inference fails, pause; do not switch to a more expensive model without
a revised approval. A hard ceiling can stop a movie before completion.

## Spending guard (implemented, currently INACTIVE)

backend/app/services/pilot_budget.py is enabled only by UST_PILOT_BUDGET_FILE.
No such variable is configured now. It rejects unapproved or mismatched model
configuration, invalid limits, unpriced long requests and a nonofficial endpoint.
Each paid call reserves its full worst-case cost BEFORE submission, in a
transactional SQLite ledger next to its private approval JSON. Reservations
survive processes, queue retries and restarts, and are never refunded, even after
timeout/error. Configuration is pinned to that ledger. Do not delete the ledger,
raise its limit, create a new one or retry the whole pilot without new approval.

Guarded calls set service_tier=default, max_completion_tokens=8192, disable SDK
retries, and use reasoning_effort=none for Luna (no temperature). Normal manual
translation behavior is unchanged with the guard absent. All translation-engine
repair and language-validation calls use this same guarded provider path.
Manual provider calls also consume the same guard when installed: do not run
manual translations concurrently with the pilot. Requests already in flight
may bill after pause, but their maximum charge was reserved. Bounds depend on
the verified price contract; recheck rates before activation.

## Exact activation sequence — execute ONLY after specific approval

1. Record approved exact movie, model and separate benchmark/movie budgets.
   Recheck pricing/model metadata. Run the 96-request blind benchmark only under
   its separately approved 1.20 ceiling. Archive inputs, request parameters,
   hashes, scored reviewer sheets, usage and reservation/cost basis. Quality
   failure means STOP before the real movie.

2. On Prime checkout/main, confirm clean/preserved work, healthy ust-dev, healthy
   untouched production, and automation disabled. Save the existing dev
   automation configuration privately (contains its webhook token, chmod 0600).
   Back up only development SQLite using sqlite3.Connection.backup; never copy
   production app.db. Record all existing sidecar hashes and selected video
   size/mtime. Reprobe ALL subtitle streams and directory entries; abort if
   Persian subtitles appeared or source checksum changed. After approval, before
   any paid inference, test exclusive temporary creation, fsync and hard-link
   publication in the selected movie directory using hidden random probe names;
   immediately remove only those probe files. Abort on any failure. No probe
   was written during read-only preparation.

3. While paused, set selected_files to precisely the ONE container video path
   from dev/runtime/pilot/plan.json:
   automation.save_scope([approved_video_path]).
   Keep existing roots/mappings and token. No directory wildcards, second
   movie, Shows path, library scan scope, or webhook changes. Assert that the
   resulting allowed_files list contains exactly that one resolved path.

4. AFTER approval, turn approval.json.draft into an approved private JSON at
   dev/runtime/data/pilot/approval.json (chmod 0600), preserving its approved
   movie, source checksum, model, USD 0.50 ceiling, 8192 output limit and prices.
   Only then copy compose.override.yml.draft to compose.override.yml. Its
   backend-only override specifies real-library processing true, model Luna and
   /app/data/pilot/approval.json. Do not edit production/release Compose.

   From /home/afshin/projects/universal-subtitle-translator:
   ./dev/ust -f dev/runtime/pilot/compose.override.yml config -q
   ./dev/ust -f dev/runtime/pilot/compose.override.yml up -d --no-deps backend

   This recreates ONLY the development backend. Source bind mounts, hot reload,
   frontend localhost:2289, development data and internal gateway stay separate.
   Do not log a full Compose rendering: it contains environment secrets.

5. Verify backend health, guard file/config, model, disabled automation, scope
   length one and exact path. Reconcile while paused:
   POST /automation/scan through an authenticated localhost:2289 session
   (or automation.reconcile() inside the dev backend).
   Require discovered=1 and one unique queue row for that exact file. Enabling
   real_library_processing alone must never imply enabling the worker.
   Enable the saved config only after these assertions; the existing persistent
   worker then executes the queued movie. Monitor /automation/status, the job
   UI and the persistent cost ledger. Sonarr/Radarr/Bazarr gateway routes remain
   authenticated but unused. No event from those services is needed.

6. Pause immediately on completion/failure, cap exhaustion, wrong path/model,
   malformed output or unexpected competing activity: POST /automation/pause.
   Pause persists and checks between batches and before publication. As a hard
   stop, ./dev/ust stop backend events affects development only.
   Do not reset queue attempts or cost reservations automatically.

7. Require exactly one new <video-basename>.fa.srt. Check UTF-8, every source cue
   ID/order and exact millisecond timestamps, unchanged cue count (1,498 for the
   recommendation), no blanks, complete Persian-script dialogue, no invented
   watermark cues, valid markup and natural-language spot checks at beginning,
   middle and end. Read back from disk. Check original video size/mtime and all
   existing sidecar hashes unchanged. Publication uses atomic non-overwrite
   semantics; a competing existing subtitle must cause refusal, not replacement.

8. Return to the base dev configuration and original paused fixture scope:
   ./dev/ust up -d --no-deps backend
   Restore saved automation scope/settings with enabled=false. Confirm
   AUTOMATION_REAL_LIBRARY_PROCESSING=false, default model restored and no
   active budget variable. Retain private ledger/evidence. Keep the new subtitle
   only if pilot acceptance succeeds. Development remains available on 2289.

## Jellyfin recognition and playback

Native Jellyfin 10.11.11 at http://192.168.0.100:8096 is reachable read-only.
Its Movies options.xml points to /tank/share/Media/Movies, real-time monitoring
true. Capitalized and lowercase Movies paths refer to the same physical library.
A new matching-basename .fa.srt is the official external-subtitle naming scheme:
https://jellyfin.org/docs/general/server/media/movies/#external-subtitles-and-audio-tracks

After output validation, wait up to two minutes for monitoring and open the
exact movie in an authenticated Jellyfin browser session. Verify the external
Persian subtitle in Media Info and player selector, then display it at three
sample timestamps. Evidence must include recognized language (fa/fas/per),
external=true, SubRip codec, exact sidecar path and correctly displayed RTL text.
Existence on disk does NOT establish Jellyfin discovery.

If not discovered, refresh ONLY that item, without replacing metadata/images.
Prime's served OpenAPI was inspected for:
POST /Items/{itemId}/Refresh?metadataRefreshMode=ValidationOnly&imageRefreshMode=None&replaceAllMetadata=false&replaceAllImages=false&regenerateTrickplay=false
Then inspect its MediaStreams again with an authenticated GET.
There is no Recursive parameter on this installed version. Do not perform a
whole-library refresh, configure a webhook, or change library paths.
No authenticated Jellyfin API session/token was supplied to this agent; use the
existing browser session or arrange dedicated authorized read/refresh access.
No refresh was sent during preparation.

## Rollback and later milestones

Pause and restore the false real-processing gate and original fixture scope
first. Preserve cost ledger even if translation failed. If the ONE new sidecar
must be rolled back, require its recorded path/hash to match the pilot output,
then move that file only to private development quarantine. Never touch original
English, pre-existing Persian, embedded subtitles, video ownership or production
data. Refresh only that Jellyfin item if required after rollback.

Legacy subs-translator remains asleep/manual; no new concurrent legacy run may
be initiated. Broken Radarr CustomScript and Bazarr post-processing are unchanged.
After the movie and Jellyfin checks pass, obtain separate approval to disable
the broken legacy Radarr hook and enable the new Radarr/Bazarr integration,
then Sonarr. This pilot is independent of those later event-delivery milestones.
