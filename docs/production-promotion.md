# Production promotion and rollback — execution authorized

The final rollout authorization supersedes earlier approval gates in this document.
The Coyote pilot succeeded. Production promotion, authenticated Radarr/Sonarr/Bazarr
hooks and events-only ongoing translation are now authorized with USD 5/day.
Use `scripts/prime_promote.py` from verified main: backup, prepare with immutable
release revision, deploy with automatic rollback on health failure. Private runtime
artifacts live under `/tank/share/ust-backups/<UTC timestamp>` and
`/opt/containers/ust-production`; never commit them.

Portainer stack 14 retains its metadata and Compose project identity. Its Compose
file is updated inside its volume; host Compose performs the scoped replacement
using the same project and production names. No Portainer authentication reset is
needed. The original data tree remains the rollback source. Full stopped-writer
archives, restored file hashes, SQLite integrity, container/environment snapshots,
Portainer database/stack definitions and saved image archives are verified first.

Current scheduler/budget/resource procedure is in queue-and-capacity.md. Production
starts paused with empty scope for acceptance, then uses Movies/Shows event-only
scope and remains enabled. Development stays paused, isolated on 2289. Production
uses 1024 MiB/1.5 CPUs, two active files, one extraction, four global API requests,
two batches/file, with pressure-aware reductions. No source mounts/hot reload in
production. Daily requests reserve worst-case cost and settle confirmed usage;
uncertain requests retain their bounds. Immutable image revision labels identify
release code. The existing secure production login and provider credential are
preserved; the webhook token, queue, checkpoints and ledger are independent.

The following original preparation record explains the backup/migration rationale;
its old references to separate approval are superseded by the authorization above.

## Current production evidence

Portainer stack 14; port 2288 published by subtitle-translator-frontend.
Backend runs root, with /data/compose/14/data bound to /app/data.
Backend image e286cbac77a396c1f908ede258a98e94cd93bc016c0f1c2f6671dc5117ac86ec.
Frontend image 301332da1cf3ff58e9f771103702f05cb7aa59e49fe5ecf4558ed6163eb6805b.
The authoritative stack definition is /data/compose/14/docker-compose.yml INSIDE
Portainer's /data volume, not that same path on Prime's host filesystem.
A private copy and container environment/image snapshots already exist under
dev/runtime/final-integration/20261014T195043Z. No production container was changed.

A read-only base-database copy passed an isolated schema rehearsal with
scripts/verify_migration.py: original jobs/logs/batches/sequence data preserved;
new automation config paused and queue empty. The live database was not opened
writable, migrated, replaced or restarted. This is not a cutover backup and
does not claim to include uncheckpointed WAL changes.

## Concrete promotion sequence, only after separate approval

1. Record the approved main commit and successful CI. Build both release images
   sequentially from an archived clean checkout of that commit, not mutable bind
   mounts. Use unique tags ust-release-backend:<commit> and
   ust-release-frontend:<commit>; record image IDs/digests and verify source/version.
   Smoke-test with mocked provider and --network none. Preserve old image IDs
   with rollback tags and docker image save archives in private backup storage.
   Do not prune or pull over an old rollback tag.
2. In Portainer, export stack 14 content AND its environment/metadata/endpoint
   details; save private mode 0600. Record published bind, restart/health/resource
   settings, mounts and dedicated network. Back up current container Config.Env
   (contains secrets) and app configuration files separately. A Compose file alone
   is insufficient. Verify required production auth/key settings without printing
   their values. Never copy development passwords/token/session secret.
3. Put the application into maintenance, pause any queue and stop only production
   frontend/backend through stack 14. The pilot will already have stopped and
   returned Development to paused/real-processing=false on 2289.
   With production writers STOPPED, archive the entire /data/compose/14/data tree,
   including app.db, any -wal/-shm, uploads, outputs, temp, modes and ownership.
   Hash archive and record database integrity, all original table row hashes,
   file checksums and restore destination. Test extracting into a private
   rehearsal directory. Never copy only app.db while a writer is running.
4. Stage a NEW production data copy at /opt/containers/ust-production/data from
   the verified backup. Preserve /data/compose/14/data unchanged for rollback.
   Set UID/GID 1000:1000 ONLY on the new production copy; no chown of real media,
   original data, or whole /tank/share. Verify that app.db's directory, uploads,
   outputs and temp are writable by UID 1000. Run scripts/verify_migration.py
   against the offline backup and inspect any remaining schema incompatibility.
5. Prepare a reviewed stack 14 replacement using immutable candidate image IDs,
   the new absolute data bind, existing production names and host port 2288.
   Backend internal port 2288; frontend preserves the existing published bind.
   No source bind mounts or Uvicorn reload in production. Set DEV_MODE=false,
   DEMO_MODE=false, AUTH_ENABLED=true; preserve secure production login/session
   settings and the EXISTING production API key privately. If credentials are
   absent/insecure, generate dedicated production credentials before deployment;
   do not copy development credentials. Keep a private production environment
   file/Portainer environment, never Git.
6. Set provider explicitly to gpt-6-luna, OPENAI_REASONING_EFFORT=medium,
   OPENAI_MAX_COMPLETION_TOKENS=32768, standard tier under the budget guard.
   Propose OPENAI_DAILY_BUDGET_USD=5, input ceiling 0.125/output 0.5 per million;
   require approval for this daily allowance. The production provider-budget.sqlite
   belongs in its own new data directory, never the development pilot/comparison
   ledgers. Keep one leased automatic translation, BATCH_FILE_CONCURRENCY=1.
7. Production automation config/queue must be new, empty and paused, with
   discovery_mode=events_only and selected_files initially empty. Do not import
   development queue rows, allowed fixture paths or integration token. Preserve
   existing manual job/log/history tables. Mount Movies and Shows to /media/movies
   and /media/shows; UID1000's existing permissions suffice. Configure mappings
   /movies -> /media/movies and /tv,/shows -> /media/shows. Keep
   AUTOMATION_REAL_LIBRARY_PROCESSING=false until the staged import approval.
8. Add a separate production-only event gateway service on the production network
   plus external sonarr_default/radarr_default/bazarr_default, alias ust-prod-events.
   Reuse the reviewed POST-only Nginx gateway config, backend:2288 resolution,
   authentication forwarding, 64KiB body limit, disabled access log and zero
   host-published gateway ports. Generate a new production UST integration token.
   No existing service container/network attachment needs changing.
9. Suggested resource limits: backend 768MiB/1 CPU, frontend 128MiB, gateway64MiB;
   health checks, unless-stopped restart, bounded logs, non-root backend, dropped
   capabilities and no-new-privileges. Validate stack configuration without
   printing credentials. Deploy only this approved stack 14 replacement.
10. Acceptance: healthy containers, authenticated browser access on 2288, forbidden
    unauthenticated API, correct release/version/model/effort, FFmpeg, all original
    manual histories and output paths readable, offline/fixture mocked translation,
    empty paused production queue, and new independent budget/token. Development
    still works at localhost:2289 and no media-service settings changed.
    Keep hooks disabled until separate real import approvals.

## Verified-data rollback procedure

Pause new production automation; stop ONLY replacement stack 14 services.
Save any NEW production queue, logs, budget ledger and generated-output manifest
privately. Never discard paid reservations or overwrite a generated sidecar.
Restore the archived stack 14 Compose/environment/metadata and the original image
IDs from preserved tags/archives. Point it back to the UNCHANGED original
/data/compose/14/data, with its original root permissions. Do not run old v1.4
against the migrated new database copy.

If the original data was somehow altered, extract the verified stopped-writer
backup to a separate restore location first; compare all table/file hashes and
ownership before replacing anything. Keep any new-data archive separate.
Restart old production services, verify v1.4.0 health, login/manual outputs and
port2288. Confirm Development still uses 2289 and its own data.

Restore only the approved UST notification/post-processing changes from private
service snapshots. Do not automatically repair the broken legacy script.
For newly produced Persian outputs, retain valid files by default. If rollback
requires removing a pilot sidecar, match its recorded creation/hash and quarantine
only that file, leaving all existing English/Persian/video files untouched.

A database schema rehearsal is complete. The stopped-writer backup, full restore
rehearsal, secure production credential verification, immutable release-image
build and promotion itself remain to be executed AFTER approval. No production
replacement has occurred.
