"""Optional event relay; install/configure in services only after explicit approval."""
import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path


def build_event(service, video=None, language="en"):
    if service == "bazarr":
        if not video:
            raise ValueError("Bazarr requires --video with its {episode} media path.")
        return {"eventType": "SubtitleDownloaded", "video_path": video,
                "language": language.split(":")[0].split(".")[0].lower()}
    event = os.getenv(service + "_eventtype", "Download")
    if event == "Test":
        return {"eventType": "Test"}
    key = "episodeFile" if service == "sonarr" else "movieFile"
    video = video or os.getenv(service + ("_episodefile_path" if service == "sonarr" else "_moviefile_path"))
    if not video:
        raise ValueError("The complete imported media path is required.")
    return {"eventType": event, key: {"path": video}}


def deliver(url, service, payload, token, attempts=3):
    request = urllib.request.Request(url.rstrip("/") + "/automation/hooks/" + service,
        data=json.dumps(payload).encode(), method="POST",
        headers={"Content-Type": "application/json", "X-Automation-Key": token})
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                return json.load(response)
        except urllib.error.HTTPError as exc:
            if exc.code < 500:
                raise RuntimeError(f"Automation event rejected (HTTP {exc.code}).") from None
        except urllib.error.URLError:
            pass
        if attempt + 1 < attempts:
            time.sleep(min(2**attempt, 8))
    raise RuntimeError("Automation endpoint unavailable; re-deliver this exact import or reconcile an approved selected file.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--service", choices=["sonarr", "radarr", "bazarr"], required=True)
    parser.add_argument("--video")
    parser.add_argument("--language", default="en")
    parser.add_argument("--url", default=os.getenv("UST_AUTOMATION_URL", ""))
    parser.add_argument("--token-file", default=os.getenv("UST_AUTOMATION_TOKEN_FILE"))
    args = parser.parse_args()
    try:
        token = Path(args.token_file).read_text().strip() if args.token_file else os.getenv("UST_AUTOMATION_TOKEN", "")
        if not args.url or not token:
            raise ValueError("Configure UST_AUTOMATION_URL and a private token file or UST_AUTOMATION_TOKEN.")
        result = deliver(args.url, args.service, build_event(args.service, args.video, args.language), token)
        print(json.dumps(result))
        return 0
    except (ValueError, OSError, RuntimeError) as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
