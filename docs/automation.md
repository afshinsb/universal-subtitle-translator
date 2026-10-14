# Automatic English-to-Persian subtitle pipeline

Development is on main, tracking origin/main, in
/home/afshin/projects/universal-subtitle-translator on Prime.
Commit 22415a8 and its parent history are preserved on main.
Atlas Codex works through SSH. Docker environment isolation remains independent
of Git branching: use ./dev/ust, port 2289, and development storage exclusively.

## Behavior

Authenticated console: http://localhost:2289/automation.
It is available from Account -> Automation. Status, queue, attempt counts,
errors, job links and retry controls are shown. Processing starts paused.
Library roots, path mappings and the enabled/paused setting persist in SQLite.
An integration token is generated in the development database and visible
only in the authenticated console; do not commit or share it.

The backend lifespan runs one polling worker. When enabled it reconciles
configured libraries once per minute, recovering missed import events.
Sonarr and Radarr import notifications queue the specific video immediately.
Bazarr completion events wake waiting videos; periodic rechecks also find
English subtitles that arrive without a completion event.

Rows are unique by resolved media path. SQLite immediate transactions make
event insertion and worker claiming safe against duplicates/concurrent workers.
A 90-second lease is renewed every 15 seconds. Expired running leases are
recovered after a process crash; stale owners cannot update a replacement claim.
A lease check precedes atomic, non-overwriting output publication.
Provider calls may repeat after a crash: delivery is at least once, while
completed subtitle files are preserved. Pending jobs survive SQLite reopen,
hot reload and container restart.

Waiting for missing media, English subtitles, writable storage or provider
configuration does not consume translation retries. Actual processing failures
use exponential backoff (30s, 60s, 120s, 240s...) and stop after five failures.
Retry controls reset a failed/waiting item's attempts. Completed/skipped/running
items cannot be forcibly retried or overwritten.

Source selection prefers complete English sidecar SRT files, with ordinary
dialogue preferred over HI/SDH/CC variants. Forced/commentary sidecars are
excluded. If no sidecar is available, English text tracks are selected;
forced/commentary and foreign tracks are excluded, non-HI preferred.
Bitmap subtitles/OCR are out of scope. Extracted source goes into application
temporary storage, never beside a real video.

Translation uses the existing engine, including its block-alignment validation,
missing-cue repair and Persian-script checks. Two preceding/following source
cues provide bounded reference context, including across batch boundaries.
The prompt requests contemporary Iranian Persian, idiomatic dialogue and
consistent character voice, without adding neighboring dialogue to a cue.
Exact source IDs and timestamps are preserved for automation output.
Automation adds no extra watermark cues. Manual outputs retain their existing
watermark behavior, styles and routes.

Development is fixture-only by default. The user subsequently authorized\nreal-library access: AUTOMATION_ALLOW_LIBRARY_WRITES=true in dev/compose.yml\nallows configured /media/movies and /media/shows roots. Automation stays paused.
When no key is configured, normal processing stops at waiting_config before
any provider request. The development key is now configured, but automation
remains paused. A mocked provider exists only within verification processes.

## Event adapters

Sonarr:
POST /automation/hooks/sonarr
Accepts Download/EpisodeFileImport/Rename with episodeFile.path or
episodeFiles[].path. Test acknowledges without queueing.

Radarr:
POST /automation/hooks/radarr
Accepts Download/MovieFileImport/Rename with movieFile.path or
movieFiles[].path. Test acknowledges without queueing.

All webhook calls require the dedicated integration token, either through
X-Automation-Key or HTTP Basic username automation/password <integration token>.
Existing application session credentials are separate.
Unsupported events are ignored; missing/invalid/outside-root paths return 422.
All paths in a multi-file event are checked before any item is accepted.
Request bodies are bounded to 64 KiB.

Bazarr:
POST /automation/hooks/bazarr
Canonical payload: eventType=SubtitleDownloaded, video_path=<full media path>,
language=en. Non-English completions are ignored.
This is our adapter payload, not a claim that Bazarr emits that native schema.

scripts/automation_event.py is a standalone stdlib relay for future service
integration. It reads Sonarr/Radarr custom-script environment variables or
Bazarr arguments, normalizes en:hi/en.hi, uses a private token file/environment,
and retries failed event delivery. Reconciliation covers missed notifications.
The relay is present in the checkout only; it was not installed in any service
or in /opt/containers/subtitle-scripts.

Future Bazarr command template (do not enable without explicit authorization):

~~~sh
python3 /approved/scripts/automation_event.py --service bazarr --video "{episode}" --language "{subtitles_language_code2}"
~~~

Provide UST_AUTOMATION_URL and UST_AUTOMATION_TOKEN_FILE securely.
Bazarr's {episode} variable is the full episode/movie path.
Path mappings translate complete source directory prefixes to backend roots.
Simulated events used fixture paths. Current mappings include /movies to
/media/movies, /tv and /shows to /media/shows, and equivalent host media paths.

Primary payload/variable references:
- Sonarr source: https://github.com/Sonarr/Sonarr/blob/develop/src/NzbDrone.Core/Notifications/Webhook/WebhookImportPayload.cs
- Radarr source: https://github.com/Radarr/Radarr/blob/develop/src/NzbDrone.Core/Notifications/Webhook/WebhookImportPayload.cs
- Bazarr post-processing: https://wiki.bazarr.media/Additional-Configuration/Settings/Subtitles/#custom-post-processing

## Existing subs-translator reference

Read-only inspection of /opt/containers/subtitle-scripts/auto_fa_on_import.py
established proven sidecar-first English selection, non-SDH preference,
embedded extraction, provider retries, block parsing, RTL wrapping and
repair of missing Persian cues. These policies were adapted into the app's
existing stronger SRT parser and alignment-repair engine rather than importing
the script's provider client or service configuration.

No legacy script, service, API key, mount, permissions or hook was changed.

## Verification

The full regression suite plus automation tests runs in a disposable,
credential-free container with networking disabled. Test tooling is installed
separately under dev/runtime/test-tools, never in the running app image.
The Python dependencies/Dockerfiles/Compose configuration did not change.

Covered: delayed English/Bazarr wakeup, duplicate imports, concurrent insertion,
exclusive claims, expired leases and stale ownership, retry backoff/exhaustion,
malformed provider alignment without partial output, manual retry, paused state,
missed-event reconciliation, English selection, forced/commentary exclusion,
path mapping/traversal/symlink boundaries, development-only roots, hook/session
authentication, payload-size limits, multi-file atomic validation, UI visibility,
context presence, exact IDs/timestamps, and existing output preservation.
Existing manual upload/download and subtitle tests remain in the full suite.

Retained live demonstration:

~~~sh
docker exec -e OPENAI_API_KEY= -i ust-dev-backend python - prepare < dev/verify_automation.py
./dev/ust restart backend
./dev/ust up -d --wait
docker exec -e OPENAI_API_KEY= -i ust-dev-backend python - complete < dev/verify_automation.py
~~~

Run with automation paused. The script generates a new writable fixture
directory, sends simulated HTTP import events to the real dev backend,
persists a waiting item across restart, sends the Bazarr completion event,
and injects an in-memory provider only into the verification process.
It also verifies actual FFmpeg embedded extraction and duplicate preservation.
No paid provider requests occur; service settings and dev env remain unchanged.
Fixture results and completed queue rows remain visible for review.

Private evidence: dev/runtime/evidence/automation-tests.log,
automation-prepare.json and automation-complete.json.

## Before controlled production integration

1. Review real payload samples and path mappings; establish an internal service
   route to the chosen translator endpoint. The development listener remains
   loopback-only; service containers have not been attached to its network.
2. Approve and configure a provider/model and a small paid quality evaluation.
   Mock tests validate mechanics, not actual translation quality.
3. Library write access is now authorized and verified. Review output policy, existing Persian subtitles
   and production backup/data migration for the non-root application.
4. Enable one approved hook/library at a time, verify behavior, then expand.
   No Sonarr/Radarr/Bazarr hook or production deployment has been enabled.

Existing .fa.srt files are never automatically repaired or replaced, including
after media upgrades. Review stale/incomplete files manually before removing
or replacing them. The legacy repair policy informs cue-repair inside fresh
translation, not destructive repair of existing library subtitles.
Untagged English tracks, OCR, subtitles stored in separate Bazarr directories,
rename-history linkage and service API polling require further integration work.
Current import detection uses webhooks plus mounted-library reconciliation.
Large-library scan performance requires controlled measurement before enabling.

Rollback: pause Automation first, revert the feature commit, then let hot reload
restart the app. Added SQLite tables can remain; manual data is unaffected.
Production stays unchanged on port 2288.

Provider configuration update: dev/compose.yml now honors the key and upload
limits in dev/.env. Model, style and SRT batch settings also come from that
file. Automation remains paused. Startup checks model access; agent-run tests
clear the provider key and use mocks, with no paid inference requests.

Media access update: Movies and Shows now have authorized read/write bind\nmounts. All 162 library directories were writable by afshin, and all files\nwere readable. No host ownership/permission changes were required.\nHooks remain disabled; no paid translation is authorized by this access change.\n