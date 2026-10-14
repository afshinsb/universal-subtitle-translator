# Prime development workspace

Primary checkout: /home/afshin/projects/universal-subtitle-translator on
Prime 192.168.0.100. Atlas Codex develops over SSH as afshin.
Use main exclusively, tracking origin/main. Commit and push completed work
directly to main; never force-push, discard commits, or overwrite local changes.

Use ./dev/ust (dev/compose.yml, project ust-dev) exclusively on Prime.
Never start release Compose files: their names collide with production.

Preserve production translator 1.4.0, port 2288, Portainer stack 14.
Do not update/restart/replace/migrate production, touch its data/secrets,
modify subs-translator or media-service hooks, change library permissions,
change firewall/network settings, or prune Docker. Keep builds sequential.

Development names: ust-dev-backend and ust-dev-frontend.
Only published development port: 127.0.0.1:2289.
Backend uses UID/GID 1000:1000. Real libraries are read-only.
Use generated writable fixtures and mocked providers; no real AI key is set.
dev/.env and dev/runtime are private and ignored. Never commit or print them.

Python source reloads automatically; templates/static assets refresh.
Recreate for environment/mount changes, rebuild for dependencies/Dockerfiles.
See dev/README.md for access, operations, tests, and rollback.
