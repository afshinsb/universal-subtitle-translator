"""Authenticated automation console and token-authenticated import adapters."""
import base64
import hmac
import json
from urllib.parse import urlparse

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from app.services import automation, daily_budget, resources
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
        "resources": resources.status(), "config": cfg, "queue": automation.list_queue(), "counts": automation.counts(),
        "provider_ready": bool(automation.settings.openai_api_key), "budget": daily_budget.status(),
        "roots_text": "\n".join(cfg["roots"]),
        "allowed_files_text": "\n".join(cfg.get("allowed_files", [])),
        "mappings_text": json.dumps(cfg["path_mappings"], indent=2),
    })


@router.get("/status")
def status():
    cfg = automation.config()
    return {"enabled": cfg["enabled"], "roots": cfg["roots"], "scope_mode": cfg.get("scope_mode", "libraries"), "allowed_files": cfg.get("allowed_files", []), "counts": automation.counts(),
            "resources": resources.status(), "provider_ready": bool(automation.settings.openai_api_key), "budget": daily_budget.status(), "discovery_mode": cfg.get("discovery_mode", "reconcile_libraries"), "queue": automation.list_queue()}


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
        if service == "bazarr":
            selected = [path for path in selected if automation.accepts_subtitle_event(path)]
            if not selected:
                return {"status": "ignored", "reason": "Waiting for a media import; historical subtitles are not queued."}
        items = [automation.enqueue(str(path), service) for path in selected]
    except (ValueError, TypeError, AttributeError) as exc:
        raise HTTPException(422, str(exc)) from exc
    return {"status": "accepted", "queue_ids": [item["id"] for item in items]}
