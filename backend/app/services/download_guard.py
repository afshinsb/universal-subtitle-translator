"""Optional, bounded qBittorrent guard. Never removes files through the filesystem."""
import hashlib
import json
import logging
import os
import stat
import threading
import time
import urllib.parse
from pathlib import PurePosixPath

from app.config import settings
from app.database import get_connection, utc_now
from app.services import media_intake

logger = logging.getLogger(__name__)
CATEGORIES = {'tv-sonarr': 'sonarr', 'radarr': 'radarr'}
DANGEROUS = {'.exe', '.scr', '.bat', '.cmd', '.ps1', '.msi', '.com', '.vbs', '.js', '.lnk'}
# Any potential media prevents deletion; filename alone never proves playability.
MEDIA = {'.mkv', '.mp4', '.avi', '.mov', '.m4v', '.ts', '.m2ts', '.webm', '.wmv', '.mpeg', '.mpg', '.iso', '.vob', '.ogg', '.3gp'}


def init_schema():
    with get_connection() as conn:
        conn.execute('''CREATE TABLE IF NOT EXISTS download_guard_config (
            id INTEGER PRIMARY KEY CHECK(id=1), enabled INTEGER, auto_remove INTEGER,
            last_scan TEXT, last_error TEXT DEFAULT '', owner TEXT, lease_until REAL DEFAULT 0,
            offset INTEGER DEFAULT 0)''')
        conn.execute('INSERT OR IGNORE INTO download_guard_config(id,enabled,auto_remove) VALUES(1,?,0)',
                     (settings.download_guard_enabled,))
        conn.execute('''CREATE TABLE IF NOT EXISTS download_guard_seen (
            hash TEXT PRIMARY KEY, signature TEXT, first_seen REAL, deleted INTEGER DEFAULT 0)''')
        conn.execute('''CREATE TABLE IF NOT EXISTS download_guard_activity (
            id INTEGER PRIMARY KEY, timestamp TEXT, hash TEXT, name TEXT,
            action TEXT, reason TEXT, identity TEXT UNIQUE)''')


def configure(enabled, auto_remove):
    with get_connection() as conn:
        old = conn.execute('SELECT * FROM download_guard_config WHERE id=1').fetchone()
        if auto_remove and not old['last_scan']:
            raise ValueError('Complete a dry-run scan before enabling automatic removal.')
        conn.execute('UPDATE download_guard_config SET enabled=?,auto_remove=? WHERE id=1', (enabled,auto_remove))


def activity(torrent, action, reason):
    identity = hashlib.sha256(json.dumps([torrent.get('hash'), action, reason]).encode()).hexdigest()
    with get_connection() as conn:
        conn.execute('''INSERT OR IGNORE INTO download_guard_activity(timestamp,hash,name,action,reason,identity)
            VALUES(?,?,?,?,?,?)''', (utc_now(),torrent.get('hash',''),torrent.get('name',''),action,reason,identity))
        conn.execute('DELETE FROM download_guard_activity WHERE id NOT IN (SELECT id FROM download_guard_activity ORDER BY id DESC LIMIT 500)')


def file_paths(torrent, files):
    """Map only qBittorrent's configured completed-download root, rejecting links."""
    root = settings.download_guard_root
    prefix = PurePosixPath(settings.download_guard_qbit_root)
    if not root or not root.is_dir() or root.is_symlink():
        raise ValueError('Read-only completed-download mount unavailable')
    save = PurePosixPath(torrent.get('save_path',''))
    if not save.is_absolute() or '..' in save.parts or '\\' in str(save):
        raise ValueError('Unsafe save path')
    relative = save.relative_to(prefix)
    paths = []
    for entry in files:
        name = PurePosixPath(entry['name'])
        if name.is_absolute() or '..' in name.parts or '\\' in entry['name'] or not name.parts:
            raise ValueError('Unsafe torrent file path')
        path = root/relative/name
        # lstat each component; never resolve through a symlink.
        current = root
        for part in (*relative.parts,*name.parts):
            current = current/part
            if current.is_symlink():
                raise ValueError('Symlink in torrent path')
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size != entry['size']:
            raise ValueError('Non-regular, shared/hardlinked, or size-mismatched torrent file')
        paths.append(path)
    return paths


def classify(torrent, files):
    if torrent.get('category') not in CATEGORIES:
        return False,'Unrelated download category; ignored'
    suffixes = [PurePosixPath(f.get('name','')).suffix.lower() for f in files]
    if not any(s in DANGEROUS for s in suffixes):
        return False,'No executable/script detected; no deletion'
    if any(s in MEDIA for s in suffixes):
        return False,'Mixed or potentially playable media; report only'
    if not files or not all(s in DANGEROUS for s in suffixes):
        return False,'Ambiguous mixed content; report only'
    if torrent.get('progress',0)!=1 or torrent.get('amount_left',1)!=0 or not all(f.get('progress',0)==1 for f in files):
        return False,'Active or incomplete download; report only'
    if torrent.get('state') not in {'pausedUP','stoppedUP','stalledUP','uploading','queuedUP'}:
        return False,'Torrent is checking, moving, incomplete or errored; report only'
    try:
        paths=file_paths(torrent,files)
        for path in paths:
            # Tiny format confirmation, never execute or hash downloaded contents.
            fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
            with os.fdopen(fd,'rb') as stream:
                header=stream.read(512)
            suffix=path.suffix.lower()
            confirmed = (suffix in {'.exe','.scr'} and header.startswith(b'MZ')
                         or suffix=='.msi' and header.startswith(bytes.fromhex('d0cf11e0a1b11ae1'))
                         or suffix=='.lnk' and header.startswith(bytes.fromhex('4c00000001140200')))
            if not confirmed:
                return False,'Executable extension without conclusive file-format evidence; report only'
    except (ValueError,OSError,KeyError) as exc:
        return False,'Unsafe or unavailable file path: '+str(exc)
    return True,'Completed executable-only torrent; file formats and paths verified'


def rejected_by_arr(torrent):
    """Fresh authoritative failed import AND no accepted import for this hash."""
    service = CATEGORIES[torrent['category']]
    with get_connection() as conn:
        if conn.execute('SELECT 1 FROM media_intake WHERE lower(download_id)=lower(?) LIMIT 1', (torrent['hash'],)).fetchone():
            return False
    result = media_intake.api(service,'api/v3/queue?page=1&pageSize=1000&includeUnknownMovieItems=true&includeUnknownSeriesItems=true')
    records=[r for r in result.get('records',[]) if str(r.get('downloadId','')).lower()==torrent['hash'].lower()]
    return bool(records) and all(str(r.get('status','')).lower()=='completed'
        and str(r.get('trackedDownloadStatus','')).lower() in {'warning','error'}
        and str(r.get('trackedDownloadState','')).lower() in {'importpending','importfailed'}
        and any('no files found' in str(m).lower() or 'no video files' in str(m).lower() or 'no eligible files' in str(m).lower()
                for e in r.get('statusMessages',[]) for m in e.get('messages',[])) for r in records)


def fingerprint(torrent, files):
    paths=file_paths(torrent,files)
    metadata=[(str(p),p.stat().st_dev,p.stat().st_ino,p.stat().st_size,p.stat().st_mtime_ns) for p in paths]
    return hashlib.sha256(json.dumps([torrent['category'],torrent['save_path'],
        [(f['name'],f['size'],f['progress']) for f in files],metadata],sort_keys=True).encode()).hexdigest()


def inspect(torrent, auto_remove=False, owner=None):
    if torrent.get('category') not in CATEGORIES:
        activity(torrent,'ignored','Unrelated download category; ignored')
        return
    hash_value=torrent.get('hash','')
    if len(hash_value) not in {40,64} or any(c not in '0123456789abcdefABCDEF' for c in hash_value):
        activity(torrent,'failed','Invalid torrent identity')
        return
    files=media_intake.api('qbit','api/v2/torrents/files?'+urllib.parse.urlencode({'hash':hash_value}))
    valid,reason=classify(torrent,files)
    suspicious=any(PurePosixPath(f.get('name','')).suffix.lower() in DANGEROUS for f in files)
    if not valid:
        activity(torrent,'detected' if suspicious else 'ignored',reason)
        return
    signature=fingerprint(torrent,files)
    with get_connection() as conn:
        old=conn.execute('SELECT * FROM download_guard_seen WHERE hash=?',(hash_value,)).fetchone()
        if not old or old['signature']!=signature:
            conn.execute('INSERT INTO download_guard_seen VALUES(?,?,?,0) ON CONFLICT(hash) DO UPDATE SET signature=excluded.signature,first_seen=excluded.first_seen', (hash_value,signature,time.time()))
            old=None
    if not rejected_by_arr(torrent):
        activity(torrent,'detected',reason+'; Arr has not confirmed an invalid/no-video import, no removal')
        return
    if not auto_remove or not old or time.time()-old['first_seen']<300:
        activity(torrent,'detected',reason+'; Arr rejected import; dry-run/stability hold')
        return
    # Re-fetch identity, completion, file list and import state immediately before API deletion.
    current=media_intake.api('qbit','api/v2/torrents/info?'+urllib.parse.urlencode({'hashes':hash_value}))
    fresh_files=media_intake.api('qbit','api/v2/torrents/files?'+urllib.parse.urlencode({'hash':hash_value}))
    if len(current)!=1 or current[0]['hash']!=hash_value or fresh_files!=files or not classify(current[0],fresh_files)[0] or fingerprint(current[0],fresh_files)!=signature or not rejected_by_arr(current[0]):
        activity(torrent,'detected','Torrent or import state changed before cleanup; no removal')
        return
    with get_connection() as conn:
        enabled=conn.execute('SELECT enabled,auto_remove,owner,lease_until FROM download_guard_config WHERE id=1').fetchone()
    if not enabled['enabled'] or not enabled['auto_remove'] or owner and (enabled['owner']!=owner or enabled['lease_until']<=time.time()):
        return
    media_intake.qbit_request('api/v2/torrents/delete',{'hashes':hash_value,'deleteFiles':'true'})
    if media_intake.api('qbit','api/v2/torrents/info?'+urllib.parse.urlencode({'hashes':hash_value})):
        raise RuntimeError('qBittorrent deletion not confirmed; no filesystem cleanup attempted')
    with get_connection() as conn:
        conn.execute('UPDATE download_guard_seen SET deleted=1 WHERE hash=?',(hash_value,))
    activity(torrent,'deleted',reason+'; Arr confirmed no-video import rejection; qBittorrent removed torrent and data')


def scan():
    with get_connection() as conn:
        conn.execute('BEGIN IMMEDIATE')
        cfg=conn.execute('SELECT * FROM download_guard_config WHERE id=1').fetchone()
        if not cfg['enabled'] or cfg['lease_until']>time.time():
            return
        owner=str(time.time())
        conn.execute('UPDATE download_guard_config SET owner=?,lease_until=? WHERE id=1',(owner,time.time()+300))
    error=''
    try:
        # Max 20 file lists/category each scan; persistent rotating offset.
        next_offset=cfg['offset']+20
        for category in CATEGORIES:
            torrents=media_intake.api('qbit','api/v2/torrents/info?'+urllib.parse.urlencode({'category':category,'limit':20,'offset':cfg['offset'],'sort':'hash'}))
            if len(torrents)<20:
                next_offset=0
            for torrent in torrents:
                try:
                    with get_connection() as conn:
                        conn.execute('UPDATE download_guard_config SET lease_until=? WHERE id=1 AND owner=?',(time.time()+300,owner))
                    inspect(torrent,bool(cfg['auto_remove']),owner)
                except Exception as exc:
                    activity(torrent,'failed',type(exc).__name__+': '+str(exc))
        with get_connection() as conn:
            conn.execute('UPDATE download_guard_config SET offset=? WHERE id=1 AND owner=?',(next_offset,owner))
            conn.execute('DELETE FROM download_guard_seen WHERE first_seen<? AND deleted=0',(time.time()-30*86400,))
    except Exception as exc:
        error=type(exc).__name__+': '+str(exc)
        logger.warning('Download Guard scan deferred: %s',type(exc).__name__)
    finally:
        with get_connection() as conn:
            conn.execute('UPDATE download_guard_config SET last_scan=?,last_error=?,owner=NULL,lease_until=0 WHERE id=1 AND owner=?',(utc_now(),error,owner))


def snapshot():
    with get_connection() as conn:
        cfg=dict(conn.execute('SELECT enabled,auto_remove,last_scan,last_error FROM download_guard_config WHERE id=1').fetchone())
        cfg['recent']=[dict(r) for r in conn.execute('SELECT * FROM download_guard_activity ORDER BY id DESC LIMIT 20')]
        cfg['suspicious_count']=conn.execute("SELECT COUNT(DISTINCT hash) FROM download_guard_activity WHERE action='detected' AND hash NOT IN(SELECT hash FROM download_guard_seen WHERE deleted=1)").fetchone()[0]
        cfg['removed_count']=conn.execute('SELECT COUNT(*) FROM download_guard_seen WHERE deleted=1').fetchone()[0]
    return cfg


class Worker:
    def __init__(self):
        self.stop_event=threading.Event()
        self.thread=None

    def start(self):
        if not self.thread:
            self.stop_event.clear()
            self.thread=threading.Thread(target=self.run,daemon=True)
            self.thread.start()

    def run(self):
        while not self.stop_event.wait(300):
            try:
                scan()
            except Exception:
                logger.exception('Download Guard deferred')

    def stop(self):
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=2)
        self.thread=None


worker=Worker()
