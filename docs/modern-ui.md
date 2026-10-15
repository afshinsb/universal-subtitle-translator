# Modern and Legacy interfaces

Both interfaces share the existing FastAPI application, session/account, production
SQLite database, translation engine, queue, workers and provider/budget policy.
No frontend framework, build server, runtime Node.js, replica or additional permanent
container is introduced. The new static CSS and JS total less than 75 KB.

| Function | Modern | Legacy |
| --- | --- | --- |
| Overview / upload | `/ui`, `/ui/translate` | `/` |
| Intake / downloads | `/ui/downloads` | `/automation` |
| Translation queue | `/ui/queue` | `/automation` |
| Download Guard | `/ui/guard` | `/automation#download-guard` |
| Automation scope / paths | `/ui/automation` | `/automation` |
| History / outputs | `/ui/history`, `/ui/outputs` | `/`, `/outputs` |
| Batch scan / translation | `/ui/batches` | `/batches` |
| Job / batch detail | `/ui/jobs/{id}`, `/ui/batches/{id}` | `/jobs/{id}`, `/batches/{id}` |
| Settings / logs | `/ui/settings`, `/ui/logs` | `/settings`, `/logs` |

Production base URL: `http://192.168.0.100:2288`. Development is still independently
available through the existing SSH tunnel at `http://localhost:2289`.
The Modern/Legacy switcher stores a one-year, HttpOnly, SameSite preference cookie.
Returning to `/` opens Modern when preferred; switching to Legacy restores its home.
Explicit `/automation` remains Legacy regardless of preference. HTML job/batch links
follow the chosen interface; downloads, JSON, CSV and event endpoints keep their
original behavior. Modern sign-in uses the same `/login` handler and session.

Modern uses neutral graphite surfaces and a restrained indigo accent in both dark
and light themes. Its stylesheet URL is versioned when the palette changes so
returning browsers load the current appearance. Legacy keeps its original theme.

Legacy template files remain, with their manual forms/scripts extracted into shared
partials used by both shells. Modern CSS/JS are separate from Legacy theme assets.
Language/style options, uploads, overwrite confirmation, folder selection/scanning,
file selection, concurrency, batch reports, output downloads, job cancellation,
logs/exports and advanced readiness/cleanup controls remain available. Provider,
account and budget configuration retain their existing secure-environment workflow.
Production is immutable and does not use source mounts or hot reload.

## Live data and bounded queries

`GET /ui/api/status` returns sanitized operational counts, actual resource leases,
provider/model policy, budget consumption/reservations, Guard state and recent logs.
It does not return provider credentials or integration tokens. The latter requires
an explicit authenticated, origin-checked POST reveal; it is not embedded in pages.
Private pages/status responses are not cached.

`GET /ui/api/{queue,downloads,history}` supports `page`, `state`, `search`, `size`.
Default pages contain 25 rows; maximum 50. SQL filters/counts and stable ordering
avoid loading the entire queue/history. Usage is aggregated only for visible files.
FIFO positions describe arrival order; fair scheduling can promote movies between
series files. Cost labels distinguish confirmed usage and outstanding reservations.
No ETA is fabricated when no measurable translated work exists.

The browser updates automatically while visible, preserves input edits and
row order, and stops network polling while hidden. It never reloads the page to
update progress. Existing per-job/batch monitoring remains tied to its existing
workflow. Actions use the original authenticated endpoints and show success/failure.

Downloads are read-only upstream observations. Arr import rejection/stalls are
separate from translation failures. Imported validation and subtitle preparation
have their own records; missing English does not occupy a translation worker.
Actual extraction phase is persisted while FFmpeg is invoked. Related episode
rows group by show/season within the current page, without hiding individual errors.

## Download Guard correction

The original Production template rendered Guard about 4,100 pixels below the top
of Automation. It was deployed and authenticated, not missing. Guard now appears
first in Legacy and has its own Modern navigation item and page.

The original suspicious count counted historical `detected` audit entries forever.
A separate current-identity table now records fresh API/path verification, absent
payloads, vanished torrent hashes, category changes and actual Guard removal.
Audit history remains intact. Missing payloads and removed torrent identities are
not counted as current suspicious payloads. The UI also exposes verification time,
last successful/attempted scans, errors, recent activity and removal history.

Exact-hash reconciliation is bounded to twenty known identities per scan and is
always non-destructive. Category scanning retains its bounded rotating cursors.
Manual scans run on the existing Guard worker, always dry-run, even in auto mode.
There is no extra container or per-click unbounded thread/task creation.

Enabling strict automatic removal requires an explicit browser confirmation AND
server-side confirmation field. The existing conservative deletion policy remains
unchanged. Guard was held in dry-run during UI verification; no torrent/data removal
was authorized as part of those checks.

Nginx now forwards `$http_host`, preserving the external port. Previously `$host`
dropped it and could reject legitimate same-origin form submissions. Origin checks
remain strict; no wildcard CORS, authentication relaxation or public webhook exposure
was added. Both Modern and Legacy toggles were tested through the real Dev proxy.

## Verification and rollback

Automated coverage includes 100-file webhook intake/deduplication/reopen, no queue
before validation, bounded 2,000-record pagination/order/search, real extraction
phase, upstream failures outside the translation queue, shared authentication,
interface preference, secret redaction, Guard reconciliation and dry scans.

`scripts/ui_fixture_server.py` is a disposable browser QA harness. It requires
DEV_MODE and absence of a real API key. It uses actual routes/SQLite, fixture media
and an HTTP mock provider. Never mount real application data or credentials there.
Browser verification covers upload/Persian download, FFmpeg batch scan/translation,
100 queued files, cancel/retry, pagination, hidden-tab polling, both interfaces,
Guard confirmation/toggles, dark/light themes and mobile navigation/layout.
Fixture screenshots are explicitly QA data, not production metrics.

Use the existing immutable release update procedure after tests/CI pass. Back up
private runtime data, image IDs and configuration; retain the original v1.4 backup.
Wait for active translations to drain before recreating the production backend.
Keep the automation enabled flag and all spending records intact. On health failure,
restore previous images/configuration, retaining new queue/ledger data. The added
phase/current-finding columns and tables are additive and can remain for rollback.
Do not modify media-service hooks or reset either application database for UI updates.


## Live processing workspace

Overview and Queue include a bounded live-translation area, with per-file cue
progress, distinct completed-batch counts, current processing stage, measured ETA
when available, confirmed API cost and a link to the existing job detail page.
Progress is based on persisted completed cues; animation never invents completion.
Parallel batches are counted distinctly even when logs repeat or finish out of order.
The queue remains paginated (25 rows); the live area loads at most six running files.
It does not launch workers or change scheduling or spending limits.

Visible Overview, Queue and Intake pages poll every three seconds while work or
upstream downloads are active, and every ten seconds while idle. Hidden pages stop
polling, and resume on visibility. DOM patches preserve progress-bar elements,
expanded paths and focus, enabling smooth transitions without whole-row flicker.
Subtle entry, activity and progress animations respect reduced-motion preferences.
On phones, records become labelled cards that retain progress, model, cost and actions.
Grid tracks use bounded minimum widths to prevent overlapping panels and long names.

Browser verification uses the isolated mock-provider QA container and 100 fixture
queue records, including two artificial running-job records for rendering and update
tests. These are never inserted into Production or presented as live production data.


## Download identity, names and removal

A season torrent is one download row, grouped by service and case-insensitive
infohash. Individual imported video files remain separate intake/translation items.
Download counts use the same grouped read model as the paginated table. Imported
episodes use the media title and episode notation; cached source SRT identifiers
are not used as titles in automatic translation history.

Seerr titles are resolved through its read-only movie/TV details API and cached.
Its current request and availability status enums follow
[Seerr constants](https://github.com/seerr-team/seerr/blob/develop/server/constants/media.ts),
including completed requests, partial availability and removed media. Completed
requests leave Active; All states retains them. Newest requests and one rotating
older page are refreshed with at most six metadata lookups per polling cycle.

A missing Arr queue entry is reconciled only after a complete successful paginated
queue read (up to five pages of 100) and an exact qBittorrent hash lookup. Imported
file records take precedence. Confirmed missing downloads become Removed from
downloads; incomplete/failed API reads never assert deletion. Download Guard's
confirmed removals update this observation too. Removed records remain in history.
Stale download observations show Status unavailable, not an indefinitely live
percentage. None of these upstream states creates a translation job.

Missing imported files with obsolete Arr file IDs get a short arrival grace period
and then terminal validation failure. Corrupt media preparation has bounded retries;
terminal failures retire any old gated queue entry. Missing English subtitles remain
waiting without occupying translation workers. A later valid import is accepted
normally. Existing history cursors and the events-only discovery policy are unchanged.
The original upstream table layout is retained; new metadata is in a separate table
so an image rollback can still write observations using the previous release.

Modern confirmations appear beside the clicked action, with Confirm and Back,
keyboard Escape and a short expiry. An open confirmation survives live row updates;
no cancellation/removal request is sent until confirmed. Shared manual controls use
the same helper in Modern, while Legacy retains its previous behavior. Automatic
cleanup still requires the server-side confirmation flag and all existing safety checks.
Polling implementation details are not shown as interface copy.
