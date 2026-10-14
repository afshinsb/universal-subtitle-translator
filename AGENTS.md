# Prime development workspace

Primary checkout: /home/afshin/projects/universal-subtitle-translator on
Prime 192.168.0.100. Atlas Codex develops over SSH as afshin.
Use main exclusively, tracking origin/main. Commit and push completed work
directly to main; never force-push, discard commits, or overwrite local changes.

Use ./dev/ust (dev/compose.yml, project ust-dev) exclusively on Prime.
Never start release Compose files: their names collide with production.

Preserve production translator 1.4.0, port 2288, Portainer stack 14.
Do not update/restart/replace/migrate production, touch its data/secrets,
modify subs-translator or media-service hooks, change library ownership,
change firewall/network settings, or prune Docker. Keep builds sequential.

Development names: ust-dev-backend and ust-dev-frontend.
Only published development port: 127.0.0.1:2289.
Backend uses UID/GID 1000:1000. The user authorized read/write Movies and
Shows mounts. Existing host permissions are sufficient; do not broaden them.
AUTOMATION_ALLOW_LIBRARY_WRITES=true permits configured library roots,
but agent-run translation tests must still use fixtures and mocked providers.
Use generated writable fixtures and mocked providers for agent-run tests.
A development API key may be configured. Never display it or make paid AI
requests without approval. Keep automation paused unless explicitly authorized.
dev/.env and dev/runtime are private and ignored. Never commit or print them.

Python source reloads automatically; templates/static assets refresh.
Recreate for environment/mount changes, rebuild for dependencies/Dockerfiles.
See dev/README.md for access, operations, tests, and rollback.

Integration preparation: ust-dev-events may join existing service networks as
an internal gateway with no published ports. Do not change service hooks or
attach/recreate existing services. Real-library processing is disabled by
AUTOMATION_REAL_LIBRARY_PROCESSING=false; preserve that gate until approval.

## Authorized final rollout (2026-10-14)
The user's final mission supersedes the earlier production/hook restrictions:
upgrade Production, preserve and back up stack 14 and original data, enable
Radarr/Sonarr/Bazarr authenticated integrations, and leave production events-only
automation enabled with GPT-6 Luna Medium and a persistent USD 5/day guard.
Development remains independent and paused. No historical library backfill,
no overwrite of subtitles, no broad permission changes, no unrelated service
changes, no Docker pruning. Preserve rollback images and private verified backups.
