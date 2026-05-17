from fastapi.templating import Jinja2Templates

from app.config import project_footer


def configure_templates(templates: Jinja2Templates) -> Jinja2Templates:
    templates.env.globals["project_footer"] = project_footer()
    return templates
