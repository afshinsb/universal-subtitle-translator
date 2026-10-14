"""Install production-only import hooks with private rollback snapshots."""
import argparse
import json
import os
import re
import shutil
import sqlite3
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

from prime_promote import ROOT, PROD, private


def api(service, path, method='GET', body=None, form=None):
    if service == 'bazarr':
        text = Path('/opt/containers/bazarr/config/config/config.yaml').read_text()
        key = re.search(r'^\s*apikey:\s*[\'"]?([^\s\'"#]+)', text, re.M).group(1)
        url = 'http://127.0.0.1:6767/api/'
    else:
        key = ET.parse(f'/opt/containers/{service}/config/config.xml').findtext('ApiKey')
        url = 'http://127.0.0.1:' + {'radarr':'7878','sonarr':'8989'}[service] + '/api/v3/'
    headers = {'X-Api-Key':key}
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        headers['Content-Type'] = 'application/json'
    if form is not None:
        data = urllib.parse.urlencode(form).encode()
        headers['Content-Type'] = 'application/x-www-form-urlencoded'
    with urllib.request.urlopen(urllib.request.Request(url+path, data=data, headers=headers, method=method), timeout=30) as response:
        content = response.read()
        return json.loads(content) if content else None


def snapshot(dest):
    for service in ('radarr','sonarr'):
        private(dest / f'{service}-notifications.json', api(service, 'notification'))
    private(dest/'bazarr-settings.json', api('bazarr','system/settings'))
    shutil.copyfile('/opt/containers/bazarr/config/config/config.yaml', dest/'bazarr-config.yaml')
    (dest/'bazarr-config.yaml').chmod(0o600)
    private(dest/'integration-created.json', {})


def rollback(dest):
    created = json.loads((dest/'integration-created.json').read_text())
    for service in ('radarr','sonarr'):
        if created.get(service):
            api(service, 'notification/'+str(created[service]), 'DELETE')
        for original in json.loads((dest/f'{service}-notifications.json').read_text()):
            if service == 'radarr' and original['id'] == 1:
                api(service,'notification/1','PUT',body=original)
    old = json.loads((dest/'bazarr-settings.json').read_text())['general']
    api('bazarr','system/settings','POST',form={
        'settings-general-use_postprocessing':str(old['use_postprocessing']).lower(),
        'settings-general-postprocessing_cmd':old.get('postprocessing_cmd') or ''})
    print(json.dumps({'hooks':'restored'}))


def activate(dest):
    snapshot(dest)
    created = {}
    try:
        with sqlite3.connect(PROD/'data/app.db') as conn:
            token = json.loads(conn.execute('SELECT value FROM automation_config WHERE id=1').fetchone()[0])['webhook_token']
        folder = Path('/opt/containers/subtitle-scripts/ust')
        folder.mkdir(mode=0o700, exist_ok=True)
        private(folder/'event.token', token)
        shutil.copyfile(ROOT/'scripts/automation_event.py', folder/'automation_event.py')
        (folder/'automation_event.py').chmod(0o644)
        for service in ('radarr','sonarr'):
            schema = next(n for n in api(service, 'notification/schema') if n['implementation']=='Webhook')
            for name in list(schema):
                if name.startswith('on'):
                    schema[name] = False
            schema.update(name='UST Persian — new imports', onDownload=True, onUpgrade=True)
            values = {'url':f'http://ust-prod-events/automation/hooks/{service}', 'method':1,
                      'username':'automation', 'password':token, 'headers':[]}
            for field in schema['fields']:
                field['value'] = values[field['name']]
            api(service,'notification/test','POST',body=schema)
            notification = api(service,'notification','POST',body=schema)
            created[service] = notification['id']
            private(dest/'integration-created.json',created)
        old = next((n for n in api('radarr','notification') if n['id']==1), None)
        if old:
            for name in list(old):
                if name.startswith('on'):
                    old[name] = False
            api('radarr','notification/1','PUT',body=old)
        command = 'python3 /scripts/ust/automation_event.py --service bazarr --url http://ust-prod-events --token-file /scripts/ust/event.token --video "{episode}" --language "{subtitles_language_code2}"'
        api('bazarr','system/settings','POST',form={
            'settings-general-use_postprocessing':'true', 'settings-general-postprocessing_cmd':command})
        result = api('bazarr','system/settings')['general']
        assert result['use_postprocessing'] and result['postprocessing_cmd']==command
        print(json.dumps({'radarr':created['radarr'],'sonarr':created['sonarr'],
                          'legacy_radarr':'disabled/preserved','bazarr':'English relay enabled'}))
    except BaseException:
        rollback(dest)
        raise


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase',choices=['activate','rollback','snapshot'])
    args = parser.parse_args()
    dest = Path((ROOT/'dev/runtime/production-backup-path').read_text())
    {'activate':activate,'rollback':rollback,'snapshot':snapshot}[args.phase](dest)


if __name__ == '__main__':
    main()
