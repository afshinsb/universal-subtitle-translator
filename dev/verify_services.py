"""Read-only service probes from the dev network; keys remain transient and unprinted."""
import json
import re
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path
requests = []
for service, port in [("sonarr",8989),("radarr",7878)]:
    key = ET.parse(f"/opt/containers/{service}/config/config.xml").getroot().findtext("ApiKey")
    requests.append({"service":service,"url":f"http://prime-host:{port}/api/v3/system/status","headers":{"X-Api-Key":key}})
config = Path("/opt/containers/bazarr/config/config/config.yaml").read_text()
match = re.search(r"(?m)^\s*apikey:\s*['\"]?([A-Za-z0-9]+)", config)
requests.append({"service":"bazarr","url":"http://prime-host:6767/api/system/status","headers":{"X-API-KEY":match.group(1)} if match else {}})
requests.extend([
    {"service":"jellyfin","url":"http://prime-host:8096/System/Info/Public","headers":{}},
    {"service":"qbittorrent","url":"http://prime-host:8080/api/v2/app/version","headers":{}},
])
program = """
import json,sys,urllib.request,urllib.error
results=[]
for probe in json.load(sys.stdin):
    req=urllib.request.Request(probe["url"],headers=probe["headers"],method="GET")
    try:
        with urllib.request.urlopen(req,timeout=10) as response:
            status=response.status
            body=response.read()
        try:
            data=json.loads(body)
            version=data.get("version",data.get("Version"))
        except Exception:
            version=None
        result={"service":probe["service"],"http_status":status,"authenticated":bool(probe["headers"]),"version":version}
    except urllib.error.HTTPError as exc:
        result={"service":probe["service"],"http_status":exc.code,"authenticated":bool(probe["headers"])}
    except Exception as exc:
        result={"service":probe["service"],"error":type(exc).__name__}
    results.append(result)
print(json.dumps(results))
assert all(r.get("http_status")==200 for r in results if r["service"]!="qbittorrent"), results
assert results[-1].get("http_status") in {200,401,403}, results
"""
subprocess.run(["docker","exec","-i","ust-dev-backend","python","-c",program],input=json.dumps(requests),text=True,check=True)
