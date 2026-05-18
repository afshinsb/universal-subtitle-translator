import hmac
from urllib.parse import urlparse

from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from app.config import auth_config_checks, settings
from app.template_context import configure_templates

router = APIRouter()
templates = configure_templates(Jinja2Templates(directory="app/templates"))


def safe_next_url(next_url: str | None) -> str:
    if not next_url:
        return "/"

    parsed = urlparse(next_url)

    if parsed.scheme or parsed.netloc or not next_url.startswith("/"):
        return "/"

    if next_url.startswith("//") or next_url.startswith("/login") or next_url.startswith("/logout"):
        return "/"

    return next_url


def auth_setup_errors() -> list[dict]:
    return [
        check
        for check in auth_config_checks()
        if check["blocking"] and not check["ok"]
    ]


@router.get("/login")
def login_page(request: Request, next: str | None = None):
    if not settings.auth_enabled:
        return RedirectResponse(url="/", status_code=303)

    next_url = safe_next_url(next)

    if request.session.get("authenticated") is True:
        return RedirectResponse(url=next_url, status_code=303)

    return templates.TemplateResponse(
        request=request,
        name="login.html",
        context={
            "next_url": next_url,
            "error": "",
            "setup_errors": auth_setup_errors(),
        },
    )


@router.post("/login")
def login_submit(
    request: Request,
    username: str = Form(""),
    password: str = Form(""),
    next: str | None = Form(None),
):
    if not settings.auth_enabled:
        return RedirectResponse(url="/", status_code=303)

    next_url = safe_next_url(next)
    setup_errors = auth_setup_errors()

    if setup_errors:
        return templates.TemplateResponse(
            request=request,
            name="login.html",
            context={
                "next_url": next_url,
                "error": "Login is not ready. Fix the setup items below, then restart the app.",
                "setup_errors": setup_errors,
            },
            status_code=503,
        )

    username_ok = hmac.compare_digest(username, settings.admin_username)
    password_ok = hmac.compare_digest(password, settings.admin_password or "")

    if not username_ok or not password_ok:
        return templates.TemplateResponse(
            request=request,
            name="login.html",
            context={
                "next_url": next_url,
                "error": "Invalid username or password.",
                "setup_errors": [],
            },
            status_code=401,
        )

    request.session.clear()
    request.session["authenticated"] = True
    request.session["username"] = settings.admin_username
    return RedirectResponse(url=next_url, status_code=303)


@router.post("/logout")
def logout_submit(request: Request):
    request.session.clear()
    return RedirectResponse(url="/login", status_code=303)


@router.get("/logout")
def logout_get(request: Request):
    request.session.clear()
    return RedirectResponse(url="/login", status_code=303)
