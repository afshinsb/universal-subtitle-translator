from pathlib import Path

from fastapi.templating import Jinja2Templates
from jinja2 import FileSystemLoader

from app.config import project_footer, settings


def current_username(request) -> str:
    if not settings.auth_enabled:
        return ""

    try:
        if request.session.get("authenticated") is True:
            return str(request.session.get("username") or settings.admin_username)
    except AssertionError:
        return ""

    return ""


def configure_templates(templates: Jinja2Templates) -> Jinja2Templates:
    # Resolve the shared templates relative to source, independent of cwd.
    if getattr(templates.env.loader, "searchpath", None) == ["app/templates"]:
        templates.env.loader = FileSystemLoader(Path(__file__).parent / "templates")
    templates.env.globals["project_footer"] = project_footer()
    templates.env.globals["auth_enabled"] = settings.auth_enabled
    templates.env.globals["current_username"] = current_username
    return templates
