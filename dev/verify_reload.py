"""Prove source/template/asset changes are served and restore every edit."""
import json
import time
import urllib.request
from pathlib import Path
root = Path(__file__).resolve().parents[1]
main = root / "backend/app/main.py"
original = main.read_bytes()
marker = "prime-reload-verified"
def health():
    return json.load(urllib.request.urlopen("http://127.0.0.1:2289/health", timeout=3))
def await_marker(expected):
    for attempt in range(45):
        try:
            if health().get("development_reload_probe") == expected:
                return
        except Exception:
            pass
        time.sleep(1)
    raise AssertionError("Reload did not serve expected source")
try:
    changed = original.decode().replace('"status": "ok",', '"status": "ok",\n        "development_reload_probe": "' + marker + '",')
    assert changed != original.decode()
    main.write_text(changed)
    await_marker(marker)
finally:
    main.write_bytes(original)
await_marker(None)
template = root / "backend/app/templates/login.html"
original = template.read_bytes()
try:
    urllib.request.urlopen("http://127.0.0.1:2289/login").read()
    template.write_bytes(original + b"\n<!-- prime-template-probe -->\n")
    page = urllib.request.urlopen("http://127.0.0.1:2289/login").read()
    assert b"prime-template-probe" in page
finally:
    template.write_bytes(original)
asset = next((root / "backend/app/static").rglob("*.css"))
original = asset.read_bytes()
try:
    asset.write_bytes(original + b"\n/* prime-asset-probe */\n")
    relative = asset.relative_to(root / "backend/app/static").as_posix()
    page = urllib.request.urlopen("http://127.0.0.1:2289/static/" + relative).read()
    assert b"prime-asset-probe" in page
finally:
    asset.write_bytes(original)
print(json.dumps({"python_reload":"passed; edit restored", "template_refresh":"passed; edit restored", "static_refresh":"passed; edit restored"}))
