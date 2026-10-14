# Repository audit and patch release 1.8.2

Audit date: 2026-10-14. Starting commit: `ca3f891` (`Fix batch progress and add subtitle credits`). Scope: tracked backend, templates/static frontend, Docker/Compose, tests, demo and documentation. Existing functionality was retained; no real media, live database or credentials were used for verification. No production container was restarted or replaced.

## Architecture and health

The project is a small, working Python application with a useful existing test suite and clear service boundaries. It needed fixes around subtitle identity, silent data loss, resource ownership and release reproducibility. It does not need a framework migration or UI redesign.

- **Backend:** FastAPI/Jinja2, synchronous SQLite access with WAL, background daemon threads, and a per-batch `ThreadPoolExecutor` capped at ten files. One process/replica is supported by the in-memory activity and cancellation sets.
- **Provider:** OpenAI only; configurable model, Chat Completions, `temperature=0.1`, indexed `BEGIN[i] ... END[i]` blocks and `<LB>` for line breaks. No provider was removed or added. The SDK handles transient retries; application retries check alignment and Persian-script output.
- **Media:** ffprobe discovers text tracks; FFmpeg extracts SRT. Source language is detected with filename/script/word heuristics. There is no audio transcription or bitmap-subtitle OCR.
- **Persistence:** SQLite history, uploads, browser outputs and temporary extractions under app data; mounted writable media keeps translated sidecars beside the video. Read-only media uses the existing output-directory fallback.
- **Frontend/deployment:** Nginx proxies HTTP/SSE to FastAPI, both on a private Compose network; frontend publishes port 2288. `demo/` is a separate simulated static site.
- **Releases before this change:** `VERSION`, config defaults and Compose all said `1.8.1`. Local tags and `git ls-remote --tags origin` showed `v1.3.0` and `v1.2.0`; recent commits included `Release v1.8.0` and an untagged 1.8.1 bump. No `.github` workflow existed. Docker Hub instructions used an unspecified owner. No application image publication was established.

## End-to-end workflow traced

1. A browser upload is streamed with a size limit into `UPLOAD_DIR/<job-id>/`; an SRT enters translation directly. A video enters the same media inspection used by batch mode. Browser outputs use `OUTPUT_DIR/<job-id>/`.
2. Batch mode accepts a video or recursively walks a folder within optional `MEDIA_ROOT`. Preview scans are asynchronous and cached briefly in memory; execution rescans and applies any selected file list.
3. Existing target sidecars or extractable embedded target-language tracks skip by default. Matching external SRT is preferred, with English first in the language preference. Otherwise an embedded text track is selected. Full, non-commentary tracks now win over forced/commentary tracks in the same language, then the default disposition, then stream index.
4. Embedded extraction produces an English/source-language SRT next to writable media, otherwise under `TEMP_DIR/extracted`. Failed extraction removes only its own unique temporary file. It cannot overwrite an existing sidecar.
5. SRT parsing, source detection and batching retain actual cue IDs and timestamps. Duplicate IDs fail safely. Every batch travels through the existing OpenAI prompt contract. Missing/empty outputs retry and repair; repeated duplicate, shifted, reordered or malformed IDs fail without publishing an incomplete result.
6. Text is wrapped with language-aware punctuation/direction rules while protecting markup tags. The existing language validation and translation credits remain. UTF-8 output publishes atomically; overwrite-disabled publication cannot replace a file created concurrently.
7. SQLite records status, progress and token counts. Cancellation checks prevent a late provider response from saving output. Restart recovery marks stale jobs interrupted; there is no partial translation checkpoint/resume. Re-running skips completed outputs.

## Confirmed issues ranked by impact

No confirmed Critical issue was established. Severity reflects this application and its default deployment, not a claim that every upstream advisory was exploitable.

| Severity | Evidence in 1.8.1 | Implemented correction |
| --- | --- | --- |
| High | Docker published on all host interfaces; `DEV_MODE` defaulted true; shipped `admin` credentials and a public session secret were accepted. In production mode the login form rejected defaults, but middleware still trusted a cookie signed with that same known secret. | Docker defaults to production checks and localhost binding. Middleware applies auth setup checks before trusting a session. Strong credentials are required in the example; intentional LAN/dev settings remain configurable. Forged-cookie and login regressions cover this path. |
| High | `write_srt` used unconditional `os.replace` after a separate existence check. A concurrent job/process could replace completed user output with overwrite disabled. | Atomic no-replace publication with `os.link`; in-process output claims and early existence checks prevent redundant requests. A failed save leaves the existing file intact. |
| High | `pysrt.open` default `ERROR_PASS` silently discarded malformed cues. Valid cues could be translated and reported complete while dialogue was missing. BOM-marked UTF-16/UTF-32 also returned no cues. | Strict parse errors and BOM-aware decoding, with mixed-valid/broken and Unicode fixture tests. Supported legacy decoding remains. |
| Medium | Glob matching `Movie*.srt` included `Movie2.fa.srt` and treated brackets in a movie title as a pattern. That could skip a valid movie or translate the wrong sidecar. Uppercase `.SRT` would be missed on Linux. | Literal complete-stem/dot-boundary matching, case-insensitive suffix checks, full-title removal before language parsing, and strict known-language aliases. |
| Medium | Correct cue IDs with empty translated text passed alignment, and validation allowed empty output. | Empty translations now enter the existing bounded retry/repair path and must be non-empty before saving. |
| Medium | The first English stream always won, including a forced-only/signs track even when a full default track existed. | Carry ffprobe disposition flags into same-language selection. Real FFmpeg smoke uses two English streams and verifies full-track selection. |
| Medium | `with sqlite3.connect(...)` committed but did not close connections. The standalone Windows smoke completed translation but then failed to remove its locked SQLite database. | A managed connection context now rolls back/commits and explicitly closes, including on exceptions. Smoke cleanup and rollback/closed-handle tests pass. |
| Medium | FFmpeg wrote directly to the final extraction path and deleted that path on failure. Unique concurrent extractions and pre-existing sidecars were not protected. | Extract to a unique `.srt`, atomically publish without replacement, use `-nostdin`, and close child process pipes. Failure regression preserves existing data. |
| Medium | No Python dependency versions/hashes were committed. The existing local environment contained affected AnyIO, IDNA, multipart and Starlette versions. | Compatible dependency lines, universal hash-locked runtime/dev requirements, and advisory checks. See dependency details below; local installed versions do not establish the versions in any deployed image. |
| Medium | Backend ran as root with no UID/GID strategy. README suggested a read-only mount for a workflow expected to save alongside videos. | Non-root runtime, configurable numeric UID/GID, explicit writable media instructions and documented upgrade ownership preparation. The read-only fallback stays supported. |
| Medium | Nginx resolved the backend once, so replacing only the backend could leave its old IP cached. | Docker DNS resolver with periodic refresh and a variable upstream. Container runtime verification remains pending the daemon. |
| Low | `hmac.compare_digest` on Unicode strings raised `TypeError`; a legitimate non-ASCII login could fail with 500. | Compare UTF-8 bytes; authenticated route test with Persian credentials. |
| Low | Model-readiness checks looked only for raw `OPENAI_MODEL`, rejecting the valid default. Temp-directory writability/timeouts/upload/concurrency settings were not all checked. | Validate effective model settings, temp writability and numeric bounds. Startup model check closes its client and disables retries to honor its short budget. |
| Low | Persian retry token accounting retained only one request's usage. Provider clients were not explicitly closed; error text could echo the configured key. | Count both requests, close clients and redact the configured key from user-visible job failures. Regression tests cover each. |
| Low | Fallback output directories replaced all Unicode characters with `_`, causing distinct folder names to collide. Formatting-tag attributes could also be split by line wrapping. | Preserve source folder names and protect tags while wrapping. |
| Low | Old `.env` `APP_VERSION` could label a new image with the old version; no CI, rollback procedure or verified publishing path existed. | Consistent patch version/image selection, build labels, read-only CI, precise install/update/rollback instructions and explicit publication limitations. |

## Changes and modernization boundaries

Reliability fixes live in the existing subtitle, media, translator, job and database modules. The only new production coordination is a lock-protected set of active output paths. Existing prompt/provider contracts, language/style choices, per-job uploads, batch UI, naming and credits are retained. No transcription, provider expansion, new persistent job framework or resumable translation feature was introduced.

FastAPI startup uses the supported lifespan interface; shutdown marks active work cancelled so a late reply cannot write another completed file. Startup repair still handles hard kills. Static assets resolve relative to their module rather than the launch directory. Templates and user-facing layouts remain intact. Tests receive isolated temporary paths and disable `.env` loading and external provider creation.

Inspection found duplicated presentation helpers (`public_job` in two routers), small compatibility wrapper functions, and the intentional separate demo. They were retained because removing them did not address a demonstrated runtime defect. There was no evidence justifying broad dead-code removal or a rewrite. The old Uvicorn `standard` extras were removed from the dependency request: this app does not use WebSocket/reload/watchfile support; HTTP and SSE use plain Uvicorn. Existing route/provider behavior is unchanged.

## Dependencies and compatibility

The source previously used unversioned requirements. The before column below is the existing local Python 3.10 environment inspected at audit start, not a historical lockfile or deployed image inventory.

| Dependency | Before (local) | Release lock |
| --- | --- | --- |
| FastAPI | 0.136.1 | 0.136.1 retained |
| Starlette | 1.0.0 | 1.3.1 |
| OpenAI SDK | 2.36.0 | 2.54.0, stays on major 2 |
| Uvicorn | 0.46.0 with standard extras | 0.46.0 without unused extras |
| python-multipart | 0.0.28 | 0.0.32 |
| python-dotenv | 1.2.2 | 1.2.4 |
| Jinja2 / itsdangerous / pysrt | 3.1.6 / 2.2.0 / 1.1.2 | retained |
| AnyIO / IDNA | 4.13.0 / 3.14 | 4.15.1 / 3.20 |
| Pydantic | 2.13.4 | 2.14.1 |
| pytest | 9.0.3 | 9.1.1 |

All transitive runtime versions and distribution SHA256 hashes are in `backend/requirements.txt`. Dev tools and runtime constraints are frozen in `requirements-dev.txt`; `.in` files explain the selected compatibility lines. Locks were generated with uv 0.13.1 for universal Python 3.10+ resolution and installed with hash verification. Python 3.10 and 3.12 both passed tests. Latest major SDK/framework releases were not adopted merely because they existed.

The advisory service reported 11 distinct advisory IDs across four runtime packages in the inspected old environment: AnyIO (2), IDNA (1), multipart (3), Starlette (5). It also flagged the old environment's pip/setuptools build tools. Duplicate advisory rows were not counted twice. Runtime and dev locks each returned **no known vulnerabilities** on 2026-10-14. This is an advisory lookup, not proof of absence or an attack-path validation of every dependency finding. No container OS vulnerability scan could run without Docker.

Primary package metadata used for compatibility/version checks: [FastAPI](https://pypi.org/project/fastapi/0.136.1/), [Starlette](https://pypi.org/project/starlette/1.3.1/), [OpenAI SDK](https://pypi.org/project/openai/2.54.0/), [multipart](https://pypi.org/project/python-multipart/0.0.32/). The actual dependency install and regression results establish local compatibility.

## Docker audit and release behavior

- Python base: `3.12-slim` → `3.12.15-slim-bookworm`, pinned to the verified manifest-list digest. The dependency stage freezes build tooling and installs hash-checked runtime packages. No compilers, build tooling or test dependencies are copied into the runtime virtualenv.
- Nginx base: `1.27-alpine` → `1.30.5-alpine`, pinned to its manifest-list digest. This is an application base-image update, not a host Docker Engine change. The tag is listed in the [official Nginx image](https://hub.docker.com/_/nginx).
- Both selected base manifests include Linux amd64/arm64. That confirms base availability, not a successful application cross-build. CI is configured to exercise both architectures; arm64 runtime smoke is still outstanding.
- Backend has a non-root default and Compose UID/GID override, `init`, no extra capabilities, no privilege escalation and a shutdown grace period. The image itself defines writable `/app/data` defaults for standalone startup as well as Compose. Frontend retains the official Nginx startup model; it sets no-new-privileges and rotating logs. Both keep meaningful HTTP liveness checks and `unless-stopped` restarts.
- Default public bind is localhost, credentials are required for production use, FFmpeg/ffprobe remain runtime dependencies, and no GPU is introduced. Existing bind-mounted data and media paths stay in place. User-data ownership changes are operator-run and documented.
- Modern Compose syntax is retained. Optional `env_file.required` sets the documented [Compose v2.24.0 minimum](https://docs.docker.com/compose/how-tos/environment-variables/set-environment-variables/). Both local-build and pull-only configurations validate without printing credentials.
- Existing root/backend `.dockerignore` files already excluded secrets, data, environments and caches from their actual contexts; no defect was established there. Frontend uses explicit `COPY nginx.conf` and has no local data. The initial build-context concern was discarded after reading the backend ignore file.
- Runtime hashes and base digests improve repeatability. Debian FFmpeg/security packages still come from live apt repositories; image layers are not claimed byte-for-byte reproducible, and final image size was not measured.
- Version moves **1.8.1 → 1.8.2** consistently across `VERSION`, native defaults, Docker build args/labels, image tags, Compose and docs. `IMAGE_TAG` controls the Docker version; an obsolete `.env` `APP_VERSION` no longer hides an update. No schema migration is required.
- Registry namespace/credentials were not established and the existing docs used placeholders. No registry publishing workflow was invented, no tags were pushed, and no image was published. The added read-only CI pins action revisions and builds/tests without registry access. Manual publication and manifest verification are documented for an authorized maintainer.

## Verification actually performed

| Check | Actual result |
| --- | --- |
| Original suite before changes | 47 passed on the pre-existing Python 3.10 environment, from its documented backend working directory. An initial repository-root invocation failed module discovery; root pytest configuration now fixes that. |
| Regressions before fixes | 12 new failures reproduced wrong subtitle matching/selection, UTF-16/32 loss, silent malformed-cue loss, missing no-overwrite support and accepted blank model translations. Other added tests were run after their focused fixes. |
| Updated full suite | 79 passed on Python 3.12.10 and 79 passed on Python 3.10.6 with the new locked dependencies. |
| Ruff / static compilation | `ruff check backend scripts` and `compileall` passed. |
| Dependency consistency | `pip check` passed in the new Python 3.12 environment. |
| Runtime and dev advisory checks | Both locks returned no known vulnerabilities; hash-verified installation succeeded in the isolated environments. |
| Native media smoke | Passed using real installed FFmpeg/ffprobe, a synthetic MKV with forced/full English tracks, real SDK parsing over a local in-memory transport, SQLite and actual UTF-8 SRT files. Exact dialogue times were preserved: 2125–3250 and 4375–5500 ms. Repeat run skipped without changing the result or making another provider call. Its initial Windows database-cleanup failure revealed and led to the connection fix. |
| HTTP/auth | TestClient verified multipart SRT upload through background translation and download with the original filename/timestamps, Unicode login, private API access, production rejection of default-secret signed cookies/disabled auth and public health. |
| Data protection | Tests checked no-replace saves, failed extraction preservation, duplicate active-output rejection, cancellation after provider reply, rollback/closure of DB handles, source naming, timestamps and existing cleanup/restart behavior. |
| Compose/CI syntax | Both Compose files passed `config -q` with `.env.example`; pull-only validation used a harmless fixture namespace. CI YAML parsed with both expected jobs. No real `.env` was displayed. |
| Base image metadata | Docker Hub registry API confirmed the exact Python/Nginx tags, digest lists and amd64/arm64 availability. |
| Docker builds | Both backend and frontend builds were attempted and blocked at daemon connection: missing `dockerDesktopLinuxEngine` pipe. No build success is claimed. |
| Container smoke/Nginx networking/image size/OS scan/arm64 build | Not run locally because the Linux Docker daemon is unavailable. CI definitions and operator commands are present, but their remote execution has not been observed. |
| Real model translation | Not attempted; no paid calls or production credentials were used. Translation quality, billing/quota and real model access remain unverified. |

Two upstream test-only deprecation warnings remain: Starlette's TestClient HTTPX compatibility path and AnyIO's BlockingPortal alias. They do not fail the tests; introducing an additional HTTP client stack solely to silence them was deferred.

## Exact operator procedures

[README](../README.md#fresh-docker-compose-installation) supplies clone/configure/build/start/media-output commands. [OPERATIONS.md](OPERATIONS.md) supplies exact stopped backups, tagged rollback images, non-root migration, source/pull updates, version verification, rollback and credential-free container smoke commands. The procedures preserve `.env`, mounted video directories, app data and existing subtitles; they do not require host Docker upgrades or deleting volumes.

## Remaining work by value

1. **Release gate:** run the new CI and a Docker-enabled host smoke, including fresh Linux mount ownership, frontend/backend restart behavior and an arm64 runtime check. Then perform one explicitly authorized real-model sample and confirm the registry manifests if publishing.
2. **Operations:** establish the actual image owner and release credentials/conventions before adding automated publishing. Keep the previous deployed image digest and private data backup for rollback.
3. **Large interrupted jobs:** checkpoint/resume would reduce repeated model spend, but needs source/model/config fingerprints and a persistent state contract. It is intentionally not added in this patch.
4. **Scaling:** a shared queue/coordination model is needed before supporting multiple workers/replicas or enforcing a global provider rate budget. Current controls remain per batch/process.
5. **Filesystem coverage:** test read-only and no-hard-link NAS/CIFS targets, cached extraction invalidation after source changes, and fallback outputs across separately scanned roots with identical names. Preserve existing names and user files when designing any change.
6. **Quality/maintenance:** consider a confidence-aware language detector, more model-output/markup fixtures and legacy encoding controls. Keep frozen Python/base dependencies under periodic review. `pysrt` is old but remains compatible and was not replaced without a demonstrated need.
