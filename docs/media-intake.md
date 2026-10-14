# Media intake and upstream tracking

Production import events first persist a normalized identity in `media_events`
and a canonical library-file row in `media_intake`. They acknowledge before
inspection or provider work. Source service, native media/file/episode IDs,
download ID, import time, destination, update/error and preparation lease persist.
Repeated deliveries and multi-episode references to one path reuse the same row.

A separate read-only poller observes Seerr requests, Arr queues and import history,
selected qBittorrent torrents when an existing credential is available, and active
Jellyfin transcodes. It never adds/removes/resumes torrents, repairs downloads,
blacklists releases or searches for replacements. A complete torrent does not
submit translation. Four pre-existing Sonarr completed/import-warning entries are
upstream records, not translator work. Polling uses bounded responses/pages and
backoff; upstream failures cannot occupy translation slots.

Arr history recovery starts at the fixed production hook activation time. Its
persistent completed ID, cycle upper watermark and next page recover missed
imports and survive outages/restarts. A cursor advances only after its entire
post-activation range is ingested. Arrivals during a scan wait for the next range.
Old history is a stopping boundary, not work. No filesystem/history backfill is
performed. Malformed/outside-library entries are rejected without blocking later
imports. Existing pending post-activation queue rows are validated during upgrade.

At most two preparation tasks repeat file identity/size/mtime stability checks
(default ten seconds), require a regular supported file in approved libraries,
validate a video container/duration with FFprobe and correlate Arr file IDs/path/
size where supplied. Device/inode also participate in the signature. Known moved
pending files can resolve through authoritative Arr IDs. Missing destinations warn
and expire after six hours without ever becoming a translation job. Invalid media
and failed preparation remain separate from provider failures. Operators can
recheck imported files; this does not control downloads.

Only validated imports with usable English sources enter the translation queue.
Missing English sources stay in intake with no translation worker or failure
attempt. Bazarr events wake only known imports. Out-of-order subtitle events do
not seed historical jobs; periodic preparation notices sources that arrived early.
Prepared source paths and hashes are cached, avoiding repeated heavy extraction.

Resource pools are independent: at most two lightweight FFprobe commands, one
FFmpeg extraction, two active translations, four global API requests, two batches
per file and one atomic publisher. Preparation releases CPU/I/O slots before
provider work. Pause cancels preparation and prevents new paid calls. Memory/load/
PSI pressure and live Jellyfin transcodes reduce admission. Hard limits and bounded
pools apply even with hundreds of pending rows. Three same-service claims allow
an eligible opposite-service file next, preventing a large season starving movies.

Dashboard areas distinguish upstream downloads/import preparation, translation
progress/cost/retry, and processing resources. Lists are limited to 200 rows with
indexed sorting; SQL retains all jobs/events. Download stalls warn after twelve
hours without reported progress. Slow downloads are never automatically failed or
repaired. Configurable secure environment thresholds: `MEDIA_STABILITY_SECONDS`,
`MEDIA_IMPORT_TIMEOUT_HOURS`, `MEDIA_DOWNLOAD_STALL_HOURS`. Service credentials live
only in private production data, mode 0600. Requests use native APIs and fixed
argument arrays; no shell command from media/download metadata is executed.

Limits: polling cannot prove the semantic content of a release; Arr identity,
regular-file/container checks and subtitle validation are the available evidence.
Unknown-ID manual renames require a fresh trusted event/operator recheck; UST does
not scan the library to guess replacements. Remote paid requests can be ambiguous
after network loss; their full reservations remain charged against the guard.
