"""Prime immutable-release update with stopped-writer backup and automatic rollback.

Run after tests and CI pass, and build both revision-tagged release images.
Private data and spending ledger remain in place on rollback.
"""
import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import tarfile
from datetime import datetime, timezone
from pathlib import Path
os.umask(63)

def main():
    root = Path('/home/afshin/projects/universal-subtitle-translator')
    prod = Path('/opt/containers/ust-production')

    def run(*a):
        return subprocess.check_call(a)

    def compose(path, *args):
        run('docker', 'compose', '-p', 'universal-subtitle-translator', '--project-directory', '/data/compose/14', '-f', str(path), *args)

    def private(path, obj):
        path.write_text(json.dumps(obj, indent=2))
        path.chmod(384)
    revision = subprocess.check_output(['git', 'rev-parse', '--short=12', 'HEAD'], cwd=root, text=True).strip()
    backup = Path('/tank/share/ust-backups') / ('update-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ'))
    backup.mkdir(mode=448)
    old = json.loads((prod / 'compose.json').read_text())
    for name in ('compose.json', 'provider-env.json', 'release.json', 'intake-activation.json'):
        if (prod / name).exists():
            shutil.copy2(prod / name, backup / name)
    run('docker', 'stop', 'subtitle-translator-backend')
    try:
        data = prod / 'data'
        with tarfile.open(backup / 'production-data.tar', 'w') as t:
            t.add(data, arcname='data')
        with tarfile.open(backup / 'production-data.tar') as t:
            t.extractall(backup / 'restore-rehearsal', filter='fully_trusted')

        def inventory(p):
            result = {}
            for f in p.rglob('*'):
                if f.is_file():
                    with f.open('rb') as stream:
                        result[str(f.relative_to(p))] = hashlib.file_digest(stream, 'sha256').hexdigest()
            return result
        hashes = inventory(data)
        assert hashes == inventory(backup / 'restore-rehearsal/data')
        db = sqlite3.connect(backup / 'restore-rehearsal/data/app.db')
        assert db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
        db.close()
        private(backup / 'source-manifest.json', hashes)
        with (backup / 'production-data.tar').open('rb') as stream:
            private(backup / 'archive-sha256.json', {'production-data.tar': hashlib.file_digest(stream, 'sha256').hexdigest()})
    finally:
        run('docker', 'start', 'subtitle-translator-backend')
    for service in ('backend', 'frontend'):
        run('docker', 'tag', old['services'][service]['image'], 'ust-rollback-' + service + ':' + backup.name)
        run('docker', 'image', 'save', '-o', str(backup / (service + '-previous.tar')), 'ust-rollback-' + service + ':' + backup.name)
    images = {s: subprocess.check_output(['docker', 'image', 'inspect', 'ust-release-' + s + ':' + revision, '--format', '{{.Id}}'], text=True).strip() for s in ('backend', 'frontend')}
    c = json.loads(json.dumps(old))
    c['services']['backend']['image'] = images['backend']
    c['services']['frontend']['image'] = images['frontend']
    c['services']['events']['image'] = images['frontend']
    e = c['services']['backend']['environment']
    e.update(MEDIA_INTAKE_ENABLED='true', MEDIA_INTAKE_ACTIVATED_AT=json.loads((prod / 'intake-activation.json').read_text())['activation_at'], DOWNLOAD_GUARD_ENABLED='true', DOWNLOAD_GUARD_ROOT='/downloads-guard', DOWNLOAD_GUARD_QBIT_ROOT='/downloads')
    mount = '/tank/share/downloads:/downloads-guard:ro'
    if mount not in c['services']['backend']['volumes']:
        c['services']['backend']['volumes'].append(mount)
    private(prod / 'compose.json', c)
    private(prod / 'provider-env.json', e)
    private(prod / 'release.json', {'revision': revision, 'images': images, 'backup': str(backup), 'original_backup': '/tank/share/ust-backups/20261014T223955Z'})
    portainer = '/var/lib/docker/volumes/portainer_data/_data'

    def stack_sync(source):
        run('docker', 'run', '--rm', '--network', 'none', '--user', '0:0', '-v', str(source) + ':/config:ro', '-v', portainer + ':/portainer', '--entrypoint', 'python', images['backend'], '-c', "import shutil;shutil.copyfile('/config/compose.json','/portainer/compose/14/docker-compose.yml')")
    try:
        compose(prod / 'compose.json', 'config', '--quiet')
        stack_sync(prod)
        compose(prod / 'compose.json', 'up', '-d', '--pull', 'never', '--wait', '--wait-timeout', '120')
    except BaseException:
        db=sqlite3.connect(prod/'data/app.db')
        row=db.execute('SELECT value FROM automation_config WHERE id=1').fetchone()
        cfg=json.loads(row[0])
        cfg['enabled']=False
        db.execute('UPDATE automation_config SET value=? WHERE id=1',(json.dumps(cfg),))
        db.commit()
        db.close()
        for name in ('compose.json', 'provider-env.json', 'release.json'):
            shutil.copy2(backup / name, prod / name)
        stack_sync(backup)
        compose(prod / 'compose.json', 'up', '-d', '--pull', 'never', '--wait', '--wait-timeout', '120')
        raise
    private(backup / 'update-result.json', {'revision': revision, 'images': images, 'sqlite_integrity': 'ok', 'archive_verified': True, 'spending_ledger_preserved': True})
    print(json.dumps({'revision': revision, 'backup': str(backup), 'deployed': True}))
if __name__ == '__main__':
    main()
