# Prime real-media integration preparation

Prepared on 2026-10-14 in /home/afshin/projects/universal-subtitle-translator,
main tracking origin/main. Initial source was 171175b, which already preserved
6a44ede and 22415a8. No production translator deployment is part of this work.

## Verified installed state

| Service | Verified version/network | Media seen inside service | Existing notification state |
| --- | --- | --- | --- |
| Sonarr | 4.0.19.2979 / sonarr_default | /tv | GET /api/v3/notification returned an empty list |
| Radarr | 6.3.0.10514 / radarr_default | /movies | Custom Script ID 1 enabled for Download only; path /scripts/run_fa_subs.sh is missing |
| Bazarr | authenticated system-status API reachable / bazarr_default | /tv and /movies | use_postprocessing=false |
| Jellyfin | native systemd service 10.11.11, UID 112 / GID 117 | host library paths | Public info GET succeeds; /Library/VirtualFolders requires a token (401) |
| subs-translator | subtitle-tools_default | /movies and /shows | sleep infinity; host wrapper can explicitly invoke auto_fa_on_import.py |

Host Movies: /tank/share/media/movies. Host Shows: /tank/share/media/shows.
Sonarr/Radarr/Bazarr configuration directories are /opt/containers/<service>/config.
The shared /scripts mount comes from /opt/containers/subtitle-scripts.
No service config or shared script was edited. Do not create the missing Radarr
run_fa_subs.sh wrapper: repairing it would revive the legacy writer.

The app runs UID/GID 1000:1000, matching afshin. Earlier permission audit found
all 162 library directories writable and all files readable. This preparation
did not chmod/chown, create probes or write subtitle files in either real library.
Existing write-enabled development mounts remain as previously authorized.
Read-only checks hashed 5 movie and 92 show Persian sidecars for preservation.

Jellyfin is a consumer of sidecars, not an import-event producer for this
pipeline. Read-only options.xml inspection verified EnableRealtimeMonitor=true
for Movies at /tank/share/Media/Movies and Shows at /tank/share/Media/Shows.
os.path.samefile verified that both capitalized paths identify the same
directories as the lower-case service mounts; no path repair is needed.
Verify actual sidecar discovery during the pilot, or perform an explicitly
approved library refresh afterward.
No authenticated Jellyfin library API configuration was inspected or changed;
provide a dedicated API token only if an API refresh is chosen. No refresh
POST or playback operation was performed here.

## Internal event route

~~~mermaid
flowchart LR
  S[Sonarr network] --> G[ust-dev-events / ust-events:80]
  R[Radarr network] --> G
  B[Bazarr network] --> G
  G -->|POST import endpoints only| U[UST backend:2288]
  U --> Q[SQLite queue and selected files]
  Q --> F[Writable fixture sidecars]
~~~

Container ust-dev-events runs the already-built development Nginx image.
It joins ust-dev_default plus the three existing service networks, with
alias ust-events on each service network. Existing service containers were
not attached to a new network, restarted or reconfigured. There are no gateway
host port bindings. Port 2289 remains bound to Prime loopback for the UI.

Internal URLs:
- http://ust-events/automation/hooks/sonarr
- http://ust-events/automation/hooks/radarr
- http://ust-events/automation/hooks/bazarr

Only POST requests to those paths are proxied. The internal /health endpoint
is a gateway health check. Dashboard/settings/login/other paths return 404;
import GETs are denied. Body limit is 64 KiB. Access logging is disabled to
avoid accidental credential-bearing logs. Token authentication is enforced by
UST, using X-Automation-Key or HTTP Basic username automation / token password.
This is HTTP on trusted Docker bridge networks, not transport encryption.
It is not a public listener and does not bypass API authentication.

The token is generated/persisted in development SQLite and shown only to the
signed-in operator on /automation. It is separate from the OpenAI API key,
service API keys and login password. Never put it in Git, URLs, CLI arguments
or relay source. Prefer a mode-0600 token file readable by UID 1000.

For future Bazarr activation, provision the relay and token only AFTER approval:
- Host relay: /opt/containers/subtitle-scripts/ust/automation_event.py
- Host token: /opt/containers/subtitle-scripts/ust/event.token
- Bazarr-visible equivalents: /scripts/ust/automation_event.py and /scripts/ust/event.token
These files have NOT been installed in the shared service scripts directory.

## Media path translation

Persisted mappings include:
| Event path prefix | UST destination |
| --- | --- |
| /movies | /media/movies |
| /tv | /media/shows |
| /shows | /media/shows |
| /tank/share/media/movies | /media/movies |
| /tank/share/media/shows | /media/shows |

Longest complete directory prefix wins; partial prefix/traversal/symlink escapes
are rejected by root validation. Fixture-specific /movies/ust-fixtures and
/tv/ust-fixtures mappings point only into the retained fixture library.
The exact selected-file allowlist contains those fixture videos only.

AUTOMATION_ALLOW_LIBRARY_WRITES=true retains prior permission authorization.
AUTOMATION_REAL_LIBRARY_PROCESSING=false separately blocks real-library queue
insertion/claim/processing even if the operator enables the worker.
Automation remains paused. Excluded service events are acknowledged as ignored
rather than failing or enqueueing the rest of a library.

Scope mode selected_files is persistent. It supports up to 50 exact video paths;
an empty selection permits no files. Existing outside-scope queue rows remain
pending and cannot starve the selected movie. Reconciliation checks only selected
files; it does not walk whole libraries in this mode.

## Realistic verification

Retained fixture root: /media/fixtures/integration-5f713264.
It contains a valid FFV1 Matroska movie with English/forced subtitle tracks,
three valid Matroska episodes, English SRT sidecars and an existing Persian SRT.

Sequence verified:
1. Disposable probes attached to sonarr_default/radarr_default/bazarr_default
   used the real gateway and relay with simulated events.
2. Movie import selected the full embedded English track, avoiding forced text.
3. Multi-file episode import selected external English for episode 1.
4. Episode 2 waited without consuming retries when English was absent.
5. Episode 3 preserved its existing Persian subtitle, verified by hash.
6. Backend restart retained the pending episode.
7. English arrived; Bazarr completion from bazarr_default reused the queue ID.
8. A mocked temporary provider error caused a persistent retry and no partial file.
9. The next mock attempt published valid Persian beside the episode.
10. Repeated and multi-episode events reused IDs; completed files were unchanged.

Result: 3 done, 1 skipped; no paid requests. Each fresh output has the same
dialogue timing and exact source IDs (embedded IDs follow FFmpeg extraction).
Authentication rejects missing/wrong tokens, UI routes are blocked, and the
gateway has no host bindings. Relay delivery recovered after two simulated
HTTP 503s; permanent connection failure returned an error. Periodic selected-
file reconciliation is the fallback for missed notifications.

Reproduce with the worker paused; these commands clear the provider key:

~~~sh
docker exec -e OPENAI_API_KEY= -i ust-dev-backend python - prepare < dev/verify_realistic.py
python3 dev/verify_network_events.py imports
docker exec -e OPENAI_API_KEY= -i ust-dev-backend python - wait < dev/verify_realistic.py
./dev/ust restart backend
./dev/ust up -d --wait
docker exec -e OPENAI_API_KEY= -i ust-dev-backend python - subtitle < dev/verify_realistic.py
python3 dev/verify_network_events.py completion
docker exec -e OPENAI_API_KEY= -i ust-dev-backend python - finish < dev/verify_realistic.py
python3 dev/verify_network_events.py duplicates
~~~

The prepare phase deliberately replaces only the selected-file fixture scope
and adds specific fixture mappings; real mappings, credentials and media remain
unchanged. Older fixture-only scripts may require resetting selected scope to
their newly generated paths. Never clear the scope to unrestricted libraries.

## Exact controlled activation steps — requires separate approval

1. Choose ONE exact movie path, e.g. /media/movies/<title>/<video>.mkv.
   Inspect English availability, matching video timing and existing Persian.
   Existing .fa.srt is never overwritten; if it exists, choose another test movie.
   Do not delete/repair existing Persian to force a test.
2. Snapshot current UST config and service notification/post-processing settings
   into private rollback artifacts; obtain a backup of the selected folder.
3. Confirm exclusive ownership of translation for that movie:
   Radarr legacy Custom Script ID 1 must be disabled before enabling the new
   webhook. Keep subs-translator asleep and do not invoke its host wrapper for
   the pilot. Read-only inspection of 37 cron/systemd configuration files found no legacy
   references; afshin's crontab also has none. Recheck at activation. UST's own deduplication cannot prevent
   an independently invoked legacy script from repairing/replacing its output.
4. On /automation, enter ONLY the exact movie in selected-file scope and apply.
   Keep enabled unchecked. Roots may stay /media/movies, /media/shows and fixtures
   because the file allowlist limits reconciliation/claims/events.
5. Only after approval, change AUTOMATION_REAL_LIBRARY_PROCESSING to true in
   dev/compose.yml and recreate ust-dev-backend. Do not change mount permissions.
   The gate is currently false and has not been activated.
6. Configure Radarr Settings -> Connect -> Webhook:
   Name UST controlled pilot; URL http://ust-events/automation/hooks/radarr;
   Method POST; Username automation; Password integration token.
   On Import/Download = enabled, On Upgrade = enabled, On Rename = enabled;
   all unrelated events off. The installed schema confirms fields url, method,
   username, password and headers. Test sends eventType=Test and does not enqueue.
   Save only after approval. Other movies are acknowledged as ignored by scope.
7. Sonarr's future Webhook uses identical auth/method at
   http://ust-events/automation/hooks/sonarr, On Import/Download, Upgrade and
   Rename enabled; other triggers off. Leave it unconfigured during movie pilot.
   episodeFile.path and episodeFiles[].path are supported; multiple episodes
   referencing the same video do not create multiple translations.
8. Bazarr Settings -> Subtitles -> Post-Processing, after approval:
   install the isolated relay/token files above, enable post-processing, choose
   thresholds that include the approved pilot subtitle, and use exactly:

~~~sh
python3 /scripts/ust/automation_event.py --service bazarr --url http://ust-events --token-file /scripts/ust/event.token --video "{episode}" --language "{subtitles_language_code2}"
~~~

   Bazarr's {episode} represents either episode OR movie file path.
   en:hi/en.hi is normalized by the relay; non-English completions are ignored.
   Do not replace existing subtitle-scripts files. No post-processing is enabled now.
9. Approve model, a bounded paid test and its spending ceiling before translation.
   Enable the UST worker only after the single-file scope and legacy exclusion
   are verified. Scan selected files once or deliver the approved movie event.
   Monitor queue/job logs, validate every cue/timestamp and confirm Persian reads
   naturally with the movie; then check Jellyfin sidecar discovery.
10. Do not expand scope or enable series libraries without a separate review.

## Immediate pause and per-service rollback

Click Pause immediately on /automation. POST /automation/pause is session-
authenticated and origin-checked. It persists enabled=false, requests cancellation
of active automation jobs, blocks next provider batches and blocks publication.
A request already sent to OpenAI cannot be unsent; it may finish/bill. No further
processing should be scheduled and its reply cannot publish after pause.

For a hard stop: ./dev/ust stop backend events (development only).
Production port 2288 is independent and must not be stopped/recreated.

Radarr rollback: disable/remove only UST controlled pilot Webhook; restore the
original ID 1 settings from the snapshot. The original path remains broken;
do not silently repair it during rollback.
Sonarr rollback: disable/remove only the newly added UST connection.
Bazarr rollback: restore use_postprocessing=false and its exact previous command/
thresholds, then remove only the new ust/ relay/token files after confirming
they are unused. Never remove the shared /scripts directory.
UST rollback: pause; reset the real-processing gate to false, clear the selected
allowlist or restore the fixture allowlist, recreate only development backend.
Gateway rollback: ./dev/ust stop events, then remove only ust-dev-events if desired.
It leaves existing service network attachments intact.
Jellyfin rollback: no service change is currently planned beyond a later approved
refresh. Preserve valid produced sidecars; move only the pilot-created output
to a rollback folder after checking it was created by this pilot, never replace
or remove pre-existing Persian files.

## Remaining gates

No actual hook has been changed. No production translator deployed.
Real-library automation is paused and blocked by a deployment gate.
Approval is still needed for the specific pilot movie, legacy-hook exclusion,
provider spend, eventual hook configuration, and production promotion.
Jellyfin real-time monitoring configuration is verified; actual sidecar discovery\nand authenticated refresh behavior still need operator verification during the pilot. Cron/systemd configuration inspection found no legacy references;
manual/external invocation of the legacy wrapper must remain excluded.

Primary references:
- Sonarr webhook fields: https://github.com/Sonarr/Sonarr/blob/develop/src/NzbDrone.Core/Notifications/Webhook/WebhookSettings.cs
- Radarr webhook fields: https://github.com/Radarr/Radarr/blob/develop/src/NzbDrone.Core/Notifications/Webhook/WebhookSettings.cs
- Bazarr variables: https://wiki.bazarr.media/Additional-Configuration/Settings/Subtitles/#custom-post-processing

Final verification: 110 tests passed, 30 pre-existing containers unchanged,
Sonarr/Radarr notification responses and Bazarr configuration hashes unchanged,
and all 97 existing Persian sidecar hashes unchanged. No real-library writes.

Persian preservation additionally reuses the manual scanner's sidecar language\nmatching (including .fa.sdh.srt and aliases) and skips media with embedded\nPersian text tracks. This prevents redundant translation without altering\nexisting sidecars or embedded streams. Bitmap Persian tracks are not included\nin this text-track check and require operator review for the pilot.
