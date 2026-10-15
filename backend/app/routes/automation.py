"""Authenticated automation console and token-authenticated import adapters."""
import base64
import hmac
import json
from urllib.parse import urlparse

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from app.services import automation, daily_budget, resources, media_intake, download_guard, ui_state
from app.template_context import configure_templates

router = APIRouter(prefix="/automation")
templates = configure_templates(Jinja2Templates(directory="app/templates"))


def check_origin(request):
    origin = request.headers.get("origin")
    if origin and urlparse(origin).netloc != request.url.netloc:
        raise HTTPException(403, "Cross-origin changes are not allowed.")


@router.get("")
def dashboard(request: Request):
    cfg = automation.config()
    return templates.TemplateResponse(request=request, name="automation.html", context={
        "guard": download_guard.snapshot(), "active_model": automation.settings.openai_model, "active_reasoning": automation.settings.openai_reasoning_effort or "default", "intake": media_intake.snapshot(), "resources": resources.status(), "config": cfg, "queue": ui_state.redacted(automation.list_queue()), "counts": automation.counts(),
        "provider_ready": bool(automation.settings.openai_api_key), "budget": daily_budget.status(),
        "roots_text": "\n".join(cfg["roots"]),
        "allowed_files_text": "\n".join(cfg.get("allowed_files", [])),
        "mappings_text": json.dumps(cfg["path_mappings"], indent=2),
    })


@router.get("/status")
def status():
    cfg = automation.config()
    return ui_state.redacted({"enabled": cfg["enabled"], "roots": cfg["roots"], "scope_mode": cfg.get("scope_mode", "libraries"), "allowed_files": cfg.get("allowed_files", []), "counts": automation.counts(),
            "guard": download_guard.snapshot(), "intake": media_intake.snapshot(), "resources": resources.status(), "provider_ready": bool(automation.settings.openai_api_key), "budget": daily_budget.status(), "discovery_mode": cfg.get("discovery_mode", "reconcile_libraries"), "queue": automation.list_queue()})


@router.post("/settings")
def update_settings(request: Request, enabled: bool = Form(False),
                    roots: str = Form(""), path_mappings: str = Form("{}"),
                    discovery_mode: str = Form("reconcile_libraries")):
    check_origin(request)
    try:
        automation.save_config(enabled, [line.strip() for line in roots.splitlines() if line.strip()],
                               json.loads(path_mappings), discovery_mode)
    except (ValueError, TypeError) as exc:
        raise HTTPException(422, str(exc)) from exc
    return RedirectResponse("/automation", status_code=303)


@router.post("/pause")
def pause(request: Request):
    check_origin(request)
    cancelled = automation.pause()
    if "text/html" in request.headers.get("accept", ""):
        return RedirectResponse("/automation", status_code=303)
    return {"paused": True, "cancel_requested": cancelled}


@router.post("/scope")
def scope(request: Request, allowed_files: str = Form(""), scope_mode: str = Form("selected_files")):
    check_origin(request)
    try:
        automation.save_scope([line.strip() for line in allowed_files.splitlines() if line.strip()], scope_mode)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return RedirectResponse("/automation", status_code=303)


@router.post("/scan")
def scan(request: Request):
    check_origin(request)
    return {"discovered": automation.reconcile()}


@router.post("/queue/{item_id}/retry")
def retry(request: Request, item_id: str):
    check_origin(request)
    try:
        automation.retry(item_id)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return RedirectResponse("/automation", status_code=303)


@router.post("/intake/{item_id}/retry")
def retry_intake(request: Request, item_id: str):
    check_origin(request)
    try:
        media_intake.retry(item_id)
    except ValueError as exc:
        raise HTTPException(409,str(exc)) from exc
    return RedirectResponse("/automation",status_code=303)


@router.post("/queue/{item_id}/cancel")
def cancel(request: Request, item_id: str):
    check_origin(request)
    try:
        automation.cancel(item_id)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return RedirectResponse("/automation", status_code=303)


@router.post("/hooks/{service}")
async def webhook(service: str, request: Request):
    if service not in {"sonarr", "radarr", "bazarr"}:
        raise HTTPException(404, "Unknown integration.")
    supplied = request.headers.get("x-automation-key", "")
    # Sonarr/Radarr Webhook connections support HTTP Basic authentication.
    authorization = request.headers.get("authorization", "")
    if authorization.lower().startswith("basic "):
        try:
            username, password = base64.b64decode(authorization[6:], validate=True).decode().split(":", 1)
            if username == "automation":
                supplied = password
        except (ValueError, UnicodeDecodeError):
            supplied = ""
    expected = automation.config()["webhook_token"]
    if not supplied or not hmac.compare_digest(supplied.encode(), expected.encode()):
        raise HTTPException(401, "Invalid automation integration token.")
    body = bytearray()
    async for chunk in request.stream():
        if len(body) + len(chunk) > 65536:
            raise HTTPException(413, "Event payload is too large.")
        body.extend(chunk)
    try:
        payload = json.loads(body)
        if not isinstance(payload, dict):
            raise ValueError("Expected a JSON event object.")
        event = payload.get("eventType", "")
        if event == "Test":
            return {"status": "ok", "test": True}
        if service == "bazarr":
            if event != "SubtitleDownloaded":
                return {"status": "ignored"}
            if str(payload.get("language", "en")).lower() not in {"en", "eng", "english"}:
                return {"status": "ignored", "reason": "Only English completion events are needed."}
            paths = [payload.get("video_path")]
        else:
            if event not in {"Download", "Rename", "MovieFileImport", "EpisodeFileImport"}:
                return {"status": "ignored"}
            key = "episodeFile" if service == "sonarr" else "movieFile"
            media = payload.get(key)
            files = [media] if isinstance(media, dict) else payload.get(key + "s", [])
            if not isinstance(files, list):
                raise ValueError("Event media files must be a list.")
            paths = [entry.get("path") for entry in files if isinstance(entry, dict)]
        if not paths or not all(isinstance(path, str) and path for path in paths):
            raise ValueError("Event must include the complete imported video path.")
        # Validate every path before accepting any part of a multi-file event.
        mapped = [automation.map_path(path) for path in paths]
        if any(path.suffix.lower() not in automation.VIDEO_EXTENSIONS for path in mapped):
            raise ValueError("Event paths must identify supported video files.")
        selected = [path for path in mapped if automation.permitted_file(path)]
        if not selected:
            return {"status": "ignored", "reason": "Outside selected processing scope or real processing disabled."}
        if automation.settings.media_intake_enabled:
            if service == "bazarr":
                ids = [item_id for path in selected if (item_id := media_intake.wake(path))]
                if not ids:
                    return {"status": "ignored", "reason": "No imported media intake; historical subtitles are not queued."}
            else:
                ids = []
                for path in selected:
                    event_payload = dict(payload)
                    key = "episodeFile" if service == "sonarr" else "movieFile"
                    candidates = payload.get(key+"s", [])
                    if candidates:
                        event_payload[key] = next((f for f in candidates if automation.map_path(f["path"]) == path), {})
                    ids.append(media_intake.ingest(service,event_payload,path))
            return {"status": "accepted", "intake_ids": ids}
        if service == "bazarr":
            selected = [path for path in selected if automation.accepts_subtitle_event(path)]
            if not selected:
                return {"status": "ignored", "reason": "Waiting for a media import; historical subtitles are not queued."}
        items = [automation.enqueue(str(path), service) for path in selected]
    except (ValueError, TypeError, AttributeError) as exc:
        raise HTTPException(422, str(exc)) from exc
    return {"status": "accepted", "queue_ids": [item["id"] for item in items]}


@router.post("/download-guard/settings")
def guard_settings(request: Request, enabled: bool = Form(False), auto_remove: bool = Form(False), confirm_remove: bool = Form(False)):
    check_origin(request)
    try:
        if auto_remove and not download_guard.snapshot()["auto_remove"] and not confirm_remove:
            raise ValueError("Confirm strict automatic torrent/data removal before enabling.")
        download_guard.configure(enabled,auto_remove)
    except ValueError as exc:
        raise HTTPException(422,str(exc)) from exc
    return RedirectResponse("/automation",status_code=303)


@router.post("/download-guard/scan",status_code=202)
def guard_scan(request:Request):
    check_origin(request)
    if 'qbit' not in media_intake.services():
        raise HTTPException(409,'Configure the private qBittorrent connection before scanning.')
    download_guard.worker.request_scan()
    return {"status":"requested","dry_run":True}


@router.post('/integration-token')
def integration_token(request:Request):
    check_origin(request)
    from fastapi.responses import JSONResponse
    return JSONResponse({'token':automation.config()['webhook_token']},headers={'Cache-Control':'no-store'})
