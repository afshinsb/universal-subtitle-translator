# Prime development environment

Workspace: /home/afshin/projects/universal-subtitle-translator.
Active branch: main, tracking origin/main, version 1.8.2.
Development-environment commit 22415a8 is preserved on main.
Upstream CI passed:
https://github.com/afshinsb/universal-subtitle-translator/actions/runs/38597986971

Atlas Codex is the development agent, accessing Prime over
ssh afshin@192.168.0.100. This is separate from recovered production Compose.

## Windows access

Keep the following running in a terminal. ssh -N is silent while connected.

~~~powershell
ssh -N -o ExitOnForwardFailure=yes -L 127.0.0.1:2289:127.0.0.1:2289 prime
~~~

If the alias is absent, use afshin@192.168.0.100.
Open http://localhost:2289. ALIEN browser login-page access was confirmed
by the user. Username: prime-dev. Retrieve the password privately:

~~~powershell
ssh afshin@192.168.0.100 "sed -n 's/^ADMIN_PASSWORD=//p' /home/afshin/projects/universal-subtitle-translator/dev/.env"
~~~

Do not share the password output. dev/.env is mode 0600 and Git-ignored.
There are no firewall changes or public development port bindings.

## Operations and editing

Run from the checkout:

~~~sh
./dev/ust up -d --wait
./dev/ust ps
./dev/ust logs -f --tail 100 backend frontend
./dev/ust stop
./dev/ust start
~~~

The wrapper explicitly selects dev/compose.yml and dev/.env.
Project/network: ust-dev / ust-dev_default.
Containers: ust-dev-backend and ust-dev-frontend.
Images: ust-dev-backend:1.8.2-5568f9e and ust-dev-frontend:1.8.2-5568f9e.
Backend port 2288 is internal; frontend publishes 127.0.0.1:2289 -> 80.

Both containers have health checks, unless-stopped restart policies,
bounded logs, CPU/PID limits, and memory limits (backend 768 MiB;
frontend 128 MiB). Idle memory was about 91 MiB and 6 MiB.

backend/app is bind-mounted read-only inside the backend; edit the host
source as afshin. Uvicorn runs:

~~~sh
python -m uvicorn app.main:app --host 0.0.0.0 --port 2288 --reload --reload-dir /app/app
~~~

Python edits reload automatically. Templates/CSS/JavaScript in backend/app
appear on browser refresh; hard-refresh cached browser assets.
Environment/mount changes require ./dev/ust up -d --force-recreate.
Dependency/Dockerfile changes require sequential builds:

~~~sh
./dev/ust build backend
./dev/ust build frontend
./dev/ust up -d --wait
~~~

Nginx config is bind-mounted as a template. After frontend/nginx.conf
changes, run ./dev/ust up -d --force-recreate frontend so the entrypoint
renders the updated config. Ordinary source changes need no rebuild.

## Storage and media

| Host | Container | Access |
| --- | --- | --- |
| dev/runtime/data | /app/data | UID/GID 1000:1000, writable |
| dev/runtime/fixtures | /media/fixtures | UID/GID 1000:1000, writable |
| /tank/share/media/movies | /media/movies | read/write (authorized) |
| /tank/share/media/shows | /media/shows | read/write (authorized) |

SQLite: dev/runtime/data/app.db. Uploads, outputs and temporary files have
separate subdirectories there. MEDIA_ROOT=/media restricts batch paths.
No production data or secrets are mounted. For generated tests use
/media/fixtures; real scanning uses /media/movies or /media/shows.

The development provider key and model are read from dev/.env.
Automation remains paused; paid translation requires approval.
Fixture scripts mock the provider only within their own process.
The v1.8.2 scanner supports output/temp fallback for unwritable media.
Real media was inspected without translation or writes. A movie had three
tagged English text streams. External English SRTs were readable in both
libraries (sample counts 1086 and 598 cues). Ten sampled show videos had
no tagged English text streams; generated fixtures verify that workflow.

Discovered existing networks: Sonarr sonarr_default; Radarr radarr_default;
Bazarr bazarr_default; qBittorrent qbittorrent_default;
subs-translator subtitle-tools_default. Jellyfin runs as a native service.
Development joins only ust-dev_default and accesses services via
prime-host (192.168.0.100) on existing published ports.

Existing service configs: /opt/containers/<service>/config.
Jellyfin paths: /var/lib/jellyfin and /etc/jellyfin.
Shared scripts: /opt/containers/subtitle-scripts.
Media: /tank/share/media/movies and /tank/share/media/shows.
qBittorrent data: /tank/share/downloads and /tank/share/incomplete.
No existing Docker networks, hooks, mounts, or ownership were changed.
No Docker socket or production service configs are mounted in development.

## Verification

Actual Linux image builds passed. Credential-free smoke ran with networking
disabled, generated embedded English subtitles and mocked translations,
validated timing/Unicode/SRT output, and preserved output on a repeat run:

~~~sh
docker run --rm --network none --memory 512m --cpus 1 \
  -v "$PWD/scripts:/smoke:ro" --entrypoint python \
  ust-dev-backend:1.8.2-5568f9e /smoke/smoke.py
~~~

Targeted checks:

~~~sh
python3 dev/verify_http.py
docker exec -e OPENAI_API_KEY= -i ust-dev-backend python < dev/verify_backend.py
docker exec -e OPENAI_API_KEY= -i ust-dev-backend python < dev/verify_persian.py
python3 dev/verify_services.py
python3 dev/verify_reload.py
~~~

verify_backend regenerates only dev fixture media, checks real media reads,
and creates a dev SQLite marker. verify_persian creates a generated .fa.srt
and persistent completed dev batch using an in-memory HTTP mock.
verify_services makes GET requests only, reading existing service API keys
transiently without printing or storing them.
verify_reload temporarily edits Python/templates/CSS and restores all edits;
run while development is idle because Python reload interrupts running jobs.

Passed: health, frontend/backend proxying, correct/incorrect login,
session cookie, FFmpeg/FFprobe, extraction, external English SRT reading,
fixture translation, Persian Unicode/RTL/timing, duplicate preservation,
Python reload, template/static refresh, container restart, SQLite persistence.
Persian output has two dialogue cues plus the existing application watermark.

Sonarr/Radarr/Bazarr authenticated system-status GETs returned 200.
Jellyfin public info returned 200 (10.11.11).
qBittorrent returned 403 to unauthenticated version GET; authenticated API
validation remains pending. subs-translator was inspected only.

Private evidence: dev/runtime/evidence. All 30 pre-existing containers kept
their IDs, image IDs, start times, and restart counts; production /health
still returns 1.4.0. SSH tunnel health/login access passed from Atlas and
the user confirmed the Windows login page.

## Git, promotion, rollback

Commit infrastructure/source changes only; dev/.env and dev/runtime are ignored.
Use Git commits as checkpoints and review changes before a PR.
Production promotion requires a separate release with explicit authorization,
backup, migration review, and production rollback planning.

To stop and remove development containers/network, run ./dev/ust down.
Bind-mounted dev data remains. Revert source with Git; rebuild only when
build-time components change. Production remains on port 2288.
Never run the repository release Compose file on Prime: it hard-codes
production container names. Never prune Docker.

## Codex workflow

Development uses Atlas Codex over SSH as requested.
Before that clarification, the official standalone installer was downloaded,
fully inspected and run as afshin. It installed CLI 0.162.1 at ~/.local/bin/codex
with packages under ~/.codex/packages/standalone and a PATH block in ~/.bashrc.
No Node.js/system packages were installed. Existing ChatGPT auth was detected.
The Prime CLI is unused and optional; its credentials were not displayed.
If explicitly wanted later: cd into this checkout and run ~/.local/bin/codex.

## Automatic subtitle pipeline

See ../docs/automation.md. The Automation page is /automation. Processing
remains paused, fixture-only, and provider-free until explicitly configured.
Future work, commits and pushes use main directly.

Provider configuration update: dev/compose.yml now honors the key and upload
limits in dev/.env. Model, style and SRT batch settings also come from that
file. Automation remains paused. Startup checks model access; agent-run tests
clear the provider key and use mocks, with no paid inference requests.

Media access update: the user authorized Movies/Shows read/write mounts.\nExisting afshin (1000:1000) permissions were sufficient; no host chmod/chown\nwas needed. Automation roots include fixtures, movies and shows; source\nservice path mappings are configured, but automatic processing remains paused.\nAgent-run translation tests continue to use fixtures and mocked providers.\n
## Real integration preparation

See ../docs/prime-integration.md and ../docs/persian-quality.md. An internal
ust-dev-events gateway exposes authenticated import routes on the service
networks without host ports. No service hooks are enabled. Real-library
processing remains blocked by AUTOMATION_REAL_LIBRARY_PROCESSING=false and
the selected-file scope is limited to retained fixtures.

### Development translation model

Prime development uses GPT-6 Luna with OPENAI_REASONING_EFFORT=medium and
OPENAI_MAX_COMPLETION_TOKENS=32768. The completion limit covers both hidden
reasoning and translated text. Explicit reasoning requests omit temperature.
Keep these values in private dev/.env and recreate only the backend with
./dev/ust up -d --no-deps backend after changing them. No image rebuild is needed.
Normal automation remains paused and real-library processing remains disabled.
The release example retains its existing model default.

Model documentation: https://developers.openai.com/api/docs/models/gpt-6-luna

### Final automation activation

See docs/final-automation-activation.md and docs/production-promotion.md.
Normal automation remains paused, real-library processing=false, and the pilot
approval/Compose files are inactive drafts. OPENAI_DAILY_BUDGET_USD defaults to 0
(off); configure a separately approved positive limit and conservative rates
before normal automation activation. The persistent provider-budget.sqlite must
not be reset/deleted. Configuration is sealed; review any change while paused.
The automation UI now exposes event-only discovery, exact/new-import scopes,
budget reservations and failure/retry controls. New-import library scope requires
event-only mode and pauses on expansion. One automatic translation is leased
across workers. Bazarr completions wake known imports instead of queuing history.
