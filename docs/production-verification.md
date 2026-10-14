# Prime production automation verification — October 14, 2026

Production v1.8.2 uses immutable main-revision images on port 2288. Development
remains independent on 127.0.0.1:2289 with hot reload, paused automation and the
real-library processing gate disabled. Production is **enabled persistently** in
`events_only` mode for Movies and Shows. No historical library reconciliation ran.

Native Sonarr webhook ID3 and Radarr webhook ID2 use the authenticated internal
`ust-prod-events` gateway. Both native notification tests pass. Broken Radarr
Custom Script ID1 is preserved but disabled. Bazarr's enabled English-completion
relay runs through its existing script mount and production-only private token.
The public frontend returns 404 for webhook routes; no gateway port is published.
The old `subs-translator` container/scripts were neither invoked nor modified.

Intake polling observes Seerr, Sonarr, Radarr, selected qBittorrent downloads and
Jellyfin sessions with no service-poll failures. The initial four completed but
rejected Sonarr downloads appear as upstream failures, never translation jobs.
History recovery begins at the fixed first-hook activation timestamp and persists
paged cursors across restarts. No qBittorrent 100% download implies media import.

## Evidence

* 100 simulated files persisted in 1.452 seconds and completed 200 mocked batches
  in 80.163 seconds; peak two media workers/four API calls, roughly 75 MiB working
  memory. No paid requests in capacity testing.
* Tests cover paged 750-event recovery with concurrent arrivals/restart, duplicates,
  delayed English, failed/incomplete downloads, invalid destinations, independent
  extraction limits, budget races/exhaustion, rate limits, lease fencing, fair
  movie/episode scheduling and reduced admission during simulated transcodes.
* A separate forced-kill container test interrupted four active mocked requests
  across two files. Eight saved batches survived; all 40 batches completed after
  restart, and saved batches were never called again. Only isolated mock resource
  lease expiry was advanced; no production lease or spending record was reset.
* Generated six-second movie, episode and physical multi-episode fixtures were
  delivered through the production gateway, including real service-network
  contexts. Repeated events reused three physical intake rows. The delayed
  English file remained in intake without a translation slot/attempt, survived
  an actual production backend restart, and completed after the actual Bazarr
  container relay delivered its completion event.
* All three generated standard Persian SRTs passed exact cue-ID/timestamp and
  Persian-text validation. Source hashes were unchanged. Jellyfin automatically
  discovered and served all three Persian tracks using its native real-time
  monitor. No global refresh, real download or existing catalog mutation was
  required. Fixture subtitles reused previously verified Luna Medium checkpoints.
* The unrelated historical 3 Body Problem Bazarr event was ignored. Existing
  Coyote Persian checksum and unrelated container start times remained unchanged.
* Original manual history is preserved; authenticated production login/dashboard,
  unauthenticated rejection, backend/frontends and scoped rollback are verified.

The generated library verification directories were hash-verified and quarantined
outside Movies/Shows at `/tank/share/ust-backups/verification-assets-20261014`.
Only generated files moved; no user media or existing subtitle was removed.
Private source/output/result manifests remain under `/opt/containers/ust-production`.

## Configuration and accounting

GPT-6 Luna Medium, contextual natural Iranian Persian, batch size 40, maximum
12,000 source characters. Initial completion cap 16,384 escalates to verified
32,768 only for truncation. Global/day spending guard is USD5 UTC, concurrency-safe
with durable reservations for uncertain calls, repairs and retries.

Measured hard limits: backend 1.5 CPUs/1 GiB; two active translations, four global
API calls, two in-flight batches per file, two FFprobe inspections, one FFmpeg
extraction and one publisher. Memory/CPU/PSI/provider pressure lowers admission;
active Jellyfin transcodes lower it to one file/two API calls. These are tested
limits, not a claim that higher concurrency would be safe. No real transcode was
started for stress testing.

Production fixture API usage: USD0.0002196 total, two requests, 153 reasoning
tokens; later library fixtures reused checkpoints without extra paid calls.
No pre-existing movies/episodes were retransmitted to the provider.

Download Guard completed a dry run before strict auto removal was enabled.
Its four detected executable-only torrent records currently reference absent
payloads. They are reported without deletion. Removed count remains zero; scripts,
mixed content and ambiguous states are conservatively reported only.
`/tank/share/downloads` belongs to shared `tank/share`; no ZFS property changed.

## Backups and limits

Original complete v1.4 rollback: `/tank/share/ust-backups/20261014T223955Z`.
Immutable-update backups: `/tank/share/ust-backups/update-*`, including stopped
writer data, hash/integrity rehearsal, previous images and private configurations.
Original `/data/compose/14/data` remains separate and unchanged. Never roll back
or reset the new spending ledger when restoring application images.

Live native webhook tests and controlled fixture imports pass. No unnecessary
Seerr request/download was launched: the first naturally arriving new download
will exercise the full upstream download/import lifecycle. Missing English may
still require Bazarr/provider availability; such imports remain waiting without
blocking other files. UST does not repair or restart downloads. Unknown renamed
files without authoritative IDs need a trusted event/operator recheck. Remote API
responses lost during an outage can remain uncertain; full reservations are
retained, and completed checkpoints prevent repeat calls wherever possible.
