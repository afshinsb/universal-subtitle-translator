# Installation, maintenance and release operations

These are operator-run commands. This audit has not changed any running container, published an image, created a release tag or changed the host Docker Engine. Commands below use a Linux shell unless marked otherwise. Run them from the repository root, preserving the same Compose project directory/name and media overrides as your existing installation.

## Fresh installation

Follow the [README](../README.md#fresh-docker-compose-installation) to clone, configure credentials, prepare `./data`, and mount media read/write. Then:

```bash
docker compose --env-file .env config -q
docker compose --env-file .env build --pull
docker compose --env-file .env up -d --wait
curl --fail http://localhost:2288/health
docker compose ps
```

Expected health version: `1.8.2` when using `IMAGE_TAG=1.8.2`. Log in, check Settings readiness, scan the mounted `/media` path, translate a safe video with an English sidecar/text track, and verify `<video-base>.fa.srt` beside the original video on the host. Browser uploads instead save under `data/outputs/<job-id>/` and provide a download link. A read-only media mount uses app-data output, not the media folder.

## Safe update of an existing source-built installation

Finish or cancel active jobs first. Cancellation is cooperative; an already accepted model request can finish and be billed. The app does not resume partial translations after a restart.

Save the actual old image IDs as local rollback tags **before** building or pulling replacements (even if the old installation used `latest`). The fixed container names below are the repository's existing defaults:

```bash
docker image tag "$(docker inspect --format '{{.Image}}' subtitle-translator-backend)" ust-rollback-backend:1.8.1
docker image tag "$(docker inspect --format '{{.Image}}' subtitle-translator-frontend)" ust-rollback-frontend:1.8.1
umask 077
BACKUP_DIR="../ust-backup-$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -p "$BACKUP_DIR"
cp -p .env docker-compose.yml docker-compose.hub.yml "$BACKUP_DIR/"
if [ -f docker-compose.override.yml ]; then cp -p docker-compose.override.yml "$BACKUP_DIR/"; fi
git rev-parse HEAD > "$BACKUP_DIR/source-commit.txt"
docker compose stop
tar -czf "$BACKUP_DIR/data.tgz" data
```

Also back up any custom Compose files and record your project name (`-p`) if used. The stopped backup includes SQLite WAL/SHM files as well as uploads, fallback outputs and temp data. External media/subtitles live outside `data`; preserve those mounts and their usual backups. Keep backups private because `.env` contains credentials. Do not prune rollback images until the upgrade is accepted.

Update the checkout to the reviewed 1.8.2 source (or the maintainer's `v1.8.2` tag once it exists). A clean tracking checkout can use:

```bash
git pull --ff-only
```

Edit the **existing** `.env`, retaining the model, API key, mount paths, output directories and session secret. Set `IMAGE_TAG=1.8.2`. Supply secure auth settings if the old installation used defaults, set `DEV_MODE=false`, and configure `PUID`/`PGID` to the existing media user. For intended LAN access, explicitly retain it with `APP_BIND_HOST=0.0.0.0`; otherwise the new default is localhost only.

The image now runs as a non-root user. If old app data is root-owned, grant your chosen UID/GID access to **only that app data directory** after the backup. Substitute the actual numbers (shown below as 1000):

```bash
sudo chown -R 1000:1000 ./data
docker compose --env-file .env config -q
docker compose --env-file .env build --pull
docker compose --env-file .env up -d --wait
curl --fail http://localhost:2288/health
docker compose ps
docker compose logs --tail=100 backend frontend
```

Do not run ownership commands against `/srv/media` wholesale. Grant a media group or ACL access to selected writable folders. If you keep a `:ro` mount, outputs fall back to app data. The Linux `chown` step does not apply to Windows Docker Desktop bind mounts.

Verify login, Settings readiness, old history, old downloads and existing generated subtitles. Repeat a batch with overwrite disabled: completed files should skip. Run the fixture below to check media processing without sending real subtitles to a model. No schema migration is introduced in 1.8.2.

## Pull-only installation/update (only after images are published)

No application registry namespace or published 1.8.2 image has been verified. Obtain the actual namespace and version from the image owner. Set `DOCKERHUB_NAMESPACE` in `.env`, and first verify both manifests:

```bash
DOCKERHUB_NAMESPACE=actual-owner
docker buildx imagetools inspect "$DOCKERHUB_NAMESPACE/universal-subtitle-translator-backend:1.8.2"
docker buildx imagetools inspect "$DOCKERHUB_NAMESPACE/universal-subtitle-translator-frontend:1.8.2"
```

Use the same credential, backup, permission and maintenance steps above. For a new pull-only installation, set up data and media first. Unlike the default Compose invocation, `-f` requires you to pass your media override explicitly:

```bash
docker compose --env-file .env -f docker-compose.hub.yml -f docker-compose.override.yml config -q
IMAGE_TAG=1.8.2 docker compose --env-file .env -f docker-compose.hub.yml -f docker-compose.override.yml pull
IMAGE_TAG=1.8.2 docker compose --env-file .env -f docker-compose.hub.yml -f docker-compose.override.yml up -d --wait
curl --fail http://localhost:2288/health
```

Omit the override argument only if there is no media override. Keep the same project name and directory so the existing data/mount configuration continues to apply. `IMAGE_TAG` takes precedence over an old `APP_VERSION` and is used consistently for backend, frontend and displayed version.

## Rollback using locally retained old images

This avoids relying on a registry tag that may never have existed. Retain your updated secure auth settings and data mounts. Create `docker-compose.rollback.yml`:

```yaml
services:
  backend:
    image: ust-rollback-backend:1.8.1
    environment:
      APP_VERSION: 1.8.1
  frontend:
    image: ust-rollback-frontend:1.8.1
```

Then, during your maintenance window:

```bash
docker compose stop
docker compose --env-file .env -f docker-compose.yml -f docker-compose.override.yml -f docker-compose.rollback.yml up -d --no-build --pull never --wait
curl --fail http://localhost:2288/health
docker compose ps
```

Omit `-f docker-compose.override.yml` if none exists, or replace it with all of your actual override files. Pull-only users substitute `docker-compose.hub.yml` for the base file. Expected health version: `1.8.1`. The current UID setting can run the old root-built image as your configured user; ownership was prepared for that user during upgrade. The old application still has its original defects, so keep secure credentials and local binding.

The 1.8.2 schema is backward-compatible; do not restore the data backup over current files for a routine rollback. That would discard newer jobs and outputs. If data recovery is necessary, stop the stack, preserve the current data directory under a separate name, and extract the backup into a **separate empty recovery directory** for inspection before choosing what to restore. Never delete media or generated subtitles as part of a rollback.

## Credential-free smoke test

Native Python environment with backend runtime dependencies and FFmpeg/ffprobe:

```bash
python scripts/smoke.py
```

After building the image, on a host with a working Docker daemon:

```bash
docker build -t ust-audit-backend:1.8.2 ./backend
docker run --rm --network none -v "$PWD/scripts:/smoke:ro" --entrypoint python ust-audit-backend:1.8.2 /smoke/smoke.py
```

PowerShell equivalent:

```powershell
docker run --rm --network none --mount "type=bind,source=$PWD/scripts,target=/smoke,readonly" --entrypoint python ust-audit-backend:1.8.2 /smoke/smoke.py
```

Expected JSON includes `"status": "passed"`, two dialogue cues, and `"repeat": "skipped; output preserved"`. It runs as the image's non-root user, creates a tiny synthetic video with full and forced English tracks, uses the real SDK with an in-memory HTTP transport, checks output beside the video and exact timestamps, then cleans up its own temporary directory. It mounts no production data or `.env`. It does **not** validate real provider access, Nginx networking, bind-mount permissions or arm64 runtime behavior.

## Maintainer release and manual image publishing

The repository uses semantic patch releases. Previous source version: `1.8.1`; this change: `1.8.2`. Only `v1.3.0` and `v1.2.0` existed as local tags during inspection; recent release-named commits were not consistently tagged. There was no `.github` workflow. Publishing credentials and a real registry namespace were not established, so this change adds read-only CI rather than a speculative publishing workflow.

CI tests Python 3.10/3.12, lint, compilation, dependency advisories, Compose validation, a Docker media smoke test, and amd64/arm64 builds. It has `contents: read`, pins third-party action commits, and does not log in to a registry or publish images. The new workflow still needs to run in GitHub.

After reviewing/committing changes and passing checks, an authorized maintainer can create the matching source tag and publish both images under their own namespace. Do not run these until the release is actually approved:

```bash
git tag -a v1.8.2 -m 'Release v1.8.2'
git push origin v1.8.2
docker login
DOCKERHUB_NAMESPACE=actual-owner
docker buildx create --use --name ust-release
docker buildx build --platform linux/amd64,linux/arm64 --build-arg APP_VERSION=1.8.2 -t "$DOCKERHUB_NAMESPACE/universal-subtitle-translator-backend:1.8.2" --push ./backend
docker buildx build --platform linux/amd64,linux/arm64 --build-arg APP_VERSION=1.8.2 -t "$DOCKERHUB_NAMESPACE/universal-subtitle-translator-frontend:1.8.2" --push ./frontend
docker buildx imagetools inspect "$DOCKERHUB_NAMESPACE/universal-subtitle-translator-backend:1.8.2"
docker buildx imagetools inspect "$DOCKERHUB_NAMESPACE/universal-subtitle-translator-frontend:1.8.2"
```

If a named builder already exists, select it with `docker buildx use ust-release`. Do not claim publication until both manifests are confirmed. Stable `latest` tags are optional and should be updated only after validating the versioned images. Do not use `latest` as a substitute for recording the version or digest of an installed image.
