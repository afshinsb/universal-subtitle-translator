# Modern and Legacy interfaces

Both interfaces share the existing FastAPI application, session/account, production
SQLite database, translation engine, queue, workers and provider/budget policy.
No frontend framework, build server, runtime Node.js, replica or additional permanent
container is introduced. The new static CSS and JS total approximately 48 KB.

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

The browser updates every twelve seconds while visible, preserves input edits and
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
