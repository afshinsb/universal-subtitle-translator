"""Prime-only production backup, immutable deployment and scoped rollback.

Run from the verified main checkout. Private artifacts contain credentials and
must never enter Git. The original production data remains untouched after stop.
"""
import argparse
import hashlib
import json
import os
import secrets
import subprocess
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path('/home/afshin/projects/universal-subtitle-translator')
PROD = Path('/opt/containers/ust-production')
PROJECT = 'universal-subtitle-translator'
PORTAINER = '/var/lib/docker/volumes/portainer_data/_data'
IMAGE = 'ust-dev-backend:1.8.2-5568f9e'


def run(*args, capture=False):
    return subprocess.check_output(args, text=True) if capture else subprocess.check_call(args)


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def private(path, value):
    path.write_text(json.dumps(value, indent=2) if not isinstance(value, str) else value)
    path.chmod(0o600)


def root_python(code, mounts):
    args = ['docker', 'run', '--rm', '--network', 'none', '--user', '0:0']
    for source, target, readonly in mounts:
        args += ['-v', f'{source}:{target}' + (':ro' if readonly else '')]
    return run(*args, '--entrypoint', 'python', IMAGE, '-c', code)


def compose(path, *args):
    run('docker', 'compose', '-p', PROJECT, '--project-directory', '/data/compose/14', '-f', str(path), *args)


def original_compose(containers):
    services = {}
    for item in containers:
        name = item['Config']['Labels']['com.docker.compose.service']
        svc = {'image': item['Image'], 'container_name': item['Name'].lstrip('/'),
               'environment': dict(v.split('=', 1) for v in item['Config']['Env']),
               'restart': item['HostConfig']['RestartPolicy']['Name'],
               'volumes': [m['Source'] + ':' + m['Destination'] + (':ro' if not m['RW'] else '') for m in item['Mounts']]}
        for field, key in [('Cmd', 'command'), ('Entrypoint', 'entrypoint'), ('User', 'user')]:
            if item['Config'].get(field):
                svc[key] = item['Config'][field]
        ports = []
        for container, binds in (item['HostConfig']['PortBindings'] or {}).items():
            for bind in binds:
                ports.append((bind['HostIp'] or '0.0.0.0') + ':' + bind['HostPort'] + ':' + container.split('/')[0])
        if ports:
            svc['ports'] = ports
        services[name] = svc
    return {'services': services, 'networks': {'default': {'name': PROJECT + '_default', 'external': True}}}


def backup():
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    dest = Path('/tank/share/ust-backups') / stamp
    dest.mkdir(mode=0o700, parents=True)
    containers = json.loads(run('docker', 'inspect', 'subtitle-translator-backend', 'subtitle-translator-frontend', capture=True))
    private(dest / 'containers.json', containers)
    private(dest / 'rollback-compose.json', original_compose(containers))
    private(dest / 'all-start-times.json', {i['Name']: i['State']['StartedAt'] for i in json.loads(run('docker', 'inspect', *run('docker', 'ps', '-q', capture=True).split(), capture=True))})
    for service, item in zip(('backend', 'frontend'), containers):
        tag = f'ust-rollback-{service}:1.4.0-{stamp}'
        run('docker', 'tag', item['Image'], tag)
        run('docker', 'image', 'save', '-o', str(dest / f'{service}-1.4.0.tar'), tag)
    # Portainer metadata is read-only. Verify the copied Bolt DB matches its source.
    root_python("""import shutil, pathlib, hashlib, os
p=pathlib.Path('/portainer'); b=pathlib.Path('/backup')
shutil.copytree(p/'compose'/'14',b/'stack14')
shutil.copyfile(p/'portainer.db',b/'portainer.db')
assert hashlib.sha256((p/'portainer.db').read_bytes()).digest()==hashlib.sha256((b/'portainer.db').read_bytes()).digest()
for f in b.rglob('*'):
 os.chown(f,1000,1000)
 if f.is_file(): f.chmod(0o600)
""", [(PORTAINER, '/portainer', True), (dest, '/backup', False)])
    run('docker', 'stop', 'subtitle-translator-frontend', 'subtitle-translator-backend')
    try:
        root_python("""import tarfile,pathlib,os,shutil,sqlite3,hashlib,json
b=pathlib.Path('/backup'); source=pathlib.Path('/original')
with tarfile.open(b/'production-data.tar','w') as t: t.add(source,arcname='data')
with tarfile.open(b/'production-data.tar') as t: t.extractall(b/'restore-rehearsal',filter='fully_trusted')
restored=b/'restore-rehearsal'/'data'
def digest(f):
 with f.open('rb') as stream: return hashlib.file_digest(stream,'sha256').hexdigest()
def inventory(root):
 return {str(f.relative_to(root)):digest(f) for f in root.rglob('*') if f.is_file()}
assert inventory(source)==inventory(restored)
manifest=inventory(source)
conn=sqlite3.connect(restored/'app.db'); assert conn.execute('PRAGMA integrity_check').fetchone()[0]=='ok'; conn.close()
(b/'source-manifest.json').write_text(json.dumps(manifest,indent=2))
new=pathlib.Path('/production'); new.mkdir(exist_ok=True)
assert not (new/'data').exists(), 'Production copy already exists; never overwrite'
shutil.copytree(restored,new/'data')
(new/'fixtures').mkdir(exist_ok=True)
for root in (b,new):
 for f in [root,*root.rglob('*')]:
  os.chown(f,1000,1000)
  if root==b and f.is_file(): f.chmod(0o600)
new.chmod(0o700)
""", [('/data/compose/14/data', '/original', True), (dest, '/backup', False), ('/opt/containers', '/containers', False), (PROD, '/production', False)])
        private(dest / 'backup-sha256.json', {p.name: digest(p) for p in dest.glob('*.tar')})
        private(ROOT / 'dev/runtime/production-backup-path', str(dest))
        print(json.dumps({'backup': str(dest), 'data_restore': 'verified', 'production': 'stopped for cutover'}))
        return dest
    except BaseException:
        run('docker', 'start', 'subtitle-translator-backend', 'subtitle-translator-frontend')
        raise


def prepare(dest, revision):
    containers = json.loads((dest / 'containers.json').read_text())
    env = dict(v.split('=', 1) for v in containers[0]['Config']['Env'])
    for key in ('PATH', 'LANG', 'GPG_KEY', 'PYTHON_VERSION', 'PYTHON_SHA256'):
        env.pop(key, None)  # Preserve app settings, not the old image's interpreter path.
    if not env.get('OPENAI_API_KEY'):
        raise RuntimeError('Existing production provider key is missing.')
    env.update(APP_VERSION='1.8.2', DEV_MODE='false', DEMO_MODE='false', AUTH_ENABLED='true',
               OPENAI_MODEL='gpt-6-luna', OPENAI_REASONING_EFFORT='medium', OPENAI_MAX_COMPLETION_TOKENS='32768',
               OPENAI_DAILY_BUDGET_USD='5', OPENAI_BUDGET_INPUT_CEILING_PER_1M='0.125', OPENAI_BUDGET_OUTPUT_PER_1M='0.5',
               OPENAI_INPUT_COST_PER_1M='0.125', OPENAI_OUTPUT_COST_PER_1M='0.5',
               MEDIA_ROOT='/media', AUTOMATION_REAL_LIBRARY_PROCESSING='false', AUTOMATION_ALLOW_LIBRARY_WRITES='true',
               AUTOMATION_JOB_CONCURRENCY='2', AUTOMATION_API_CONCURRENCY='4', AUTOMATION_BATCH_CONCURRENCY='2',
               AUTOMATION_INITIAL_COMPLETION_TOKENS='16384', BATCH_FILE_CONCURRENCY='1',
               DEFAULT_STYLE='natural_conversational', SRT_BATCH_SIZE='40', SRT_MAX_CHARS='12000')
    if not env.get('ADMIN_PASSWORD') or env['ADMIN_PASSWORD'] == 'admin':
        env['ADMIN_PASSWORD'] = secrets.token_urlsafe(24)
    if len(env.get('SESSION_SECRET', '')) < 32 or env.get('SESSION_SECRET', '').startswith('default-'):
        env['SESSION_SECRET'] = secrets.token_urlsafe(48)
    images = {service: run('docker', 'image', 'inspect', f'ust-release-{service}:{revision}', '--format', '{{.Id}}', capture=True).strip() for service in ('backend','frontend')}
    logging = {'driver': 'json-file', 'options': {'max-size':'10m','max-file':'3'}}
    services = {
        'backend': {'image':images['backend'], 'container_name':'subtitle-translator-backend',
            'user':'1000:1000', 'init':True, 'environment':env, 'volumes':[
                str(PROD/'data')+':/app/data', str(PROD/'fixtures')+':/media/fixtures',
                '/tank/share/media/movies:/media/movies', '/tank/share/media/shows:/media/shows'],
            'cpus':1.5, 'mem_limit':'1024m', 'pids_limit':192, 'restart':'unless-stopped',
            'cap_drop':['ALL'], 'security_opt':['no-new-privileges:true'], 'logging':logging,
            'stop_grace_period':'45s', 'healthcheck':{'test':['CMD','python','-c',"import urllib.request; urllib.request.urlopen('http://127.0.0.1:2288/health',timeout=3)"], 'interval':'15s','timeout':'5s','start_period':'20s','retries':3}},
        'frontend': {'image':images['frontend'], 'container_name':'subtitle-translator-frontend',
            'environment':{'BACKEND_PORT':'2288','NGINX_CLIENT_MAX_BODY_SIZE':'10G'}, 'ports':['0.0.0.0:2288:80'],
            'mem_limit':'128m','cpus':.5,'restart':'unless-stopped','logging':logging,
            'security_opt':['no-new-privileges:true'],'depends_on':{'backend':{'condition':'service_healthy'}}},
        'events': {'image':images['frontend'], 'container_name':'ust-prod-events',
            'entrypoint':['nginx','-g','daemon off;'], 'volumes':[str(PROD/'events-nginx.conf')+':/etc/nginx/conf.d/default.conf:ro'],
            'mem_limit':'64m','cpus':.25,'restart':'unless-stopped','logging':logging,
            'security_opt':['no-new-privileges:true'], 'networks':['default','sonarr','radarr','bazarr'],
            'healthcheck':{'test':['CMD-SHELL','wget -q -O /dev/null http://127.0.0.1/health'],'interval':'15s','timeout':'3s','retries':3}}
    }
    networks = {'default':{'name':PROJECT+'_default','external':True}, **{s:{'name':s+'_default','external':True} for s in ('sonarr','radarr','bazarr')}}
    private(PROD/'compose.json', {'services':services,'networks':networks})
    private(PROD/'provider-env.json', env)
    private(PROD/'release.json', {'revision':revision,'images':images,'backup':str(dest)})
    private(PROD/'events-nginx.conf', (ROOT/'dev/events-nginx.conf').read_text())
    compose(PROD/'compose.json', 'config', '--quiet')


def rollback(dest):
    # Keep new data and spending ledgers intact, even when the old app returns.
    compose(PROD/'compose.json', 'stop')
    compose(PROD/'compose.json', 'rm', '-f')
    root_python("import shutil; shutil.copyfile('/backup/stack14/docker-compose.yml','/portainer/compose/14/docker-compose.yml')",
                [(dest,'/backup',True),(PORTAINER,'/portainer',False)])
    compose(dest/'rollback-compose.json', 'up', '-d', '--pull', 'never', '--wait', '--wait-timeout','120')


def deploy(dest):
    try:
        root_python("import shutil; shutil.copyfile('/production/compose.json','/portainer/compose/14/docker-compose.yml')",
                    [(PROD,'/production',True),(PORTAINER,'/portainer',False)])
        compose(PROD/'compose.json', 'up', '-d', '--pull', 'never', '--wait','--wait-timeout','120')
    except BaseException:
        rollback(dest)
        raise


def main():
    os.umask(0o077)
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('phase', choices=['backup','prepare','deploy','rollback'])
    p.add_argument('--revision')
    p.add_argument('--backup')
    args = p.parse_args()
    if args.phase == 'backup':
        backup()
        return
    dest = Path(args.backup or (ROOT/'dev/runtime/production-backup-path').read_text())
    if args.phase == 'prepare':
        prepare(dest, args.revision)
    elif args.phase == 'deploy':
        deploy(dest)
    else:
        rollback(dest)


if __name__ == '__main__':
    main()
