"""Verify development authentication via the local frontend without printing secrets."""
import http.cookiejar
import json
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

base = "http://127.0.0.1:2289"
env = dict(line.split("=", 1) for line in Path(__file__).with_name(".env").read_text().splitlines() if "=" in line)
health = json.load(urllib.request.urlopen(base + "/health", timeout=10))
assert health["version"] == "1.8.2", health
try:
    urllib.request.urlopen(base + "/", timeout=10)
    raise AssertionError("Unauthenticated request accepted")
except urllib.error.HTTPError as exc:
    assert exc.code == 401
cookies = http.cookiejar.CookieJar()
client = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cookies))
bad = urllib.parse.urlencode({"username":env["ADMIN_USERNAME"],"password":"incorrect"}).encode()
try:
    client.open(base + "/login", bad, timeout=10)
    raise AssertionError("Incorrect password accepted")
except urllib.error.HTTPError as exc:
    assert exc.code == 401
good = urllib.parse.urlencode({"username":env["ADMIN_USERNAME"],"password":env["ADMIN_PASSWORD"]}).encode()
response = client.open(base + "/login", good, timeout=10)
assert response.status == 200
assert any(cookie.name == "ust_session" for cookie in cookies)
assert client.open(base + "/", timeout=10).status == 200
assert client.open(base + "/automation", timeout=10).status == 200
automation = json.load(client.open(base + "/automation/status", timeout=10))
assert not automation["enabled"]
assert automation["provider_ready"] == bool(env.get("OPENAI_API_KEY", "").strip())
assert "webhook_token" not in automation
print(json.dumps({"automation_page":200, "automation_counts":automation["counts"], "health":health,"unauthenticated":401,"wrong_password":401,"authenticated_page":200,"session_cookie":True}))
