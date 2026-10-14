# Final automatic media integration — controlled pilot complete, hooks inactive

The approved single-movie pilot is complete. See [coyote-pilot-results.md](coyote-pilot-results.md).
Production promotion and live hook activation remain separately gated.

Prepared on Prime, 2026-10-14. Development uses main, GPT-6 Luna Medium,
32768 completion tokens, source hot reload and loopback port 2289.
Production 1.4.0 on 2288 is independent. No comparisons or paid calls were run.

## Verified live connections

Seerr's default Sonarr and Radarr targets are 192.168.0.100:8989 and :7878.
Both download clients use qBittorrent at 192.168.0.100:8080; categories are
tv-sonarr and radarr. Downloads share /tank/share/downloads. No upstream
configuration change is needed for this preparation.

Sonarr 4.0.19.2979 sees Shows as /tv, with no notification connections.
Radarr 6.3.0.10514 sees Movies as /movies. Custom Script connection ID 1 is
enabled on download, but /scripts/run_fa_subs.sh is absent. Do not repair that
script: it would revive a competing writer. Before replacement notifications
are activated, disable ID 1 by updating its saved notification object with
onDownload/onUpgrade/onRename and all other event switches false. Preserve
all fields and ID; do not delete it. Confirm disabled before adding UST.
Restore the exact saved object on rollback; its original script remains broken.

Bazarr uses /movies and /tv; use_sonarr/use_radarr are true. Its eng language
profile requests ordinary English and excludes HI/SDH/Hearing labels.
Post-processing remains disabled and its command is empty. Verify that new
Radarr movies and Sonarr series inherit profile eng when activating; assigning
a profile to a historical library or launching a bulk subtitle search is excluded.

subs-translator still runs sleep infinity. Its media mounts remain writable.
No references were found in inspected cron/systemd files. The missing Radarr
wrapper, disabled Bazarr processing and absence of schedules prevent current
automatic legacy invocation; they cannot prevent someone manually invoking
/opt/containers/subtitle-scripts/run_fa_subs_host.sh. Leave the service untouched
and do not invoke it for any UST-owned media.

Service configuration/notification/schema/download-client snapshots and the
Portainer stack 14 Compose definition are private, mode 0600, under:
dev/runtime/final-integration/20261014T195043Z.
The directory is mode 0700. It includes container/image/environment snapshots
and Persian sidecar checksums. Development SQLite and automation settings were
backed up under dev/runtime/data/final-integration-backup.
These contain credentials: never publish or commit them.

## Internal delivery and paths

The existing ust-dev-events gateway has no published ports. It joins
sonarr_default, radarr_default and bazarr_default, with alias ust-events.
Development URLs are:
- http://ust-events/automation/hooks/radarr
- http://ust-events/automation/hooks/sonarr
- http://ust-events/automation/hooks/bazarr

Only authenticated POST hooks are proxied. Other UI/API routes are blocked.
Sonarr/Radarr use HTTP Basic username automation, password the dedicated
development integration token from the authenticated UST automation console.
The relay uses X-Automation-Key. Never put tokens in URLs, Git or shell arguments.

Mappings: /movies -> /media/movies; /tv and /shows -> /media/shows.
Host paths are /tank/share/media/movies and /tank/share/media/shows.
UST runs UID/GID 1000:1000. Existing permissions are sufficient; no library-wide
ownership or permission change is required.

After production promotion use a SEPARATE gateway alias ust-prod-events,
same three hook paths, its own network, and a NEW production integration token.
Never point live unrestricted hooks at the development gateway.

After hook approval, install only these new files:
- /opt/containers/subtitle-scripts/ust/automation_event.py
- /opt/containers/subtitle-scripts/ust/event.token (mode 0600, service-readable)
Inside Bazarr they are /scripts/ust/automation_event.py and event.token.
Copy the relay from the reviewed release; copy no development provider secret.

Bazarr production post-processing command:
~~~sh
python3 /scripts/ust/automation_event.py --service bazarr --url http://ust-prod-events --token-file /scripts/ust/event.token --video "{episode}" --language "{subtitles_language_code2}"
~~~
For a separately approved development event test use http://ust-events instead.
Bazarr's episode variable also identifies a movie. Preserve previous thresholds;
currently threshold checks are disabled. The relay ignores non-English events,
normalizes en:hi/en.hi, retries temporary delivery errors and returns nonzero
on failed delivery. HI selection policy in UST remains unchanged.

Radarr and Sonarr Webhook connections: method POST, username automation,
dedicated token as password. Enable On Import/Download and Upgrade; optional
Rename is supported. Keep unrelated notification types disabled. Test events
return success without enqueuing files. Sonarr episodeFile and episodeFiles
payloads, multi-episode videos, repeated imports and Bazarr completion reuse
persistent queue IDs.

## Safeguards implemented in this increment

- Pilot reasoning none/low/medium/high/xhigh/max and up to 128000 completion
  tokens are validated BEFORE reservation. Luna Medium uses 32768, no temperature.
- Scoped pilot requests must match the approved exact video and English SHA256.
  Manual/unrelated requests cannot consume the scoped pilot budget.
- Pilot SQLite reservations persist across repairs, retries and restarts.
  SDK retries are disabled. Failed/uncertain calls retain their full reservations.
- Optional OPENAI_DAILY_BUDGET_USD guards all normal provider calls and repairs.
  Configure positive conservative input/output rates and a completion cap.
  Standard tier is enforced; long-context and nonofficial endpoints are rejected.
  No hidden retry can escape accounting. Daily counts reset by UTC date only;
  ledger history is retained, never deleted/reset. Configuration is sealed.
- Daily exhaustion becomes waiting_budget until next UTC day, without consuming
  queue retry attempts. Usage records include exposed reasoning tokens, already
  included within completion/output tokens. Reservations are conservative caps,
  not a claim of actual invoice cost. They are never refunded for cheaper calls.
- Automation has one active leased translation across worker processes.
- events_only discovery never walks historical libraries. Bazarr wakes known
  imported queue rows; it does not seed historical media. English arriving before
  import is found from disk when the import later arrives.
- Selected-file reconciliation remains available for the exact pilot.
  Missing/delayed English stays pending; missed import webhooks in event-only mode
  require targeted re-delivery/reconciliation. There is intentionally no bulk
  fallback that would translate history.
- Existing SRT/ASS/SSA/VTT/SUB/IDX Persian sidecars and text/bitmap embedded
  Persian tracks are preserved, including language-unknown Persian title tags.
  The writer rechecks competing sidecars/media changes before publication.
- Authenticated automation UI displays spending reservations, reasoning tokens,
  failed/waiting-budget alerts, queue details and retry controls.
  External failure notifications are not configured; the UI is the current alert.

## Approval 1: ONE Coyote vs. Acme movie, no live hooks

Exact container video:
~~~text
/media/movies/Coyote vs. Acme (2026)/Coyote vs Acme 2026 1080p AMZN WEB-DL DDP5 1 Atmos H 264-BYNDR.mkv
~~~
Host equivalent starts /tank/share/media/movies/.
Duration 01:42:55.216. Ordinary embedded English SubRip stream 2, 1498 valid cues,
38 batches of 40/12000 with existing two-cue context. Stream 3 is SDH and is not
selected. English SHA256:
7393d3129a901c689cae6370108a29e48988c2bb960024ac34c839753c88747d.
No Persian sidecar or embedded Persian stream appeared at reinspection.
Directory UID/GID 1000:1000, writable/traversable without chmod/chown.

Model gpt-6-luna, reasoning medium, max_completion_tokens 32768, standard tier.
Official short-context input/cache-write/output rates are 0.10/0.125/0.50 USD per
million; reservations charge ALL input at 0.125 and ALL capped output at 0.50.
The actual engine's 38 first-pass prompts have 481710 total conservative input
tokens (UTF8 bytes plus 1024 overhead each); largest request 14918.
First-pass worst-case reservation: USD 0.68280575. Expected actual usage cost
approximately USD 0.04–0.08 based on the completed episode's measured Medium
usage, a heuristic only. Proposed HARD TOTAL: USD 1.50 including all repairs,
retries and restarts. Exhaustion stops requests even if the subtitle is incomplete.
This is NEW approval; the episode comparison ledger/budget is unrelated.

Inactive drafts:
- dev/runtime/data/final-integration-backup/approval-medium.json.draft (approved=false)
- dev/runtime/final-integration/20261014T195043Z/pilot.override.yml.draft

After explicit approval:
1. Pause UST; take a fresh development SQLite/config backup and recheck the exact
   video's signature, all English/Persian sources and source SHA256. Abort if
   Persian exists or the source changed. Do not invoke legacy scripts.
2. Apply selected_files with ONLY the exact container video above. Assert one
   resolved file. Keep hooks unchanged. No library scan outside selected scope.
3. Create the approved private approval-medium.json from its draft, setting
   approved=true ONLY after approval. Do not change movie/model/rates/cap/limit.
   Keep it mode 0600. Its .sqlite ledger must never be removed/reset.
4. Copy pilot.override.yml.draft to pilot.override.yml only after approval, then:
~~~sh
./dev/ust -f dev/runtime/final-integration/20261014T195043Z/pilot.override.yml config -q
./dev/ust -f dev/runtime/final-integration/20261014T195043Z/pilot.override.yml up -d --no-deps backend
~~~
   This changes ONLY dev backend gate/model/guard. Keep daily guard off for this
   separate, total-capped pilot. Confirm healthy, paused, scope one, Medium/32768
   and active approved guard. Never print a full rendered Compose configuration.
5. Reconcile selected file while paused; assert discovered=1, one unique queue
   row. Enable the worker only after those assertions. The known English stream
   is extracted solely in development temporary storage.
6. Monitor queue/job logs and ledger. Abort/pause on scope/model errors, competing
   writers, budget exhaustion or invalid output. Atomic staging in this one
   directory publishes only the standard basename.fa.srt, without overwrite.
7. Pause on completion. Validate 1498 cue IDs/order/exact millisecond timestamps,
   no blanks/missing/duplicated dialogue, valid UTF8/Persian and unchanged
   original source/media/other subtitle evidence. Human spot-check dialogue.
8. Jellyfin's exact 1080p item is 40016011-E644-EE8D-06BD-8340053E40E1, NOT the
   separate 2160p Coyote item. Wait for realtime monitoring, authenticated GET
   this item's MediaStreams and fetch/display its external Persian SRT at three
   timestamps. If monitoring fails, approve an item-only validation refresh;
   never refresh the whole library. Episode sidecar discovery already succeeded.
9. Return to base dev Compose with ./dev/ust up -d --no-deps backend; restore the
   saved fixture scope/mappings with enabled=false. Confirm real-processing=false,
   no active pilot budget variable, Luna Medium unchanged. Keep ledger/evidence.
10. Rollback, if needed: pause first; check the exact new sidecar's recorded hash
    and quarantine only that pilot-created file in private development storage.
    Never delete/rewrite original English, pre-existing Persian, or the video.

Pause: POST /automation/pause through an authenticated same-origin session or
the UI. It persists pause, requests job cancellation and blocks subsequent
batches/publication. An already submitted request may bill but is reserved.
Hard stop development only: ./dev/ust stop backend events.

## Approvals 2 and 3: production promotion, then staged hook activation

See production-promotion.md for the separate production approval.
Production has its OWN provider credentials, secure authentication, SQLite,
queue, budget ledger and event gateway. Development stays on 2289.

After promotion is accepted, with automation still paused:
1. Set production discovery_mode=events_only, exact scope to ONE approved newly
   imported movie, daily ceiling (proposed USD 5/day, separately approved), Luna
   Medium/32768 and one automatic translation. Start with an empty production queue.
2. Disable broken Radarr CustomScript ID 1 and verify it cannot execute. Add only
   the replacement Radarr Webhook to ust-prod-events, test authentication.
3. Enable Bazarr English-completion relay after backing up YAML and thresholds.
   Verify a real Radarr import, delayed-English completion if applicable, UST
   queue, validated new .fa.srt and exact Jellyfin movie discovery.
4. Add Sonarr Webhook, expand exact scope to ONE approved new episode only, and
   verify an actual episode import and Jellyfin discovery, including multi-episode
   payload handling. Do not batch-submit historical shows.
5. Only after both real imports pass and another approval, change scope to
   approved libraries, keeping events_only. The scope UI requires event-only discovery and pauses on
   expansion; review before enabling. Test rejecting a historical Bazarr
   completion and demonstrate that reconciliation discovers zero historical files.
6. Roll back any step by pausing production UST and restoring only that service's
   saved notification/YAML. Do not reactivate/repair legacy scripts automatically.
   Keep produced valid Persian and durable ledgers.

## Verification and limits

Real gateway tests used all three installed service networks with simulated
events, wrong/missing authentication, denied dashboard access, multi-file and
duplicate imports, delayed English across a backend restart, failed relay
delivery and a transient mocked provider error. Fixture result: three completed
outputs, one preserved Persian file; no paid requests or real-library writes.
The original paused fixture scope/mappings were restored afterward.

A read-only base snapshot of the production database was migrated ONLY in an
isolated copy: 2 jobs, 6 logs, batch/sequence tables preserved; SQLite integrity
passed and the new automation queue was empty/paused. This rehearsal is NOT
the final live-data backup: cutover requires a stopped-writer, complete backup
including any WAL and all directories/environment.

QBit version probe returns 403 without authentication, as expected. Other
service read probes returned 200. No actual new download/import was requested.
External alert delivery, real pilot publication, actual hook configuration and
production cutover remain approval-gated.

Official sources:
- https://developers.openai.com/api/docs/models/gpt-6-luna
- https://developers.openai.com/api/docs/guides/reasoning
- https://wiki.bazarr.media/Additional-Configuration/Settings/Subtitles/#custom-post-processing

Final checks: 154 tests and Ruff passed; Linux Docker mocked-provider smoke and
reversible Python/template/static reload checks passed. All 103 pre-existing
Persian sidecar hashes were unchanged. Sonarr/Radarr notification objects and
Bazarr YAML remained identical to their snapshots. Production 1.4.0 containers
and subs-translator retained their original start times and zero restarts.

One external change was detected: Seerr was recreated at 20:03:48 UTC from
v3.4.1 to v3.5.0 while this work was in progress. No UST command targeted Seerr.
It is healthy, with unchanged mounts/network. The old and new settings snapshots
are retained privately. Do not claim every pre-existing container was unchanged.
Development backend alone was deliberately restarted for the pending-job test.
