"""Read-only upstream tracking and durable imported-file preparation.

Download completion is never translation eligibility. Only authenticated import
notifications or post-activation Arr import history can submit library files.
"""
import hashlib
import http.cookiejar
import json
import logging
import stat
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from app.config import settings
from app.database import get_connection, utc_now
from app.services import automation, resources
from app.services.ffmpeg_service import get_media_info, list_subtitle_streams

logger = logging.getLogger(__name__)


def init_schema():
    with get_connection() as conn:
        conn.execute('''CREATE TABLE IF NOT EXISTS media_intake (
            id TEXT PRIMARY KEY, video_path TEXT UNIQUE NOT NULL, service TEXT,
            title TEXT, media_ids TEXT, download_id TEXT, imported_at TEXT,
            state TEXT NOT NULL, signature TEXT DEFAULT '', stable_since REAL DEFAULT 0,
            source_path TEXT, source_hash TEXT, queue_id TEXT,
            next_run REAL DEFAULT 0, owner TEXT, lease_until REAL DEFAULT 0,
            attempts INTEGER DEFAULT 0, error TEXT DEFAULT '', updated_at TEXT)''')
        conn.execute('CREATE INDEX IF NOT EXISTS intake_updated ON media_intake(updated_at)')
        conn.execute('CREATE INDEX IF NOT EXISTS intake_due ON media_intake(state,next_run)')
        conn.execute('''CREATE TABLE IF NOT EXISTS media_events (
            identity TEXT PRIMARY KEY, intake_id TEXT, service TEXT, received_at TEXT)''')
        conn.execute('''CREATE TABLE IF NOT EXISTS intake_cursors (
            service TEXT PRIMARY KEY, activation_at TEXT NOT NULL, last_id INTEGER DEFAULT 0,
            upper_id INTEGER DEFAULT 0, page INTEGER DEFAULT 1,
            next_run REAL DEFAULT 0, failures INTEGER DEFAULT 0, error TEXT DEFAULT '')''')
        conn.execute('''CREATE TABLE IF NOT EXISTS upstream_activity (
            identity TEXT PRIMARY KEY, service TEXT, media_id TEXT, download_id TEXT,
            title TEXT, state TEXT, progress REAL, path TEXT, error TEXT,
            first_seen REAL, changed_at REAL, updated_at TEXT, replaced_by TEXT)''')
        conn.execute('CREATE INDEX IF NOT EXISTS upstream_updated ON upstream_activity(updated_at)')
        activation = settings.media_intake_activated_at or utc_now()
        for service in ('radarr','sonarr','seerr','jellyfin','qbit'):
            conn.execute('INSERT OR IGNORE INTO intake_cursors(service,activation_at) VALUES (?,?)', (service,activation))
        if settings.media_intake_enabled:
            # Only already accepted post-activation queue entries, never a library scan.
            pending=conn.execute("SELECT * FROM automation_queue WHERE origin IN ('sonarr','radarr') AND status IN ('queued','retry','waiting_media','waiting_source','waiting_config','waiting_budget')")
            for row in pending:
                item=conn.execute('SELECT id FROM media_intake WHERE video_path=?',(row['video_path'],)).fetchone()
                if not item:
                    conn.execute("INSERT INTO media_intake(id,video_path,service,title,media_ids,imported_at,state,queue_id,updated_at) VALUES (?,?,?,?,?,?,'validation_pending',?,?)", (uuid4().hex,row['video_path'],row['origin'],Path(row['video_path']).stem,'{}',row['created_at'],row['id'],utc_now()))
                    conn.execute("UPDATE automation_queue SET status='waiting_intake',owner=NULL,lease_until=0 WHERE id=?",(row['id'],))


def services():
    path = settings.data_dir/'media-services.json'
    return json.loads(path.read_text()) if path.is_file() else {}


_qbit_client = None


_qbit_lock = threading.Lock()


def qbit_request(route, data=None):
    """Shared authenticated qBittorrent transport; mutations used only by Guard."""
    global _qbit_client
    cfg=services()['qbit']
    with _qbit_lock:
        if _qbit_client is None:
            _qbit_client=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
            login=urllib.parse.urlencode({'username':cfg['username'],'password':cfg['password']}).encode()
            try:
                with _qbit_client.open(urllib.request.Request(cfg['url'].rstrip('/')+'/api/v2/auth/login',data=login),timeout=8) as response:
                    if response.read(100)!=b'Ok.':
                        raise RuntimeError('qBittorrent authentication unavailable.')
            except Exception:
                _qbit_client=None
                raise
        try:
            payload=urllib.parse.urlencode(data).encode() if data is not None else None
            request=urllib.request.Request(cfg['url'].rstrip('/')+'/'+route,data=payload)
            with _qbit_client.open(request,timeout=8) as response:
                content=response.read(2_000_001)
                if len(content)>2_000_000:
                    raise RuntimeError('qBittorrent response exceeded bounded polling size.')
                return json.loads(content) if data is None else content
        except urllib.error.HTTPError:
            _qbit_client=None
            raise


def api(service, route):
    cfg = services()[service]
    if service=='qbit':
        return qbit_request(route)
    headers = {'X-Api-Key':cfg['api_key']}
    if service == 'jellyfin':
        headers = {'Authorization':'MediaBrowser Token="'+cfg['api_key']+'", Client="UST", Device="Prime", DeviceId="ust-production"'}
    request = urllib.request.Request(cfg['url'].rstrip('/')+'/'+route.lstrip('/'),headers=headers)
    with urllib.request.urlopen(request,timeout=8) as response:
        content = response.read(2_000_001)
        if len(content)>2_000_000:
            raise RuntimeError('Upstream response exceeded bounded polling size.')
        return json.loads(content)


def ingest(service, payload, path, origin='webhook'):
    path = automation.checked_path(str(path))
    media = payload.get('movie') or payload.get('series') or {}
    file = payload.get('movieFile') or payload.get('episodeFile') or {}
    file_id = file.get('id') or (payload.get('data') or {}).get('fileId')
    if file_id is not None:
        file_id = int(file_id)
    ids = {'item':media.get('id'), 'file':file_id,
           'episodes':[e.get('id') for e in payload.get('episodes',[]) if isinstance(e,dict)]}
    title = media.get('title') or payload.get('sourceTitle') or path.stem
    imported = payload.get('date') or file.get('dateAdded') or utc_now()
    download = payload.get('downloadId') or (payload.get('data') or {}).get('downloadId')
    identity = hashlib.sha256(json.dumps([service,str(path),ids,download,imported if origin=='history' else file.get('id'),automation.signature(path)],sort_keys=True).encode()).hexdigest()
    with get_connection() as conn:
        conn.execute('BEGIN IMMEDIATE')
        old = conn.execute('SELECT * FROM media_intake WHERE video_path=?',(str(path),)).fetchone()
        item_id = old['id'] if old else uuid4().hex
        inserted = conn.execute('INSERT OR IGNORE INTO media_events VALUES (?,?,?,?)',(identity,item_id,service,utc_now())).rowcount
        if inserted:
            changed = old and old['signature'] and automation.signature(path)!=old['signature']
            if changed:
                conn.execute("UPDATE automation_queue SET status='waiting_intake',owner=NULL,lease_until=0,signature=?,message='Media upgraded; validating replacement' WHERE video_path=? AND status NOT IN ('done','skipped')", (automation.signature(path),str(path)))
            if not old:
                conn.execute('''INSERT INTO media_intake(id,video_path,service,title,media_ids,download_id,imported_at,state,updated_at)
                    VALUES (?,?,?,?,?,?,?,'validation_pending',?)''',(item_id,str(path),service,title,json.dumps(ids),download,imported,utc_now()))
            else:
                conn.execute('''UPDATE media_intake SET title=?,media_ids=?,download_id=?,updated_at=?,
                    state=CASE WHEN ? OR state IN ('invalid_media','preparation_failed','waiting_import','superseded') THEN 'validation_pending' ELSE state END,
                    next_run=0 WHERE id=?''',(title,json.dumps(ids),download,utc_now(),bool(changed),item_id))
            if download:
                conn.execute("UPDATE upstream_activity SET state='imported',path=?,replaced_by=?,updated_at=? WHERE service=? AND download_id=?",
                             (str(path),download,utc_now(),service,download))
        return item_id


def wake(path):
    with get_connection() as conn:
        row = conn.execute('SELECT id FROM media_intake WHERE video_path=?',(str(path),)).fetchone()
        if row:
            conn.execute("UPDATE media_intake SET next_run=0 WHERE id=? AND state='waiting_source'",(row['id'],))
        return row['id'] if row else None


def cached_source(path):
    if not settings.media_intake_enabled:
        return None
    with get_connection() as conn:
        row = conn.execute('SELECT * FROM media_intake WHERE video_path=?',(str(path),)).fetchone()
    if not row or row['signature']!=automation.signature(path) or not row['source_path']:
        return None
    source = Path(row['source_path'])
    if source.is_file() and hashlib.sha256(source.read_bytes()).hexdigest()==row['source_hash']:
        return source
    return None


def update(item, state, error='', delay=0, **fields):
    fields.update(state=state,error=error,next_run=time.time()+delay,owner=None,lease_until=0,updated_at=utc_now())
    with get_connection() as conn:
        conn.execute('UPDATE media_intake SET '+','.join(k+'=?' for k in fields)+' WHERE id=? AND owner=?',
                     [*fields.values(),item['id'],item['owner']])


def claim():
    with get_connection() as conn:
        conn.execute('BEGIN IMMEDIATE')
        conn.execute('UPDATE media_intake SET owner=NULL WHERE lease_until<?',(time.time(),))
        if conn.execute('SELECT COUNT(*) FROM media_intake WHERE owner IS NOT NULL AND lease_until>=?',(time.time(),)).fetchone()[0]>=2:
            return None
        row = conn.execute("""SELECT * FROM media_intake WHERE owner IS NULL AND next_run<=?
            AND state IN ('validation_pending','waiting_stable','waiting_import','waiting_source')
            ORDER BY imported_at LIMIT 1""",(time.time(),)).fetchone()
        if not row:
            return None
        owner = uuid4().hex
        conn.execute('UPDATE media_intake SET owner=?,lease_until=? WHERE id=?',(owner,time.time()+300,row['id']))
        return dict(conn.execute('SELECT * FROM media_intake WHERE id=?',(row['id'],)).fetchone())


def prepare_one():
    if not automation.config()["enabled"]:
        return False
    item = claim()
    if not item:
        return False
    heartbeat_stop = threading.Event()
    def heartbeat():
        while not heartbeat_stop.wait(15):
            with get_connection() as conn:
                conn.execute('UPDATE media_intake SET lease_until=? WHERE id=? AND owner=?',(time.time()+300,item['id'],item['owner']))
    thread=threading.Thread(target=heartbeat,daemon=True)
    thread.start()
    stage='inspection'
    def cancelled():
        if not automation.config()['enabled'] or worker.stop_event.is_set():
            return True
        with get_connection() as conn:
            row=conn.execute('SELECT owner FROM media_intake WHERE id=?',(item['id'],)).fetchone()
        return not row or row['owner']!=item['owner']
    try:
        path = automation.checked_path(item['video_path'])
        if not automation.permitted_file(path):
            update(item,'validation_pending','Outside active processing scope',60)
            return True
        if not path.exists():
            ids=json.loads(item['media_ids'] or '{}')
            if ids.get('file') and item['service'] in services():
                current=api(item['service'],'api/v3/'+('moviefile/' if item['service']=='radarr' else 'episodefile/')+str(ids['file']))
                if current.get('path'):
                    new_path=automation.map_path(current['path'])
                    if new_path!=path:
                        with get_connection() as conn:
                            conn.execute('BEGIN IMMEDIATE')
                            conn.execute("UPDATE media_intake SET video_path=?,state='validation_pending',signature='',stable_since=0,source_path=NULL,source_hash=NULL,owner=NULL,next_run=0 WHERE id=? AND owner=?",(str(new_path),item['id'],item['owner']))
                            conn.execute("UPDATE automation_queue SET video_path=?,status='waiting_intake',owner=NULL,lease_until=0 WHERE video_path=? AND status NOT IN ('done','skipped')",(str(new_path),str(path)))
                        return True
            age = (datetime.now(timezone.utc)-datetime.fromisoformat(item['imported_at'].replace('Z','+00:00'))).total_seconds()
            update(item,'invalid_media' if age>settings.media_import_timeout_hours*3600 else 'waiting_import',
                   'Imported destination missing; no translation job created',60)
            return True
        if not stat.S_ISREG(path.stat().st_mode) or path.suffix.lower() not in automation.VIDEO_EXTENSIONS:
            update(item,'invalid_media','Not a regular supported media file')
            return True
        signature = automation.signature(path)
        if signature!=item['signature'] or not item['stable_since']:
            update(item,'waiting_stable','Checking import file stability',settings.media_stability_seconds,
                   signature=signature,stable_since=time.time())
            return True
        if time.time()-item['stable_since']<settings.media_stability_seconds:
            update(item,'waiting_stable','Checking import file stability',settings.media_stability_seconds)
            return True
        ids = json.loads(item['media_ids'] or '{}')
        if ids.get('file') and item['service'] in services():
            file = api(item['service'],'api/v3/'+('moviefile/' if item['service']=='radarr' else 'episodefile/')+str(ids['file']))
            expected_key = 'movieId' if item['service']=='radarr' else 'seriesId'
            if ids.get('item') and file.get(expected_key) and ids['item']!=file[expected_key]:
                update(item,'invalid_media','Arr file does not belong to the notified media identity')
                return True
            if file.get('path') and automation.map_path(file['path'])!=path:
                update(item,'superseded','Arr file identity now points to another import')
                return True
            if file.get('size') and file['size']!=path.stat().st_size:
                update(item,'waiting_stable','Arr size and destination size differ',30,stable_since=0)
                return True
        info = get_media_info(path,cancel_check=cancelled)
        if info.get('format',{}).get('format_name','').split(',')[0] not in {'matroska','webm','mov','mp4','avi','mpeg','mpegts','asf','ogg'}:
            update(item,'invalid_media','Unsupported media container detected by FFprobe')
            return True
        if not any(s.get('codec_type')=='video' and s.get('codec_name') for s in info.get('streams',[])) or float(info.get('format',{}).get('duration',0))<=0:
            update(item,'invalid_media','FFprobe found no valid video/container duration')
            return True
        if automation.existing_persian_sidecar(path):
            update(item,'completed','Existing Persian subtitle preserved')
            return True
        streams = list_subtitle_streams(path,cancel_check=cancelled)
        if any(s['language'] in {'fa','fas','per'} or any(x in s.get('title','').lower() for x in ('persian','farsi','فارسی')) for s in streams):
            update(item,'completed','Existing embedded Persian subtitle preserved')
            return True
        stage='extraction'
        source = automation.select_source(path,item['id'],streams,cancel_check=cancelled)
        if automation.signature(path)!=signature:
            update(item,'waiting_stable','Import changed during inspection',10,stable_since=0)
            return True
        if not source:
            update(item,'waiting_source','Waiting for English subtitles; no translation attempt consumed',60)
            return True
        with get_connection() as conn:
            owned=conn.execute('SELECT owner,lease_until FROM media_intake WHERE id=?',(item['id'],)).fetchone()
            if not owned or owned['owner']!=item['owner'] or owned['lease_until']<=time.time():
                raise RuntimeError('Media preparation lease was lost.')
            conn.execute('UPDATE media_intake SET source_path=?,source_hash=? WHERE id=? AND owner=?',
                         (str(source),hashlib.sha256(source.read_bytes()).hexdigest(),item['id'],item['owner']))
        if source.parent==path.parent and time.time()-source.stat().st_mtime<settings.media_stability_seconds:
            update(item,'waiting_source','Waiting for English sidecar stability',settings.media_stability_seconds)
            return True
        queue = automation.enqueue(str(path),item['service'])
        with get_connection() as conn:
            conn.execute("UPDATE automation_queue SET status='queued',next_run=0 WHERE id=? AND status='waiting_intake'",(queue['id'],))
        update(item,'queued',queue_id=queue['id'],source_path=str(source),source_hash=hashlib.sha256(source.read_bytes()).hexdigest(),attempts=0)
    except urllib.error.HTTPError as exc:
        update(item,'superseded' if exc.code==404 else 'validation_pending','Arr file identity unavailable: HTTP '+str(exc.code),60)
    except (urllib.error.URLError,TimeoutError) as exc:
        update(item,'validation_pending','Authoritative Arr identity temporarily unavailable: '+str(exc),60)
    except Exception as exc:
        if not automation.config()['enabled'] or worker.stop_event.is_set():
            update(item,'validation_pending','Paused or restarting during preparation',5)
            return True
        attempts = item['attempts']+1
        update(item,('preparation_failed' if stage=='extraction' else 'invalid_media') if attempts>=5 else 'validation_pending',
               type(exc).__name__+': '+str(exc),min(600,15*2**min(attempts,5)),attempts=attempts)
        logger.warning('Media intake deferred: %s',type(exc).__name__)
    finally:
        heartbeat_stop.set()
        thread.join(timeout=2)
    return True


def upstream(service, record, state):
    download = record.get('downloadId')
    media_id = (str(record.get('movieId')) if service=='radarr' else 'series:'+str(record.get('seriesId'))+':episode:'+str(record.get('episodeId'))) if service in {'radarr','sonarr'} else str(record.get('mediaId') or '')
    identity = service+(':history:' if record.get('eventType') else ':queue:')+str(record.get('id') or download or media_id)
    size = record.get('size') or 0
    progress = 100*(1-(record.get('sizeleft',size)/size)) if size else None
    error = '; '.join(str(message) for entry in record.get('statusMessages',[]) for message in entry.get('messages',[]))
    with get_connection() as conn:
        old = conn.execute('SELECT * FROM upstream_activity WHERE identity=?',(identity,)).fetchone()
        now = time.time()
        same_state = old and (old['state']==state or old['state']=='download_stalled' and state=='downloading')
        changed = now if not old or old['progress']!=progress or not same_state else old['changed_at']
        if state=='downloading' and now-changed>settings.media_download_stall_hours*3600:
            state='download_stalled'
            error=error or 'No reported progress within configured warning threshold; download remains controlled by Arr.'
        if download and media_id:
            conn.execute("UPDATE upstream_activity SET replaced_by=? WHERE service=? AND media_id=? AND download_id<>? AND state IN ('download_failed','import_failed','import_rejected','download_stalled')", (download,service,media_id,download))
        conn.execute('''INSERT INTO upstream_activity VALUES (?,?,?,?,?,?,?,?,?,?,?,?,NULL)
            ON CONFLICT(identity) DO UPDATE SET state=excluded.state,progress=excluded.progress,
            error=excluded.error,updated_at=excluded.updated_at,changed_at=excluded.changed_at,path=excluded.path,
            media_id=excluded.media_id,download_id=excluded.download_id,title=excluded.title''',
            (identity,service,media_id,download,record.get('title') or record.get('sourceTitle') or identity,state,progress,
             record.get('outputPath') or '',error,old['first_seen'] if old else now,changed,utc_now()))


def poll_arr(service, cursor):
    queue = api(service,'api/v3/queue?page=1&pageSize=100&includeUnknownMovieItems=true&includeUnknownSeriesItems=true')
    for item in queue.get('records',[]):
        status = str(item.get('status','')).lower()
        tracked = str(item.get('trackedDownloadStatus','')).lower()
        state = {'queued':'download_queued','paused':'download_paused','downloading':'downloading','failed':'download_failed'}.get(status,'downloading')
        if status=='completed':
            state='completed_not_imported'
        if tracked=='error':
            state='import_failed' if status=='completed' else 'download_failed'
        elif tracked=='warning':
            state='import_rejected' if status=='completed' else 'download_stalled'
        upstream(service,item,state)
    # DESC pagination checkpoint is committed only after reaching the old cursor.
    # New events arriving during a cycle are excluded by its upper watermark.
    for _ in range(5):
        result = api(service,'api/v3/history?'+urllib.parse.urlencode({'page':cursor['page'],'pageSize':100,
            'sortKey':'date','sortDirection':'descending','includeMovie':'true','includeSeries':'true','includeEpisode':'true'}))
        records = result.get('records',[])
        if not cursor['upper_id']:
            cursor['upper_id']=max((r['id'] for r in records),default=cursor['last_id'])
        boundary = not records
        for record in records:
            if record['id']<=cursor['last_id'] or datetime.fromisoformat(record['date'].replace('Z','+00:00'))<datetime.fromisoformat(cursor['activation_at'].replace('Z','+00:00')):
                boundary=True
                continue
            if record['id']>cursor['upper_id']:
                continue
            event = record.get('eventType')
            if event in {'downloadFolderImported','movieFileImported','episodeFileImported'}:
                imported = record.get('data',{}).get('importedPath')
                if imported:
                    try:
                        mapped = automation.map_path(imported)
                        ingest(service,record,mapped,'history')
                    except (ValueError,TypeError):
                        rejected=dict(record)
                        rejected['statusMessages']=[{'messages':['Import destination or metadata rejected by UST library policy']} ]
                        upstream(service,rejected,'import_rejected')
            elif event in {'downloadFailed','downloadIgnored'}:
                upstream(service,record,'download_failed' if event=='downloadFailed' else 'import_rejected')
        if boundary or len(records)<100:
            cursor['last_id']=cursor['upper_id']
            cursor['upper_id']=0
            cursor['page']=1
        else:
            cursor['page']+=1
        with get_connection() as conn:
            conn.execute('UPDATE intake_cursors SET last_id=?,upper_id=?,page=? WHERE service=?',
                         (cursor['last_id'],cursor['upper_id'],cursor['page'],service))
        if boundary or len(records)<100:
            break


def poll():
    with get_connection() as conn:
        conn.execute("UPDATE automation_queue SET status='waiting_intake',owner=NULL,lease_until=0 WHERE status='waiting_media' AND id IN (SELECT queue_id FROM media_intake)")
        conn.execute("""UPDATE media_intake SET state=CASE
            (SELECT status FROM automation_queue WHERE id=media_intake.queue_id)
            WHEN 'done' THEN 'completed' WHEN 'skipped' THEN 'completed'
            WHEN 'running' THEN 'processing' WHEN 'failed' THEN 'translation_failed'
            WHEN 'waiting_intake' THEN 'validation_pending'
            WHEN 'waiting_budget' THEN 'waiting_budget' WHEN 'cancelled' THEN 'cancelled'
            ELSE 'queued' END
            WHERE queue_id IS NOT NULL AND owner IS NULL AND state NOT IN ('superseded','invalid_media','waiting_stable','validation_pending')""")
    for service in services():
        with get_connection() as conn:
            row=conn.execute('SELECT * FROM intake_cursors WHERE service=?',(service,)).fetchone()
        if not row or row['next_run']>time.time():
            continue
        try:
            if service in {'sonarr','radarr'}:
                poll_arr(service,dict(row))
            elif service=='seerr':
                for request in api(service,'api/v1/request?take=25&skip=0&sort=added').get('results',[]):
                    media=request.get('media') or {}
                    upstream(service,{'id':request['id'],'title':media.get('title') or str(request.get('type'))+' TMDB '+str(media.get('tmdbId')),'mediaId':media.get('externalServiceId')},
                             {1:'requested',2:'requested_approved',3:'request_declined'}.get(request.get('status'),'requested_unknown'))
            elif service=='qbit':
                with get_connection() as conn:
                    hashes=[r[0] for r in conn.execute("SELECT DISTINCT download_id FROM upstream_activity WHERE service IN ('radarr','sonarr') AND download_id IS NOT NULL AND state NOT IN ('imported','download_failed') LIMIT 100")]
                if hashes:
                    for torrent in api(service,'api/v2/torrents/info?'+urllib.parse.urlencode({'hashes':'|'.join(hashes)})):
                        state=torrent.get('state','')
                        mapped='download_stalled' if state=='stalledDL' else 'download_failed' if state in {'error','missingFiles'} else 'download_paused' if state in {'pausedDL','stoppedDL'} else 'download_complete' if torrent.get('progress',0)>=1 else 'downloading'
                        upstream(service,{'id':torrent['hash'],'downloadId':torrent['hash'],'title':torrent['name'],'size':torrent.get('total_size',0),'sizeleft':torrent.get('amount_left',0),'outputPath':torrent.get('save_path','')},mapped)
            elif service=='jellyfin':
                count=sum(bool(s.get('TranscodingInfo')) and bool(s.get('NowPlayingItem')) for s in api(service,'Sessions'))
                resources.set_transcodes(count)
            with get_connection() as conn:
                conn.execute("UPDATE intake_cursors SET next_run=?,failures=0,error='' WHERE service=?",(time.time()+30,service))
        except Exception as exc:
            with get_connection() as conn:
                conn.execute('UPDATE intake_cursors SET next_run=?,failures=failures+1,error=? WHERE service=?',
                             (time.time()+min(600,15*2**min(row['failures'],5)),type(exc).__name__+': '+str(exc),service))


def retry(item_id):
    with get_connection() as conn:
        row=conn.execute('SELECT state FROM media_intake WHERE id=?',(item_id,)).fetchone()
        if not row or row['state'] in {'processing','completed','queued'}:
            raise ValueError('Active/completed/missing imports cannot be rechecked.')
        conn.execute("UPDATE media_intake SET state='validation_pending',attempts=0,next_run=0,owner=NULL,lease_until=0,error='' WHERE id=?",(item_id,))


def snapshot():
    with get_connection() as conn:
        rows=[dict(r) for r in conn.execute('''SELECT i.*,q.status AS translation_state FROM media_intake i
            LEFT JOIN automation_queue q ON q.id=i.queue_id ORDER BY i.updated_at DESC LIMIT 200''')]
        upstream_rows=[dict(r) for r in conn.execute('SELECT * FROM upstream_activity ORDER BY updated_at DESC LIMIT 200')]
        cursors=[dict(r) for r in conn.execute('SELECT service,next_run,failures,error FROM intake_cursors')]
        counts=dict(conn.execute('SELECT state,COUNT(*) FROM media_intake GROUP BY state').fetchall())
    return {'imports':rows,'downloads':upstream_rows,'services':cursors,'counts':counts}


class Worker:
    def __init__(self):
        self.stop_event=threading.Event()
        self.threads=[]

    def start(self):
        if not settings.media_intake_enabled or self.threads:
            return
        self.stop_event.clear()
        self.threads=[threading.Thread(target=self.polling,daemon=True),threading.Thread(target=self.preparing,daemon=True)]
        for thread in self.threads:
            thread.start()

    def polling(self):
        while not self.stop_event.is_set():
            try:
                poll()
            except Exception:
                logger.exception('Read-only upstream polling deferred')
            self.stop_event.wait(2)

    def preparing(self):
        futures=set()
        with ThreadPoolExecutor(max_workers=2) as pool:
            while not self.stop_event.is_set():
                for future in list(futures):
                    if future.done():
                        try:
                            future.result()
                        except Exception:
                            logger.exception('Preparation scheduler deferred')
                        futures.remove(future)
                if len(futures)<2:
                    futures.add(pool.submit(prepare_one))
                self.stop_event.wait(.5)

    def stop(self):
        self.stop_event.set()
        for thread in self.threads:
            thread.join(timeout=3)
        self.threads=[]


worker=Worker()
