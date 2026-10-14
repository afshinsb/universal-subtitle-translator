"""Simulated event delivery from disposable probes on actual service networks."""
import argparse
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser()
parser.add_argument("phase", choices=["imports","completion","duplicates"])
args = parser.parse_args()
manifest = json.loads((ROOT/"dev/runtime/data/integration-fixtures.json").read_text())
token = subprocess.check_output(["docker","exec","ust-dev-backend","python","-c",
    "from app.services.automation import config; print(config()['webhook_token'])"],text=True).strip()
program = """
import json,sys,urllib.request,urllib.error,http.server,threading
sys.path.insert(0,"/relay")
from automation_event import deliver
job=json.load(sys.stdin)
token=job["token"]
base="http://ust-events"
def probe(path, payload=None, auth=None):
    req=urllib.request.Request(base+path,data=json.dumps(payload).encode() if payload is not None else None,
        headers={"Content-Type":"application/json",**({"X-Automation-Key":auth} if auth else {})})
    try:
        with urllib.request.urlopen(req,timeout=10) as response:
            return response.status,response.read()
    except urllib.error.HTTPError as exc:
        return exc.code,exc.read()
assert probe("/automation/status")[0]==404
assert probe("/login")[0]==404
assert probe("/automation/hooks/sonarr",{"eventType":"Test"})[0]==401
assert probe("/automation/hooks/sonarr",{"eventType":"Test"},"wrong-token")[0]==401
assert probe("/automation/hooks/sonarr",{"eventType":"Test"},token)[0]==200
if job["phase"]=="imports":
    if job["service"]=="sonarr":
        payload={"eventType":"Rename","episodeFiles":[{"path":path} for path in job["paths"]]}
    elif job["service"]=="radarr":
        payload={"eventType":"Download","movieFile":{"path":job["paths"][0]}}
    else:
        payload={"eventType":"Test"}
elif job["phase"]=="completion":
    payload={"eventType":"SubtitleDownloaded","video_path":job["paths"][1],"language":"en"}
else:
    payload={"eventType":"Download","episodeFile":{"path":job["paths"][0]},"episodes":[{"episodeNumber":1},{"episodeNumber":2}]} if job["service"]=="sonarr" else {"eventType":"Download","movieFile":{"path":job["paths"][0]}}
result=deliver(base,job["service"],payload,token)
repeat=deliver(base,job["service"],payload,token)
assert result==repeat
class Handler(http.server.BaseHTTPRequestHandler):
    attempts=0
    def do_POST(self):
        type(self).attempts+=1
        self.rfile.read(int(self.headers["Content-Length"]))
        self.send_response(503 if self.attempts<3 else 200)
        self.end_headers()
        self.wfile.write(b'{"status":"accepted"}')
    def log_message(self,*args):
        pass
if job["phase"]=="imports":
    server=http.server.HTTPServer(("127.0.0.1",0),Handler)
    threading.Thread(target=server.serve_forever,daemon=True).start()
    assert deliver("http://127.0.0.1:"+str(server.server_port),job["service"],payload,token)["status"]=="accepted"
    assert Handler.attempts==3
    server.shutdown()
    try:
        deliver("http://127.0.0.1:9",job["service"],payload,token,attempts=1)
        raise AssertionError("Expected failed delivery")
    except RuntimeError:
        pass
    real=probe("/automation/hooks/radarr",{"eventType":"Download","movieFile":{"path":"/movies/Not Selected.mkv"}},token)
    assert real[0]==200 and json.loads(real[1])["status"]=="ignored"
print(json.dumps({"network":job["service"]+"_default","phase":job["phase"],"event":result,
    "duplicate":"same IDs","auth":"enforced","dashboard":"blocked","failed_delivery":"verified" if job["phase"]=="imports" else "previously verified"}))
"""
services = ["bazarr"] if args.phase=="completion" else ["sonarr","radarr","bazarr"] if args.phase=="imports" else ["sonarr","radarr"]
for service in services:
    paths = ["/movies/ust-fixtures/Fixture Film (2026).mkv"] if service=="radarr" else [
        "/tv/ust-fixtures/Fixture Show - S01E01.mkv","/tv/ust-fixtures/Fixture Show - S01E02.mkv","/tv/ust-fixtures/Fixture Show - S01E03.mkv"]
    payload = {"token":token,"service":service,"phase":args.phase,"paths":paths}
    subprocess.run(["docker","run","--rm","-i","--network",service+"_default","--name","ust-dev-probe-"+service,
        "--memory","128m","--cpus","0.25","--cap-drop","ALL","--security-opt","no-new-privileges",
        "-v",str(ROOT/"scripts")+":/relay:ro","--entrypoint","python","ust-dev-backend:1.8.2-5568f9e","-c",program],
        input=json.dumps(payload),text=True,check=True)
gateway=json.loads(subprocess.check_output(["docker","inspect","ust-dev-events"]))[0]
assert not gateway["HostConfig"]["PortBindings"]
print("Gateway has no host-published ports.")
