import time

import pytest

from app.config import settings, ensure_directories
from app.database import init_db, get_connection
from app.services import media_intake as intake, automation, resources

ENGLISH='1\n00:00:01,000 --> 00:00:02,000\nHello, how are you?\n\n2\n00:00:03,000 --> 00:00:04,000\nAre you kidding me?\n'


@pytest.fixture
def library(monkeypatch,tmp_path):
    intake.worker.stop_event.clear()
    root=tmp_path/'library'
    root.mkdir()
    monkeypatch.setattr(settings,'media_intake_enabled',True)
    monkeypatch.setattr(settings,'media_stability_seconds',0)
    ensure_directories()
    init_db()
    automation.init_schema()
    intake.init_schema()
    automation.save_config(True,[str(root)],{},'events_only')
    monkeypatch.setattr(intake,'services',lambda: {})
    monkeypatch.setattr(intake,'get_media_info',lambda _,**kwargs: {'streams':[{'codec_type':'video','codec_name':'ffv1'}],'format':{'duration':'6','format_name':'matroska'}})
    monkeypatch.setattr(intake,'list_subtitle_streams',lambda _,**kwargs: [])
    monkeypatch.setattr(automation,'list_subtitle_streams',lambda _,**kwargs: [])
    monkeypatch.setattr('app.services.ffmpeg_service.get_media_info',lambda _,**kwargs: {'format':{'duration':'6'}})
    return root


def media(root,name='Episode'):
    path=root/(name+'.mkv')
    path.write_bytes(b'regular fixture; ffprobe is mocked')
    return path


def state(item_id):
    with get_connection() as c:
        return dict(c.execute('SELECT * FROM media_intake WHERE id=?',(item_id,)).fetchone())


def due(item_id):
    with get_connection() as c:
        c.execute('UPDATE media_intake SET next_run=0 WHERE id=?',(item_id,))


def test_stability_and_english_are_prerequisites_not_worker_jobs(library):
    video=media(library)
    item=intake.ingest('sonarr',{'episodeFile':{'path':str(video)}},video)
    assert automation.counts()=={}
    intake.prepare_one()
    assert state(item)['state']=='waiting_stable'
    intake.prepare_one()
    assert state(item)['state']=='waiting_source'
    assert automation.counts()=={} and state(item)['attempts']==0
    video.with_suffix('.en.srt').write_text(ENGLISH)
    assert intake.wake(video)==item
    intake.prepare_one()
    assert state(item)['state']=='queued' and automation.counts()=={'queued':1}
    assert intake.cached_source(video)==video.with_suffix('.en.srt')


def test_100_imports_duplicates_and_restart_no_unbounded_work(library):
    started=time.monotonic()
    for i in range(100):
        video=media(library,str(i))
        first=intake.ingest('sonarr',{},video)
        assert intake.ingest('sonarr',{},video)==first
    intake.init_schema()
    assert time.monotonic()-started<10
    with get_connection() as c:
        assert c.execute('SELECT COUNT(*) FROM media_intake').fetchone()[0]==100
        assert c.execute('SELECT COUNT(*) FROM media_events').fetchone()[0]==100
    assert automation.counts()=={}
    first,second=intake.claim(),intake.claim()
    assert first and second and not intake.claim()
    with get_connection() as c:
        c.execute('UPDATE media_intake SET lease_until=0 WHERE id=?',(first['id'],))
    recovered=intake.claim()
    assert recovered['id']==first['id'] and recovered['owner']!=first['owner']
    intake.update(first,'queued')
    assert state(first['id'])['owner']==recovered['owner']


def test_fake_completed_and_failed_downloads_never_submit_translation(library,monkeypatch):
    responses={'queue':{'records':[
        {'id':1,'seriesId':10,'episodeId':20,'status':'downloading','size':100,'sizeleft':1,'downloadId':'fake'},
        {'id':2,'seriesId':10,'episodeId':21,'status':'completed','trackedDownloadStatus':'error','size':100,'sizeleft':0,'downloadId':'bad-import','statusMessages':[{'messages':['No eligible video found']}]}]},'history':{'records':[]}}
    monkeypatch.setattr(intake,'api',lambda _,route: responses['queue' if 'queue?' in route else 'history'])
    intake.poll_arr('sonarr',{'page':1,'last_id':0,'upper_id':0,'activation_at':'2026-01-01T00:00:00+00:00'})
    snapshot=intake.snapshot()
    assert {r['state'] for r in snapshot['downloads']}=={'downloading','import_failed'}
    assert snapshot['imports']==[] and automation.counts()=={}


def test_missing_webhooks_recovered_by_cursor_without_historical_backfill(library,monkeypatch):
    old=media(library,'Old')
    new=media(library,'New')
    history=[{'id':11,'eventType':'downloadFolderImported','date':'2026-10-14T23:00:00Z','data':{'importedPath':str(new)}},
             {'id':10,'eventType':'downloadFolderImported','date':'2025-01-01T00:00:00Z','data':{'importedPath':str(old)}}]
    monkeypatch.setattr(intake,'api',lambda _,route: {'records':[]} if 'queue?' in route else {'records':history})
    cursor={'page':1,'last_id':0,'upper_id':0,'activation_at':'2026-10-14T22:00:00+00:00'}
    intake.poll_arr('radarr',cursor)
    assert cursor['last_id']==11
    with get_connection() as c:
        assert c.execute('SELECT video_path FROM media_intake').fetchall()[0][0]==str(new)
        assert c.execute('SELECT COUNT(*) FROM media_intake').fetchone()[0]==1
    intake.init_schema()
    intake.poll_arr('radarr',cursor)
    with get_connection() as c:
        assert c.execute('SELECT COUNT(*) FROM media_events').fetchone()[0]==1


def test_missing_or_invalid_destination_does_not_block_valid_episode(library,monkeypatch):
    missing=library/'Missing.mkv'
    first=intake.ingest('sonarr',{},missing)
    intake.prepare_one()
    assert state(first)['state']=='waiting_import' and automation.counts()=={}
    valid=media(library,'Valid')
    valid.with_suffix('.en.srt').write_text(ENGLISH)
    second=intake.ingest('sonarr',{},valid)
    intake.prepare_one()
    intake.prepare_one()
    assert state(second)['state']=='queued' and automation.counts()=={'queued':1}


def test_extraction_failure_releases_preparation_for_other_files(library,monkeypatch):
    bad=media(library,'Bad')
    good=media(library,'Good')
    good.with_suffix('.en.srt').write_text(ENGLISH)
    first=intake.ingest('sonarr',{},bad)
    second=intake.ingest('sonarr',{},good)
    original=automation.select_source
    def source(path,*args,**kwargs):
        if path==bad:
            raise RuntimeError('FFmpeg fixture failure')
        return original(path,*args,**kwargs)
    monkeypatch.setattr(automation,'select_source',source)
    for _ in range(4):
        intake.prepare_one()
    assert state(first)['attempts']==1
    assert state(second)['state']=='queued'
    assert automation.counts()=={'queued':1}


def test_jellyfin_transcoding_reduces_admission(monkeypatch):
    monkeypatch.setattr(settings,'automation_job_concurrency',2)
    monkeypatch.setattr(settings,'automation_api_concurrency',4)
    monkeypatch.setattr(resources,'pressure',lambda: {'available_mb':4096,'container_mb':900,'memory_pressure':0,'load':0})
    resources.set_transcodes(1)
    status=resources.status()
    assert status['job_limit']==1 and status['api_limit']==2
    assert status['inspection_limit']==1 and status['extraction_limit']==1
    assert status['active_transcodes']==1


def test_cursor_pagination_survives_restart_and_continuous_imports(library,monkeypatch):
    records=[{'id':n,'date':'2026-10-14T23:00:00Z','eventType':'downloadFolderImported',
              'data':{'importedPath':str(library/f'{n}.mkv')}} for n in range(1750,1000,-1)]
    records.append({'id':1000,'date':'2025-01-01T00:00:00Z','eventType':'downloadFolderImported','data':{'importedPath':str(library/'historical.mkv')}})
    def api(_,route):
        if 'queue?' in route:
            return {'records':[]}
        from urllib.parse import parse_qs,urlsplit
        page=int(parse_qs(urlsplit(route).query)['page'][0])
        return {'records':records[(page-1)*100:page*100]}
    monkeypatch.setattr(intake,'api',api)
    cursor={'page':1,'last_id':1000,'upper_id':0,'activation_at':'2026-10-14T22:00:00+00:00'}
    intake.poll_arr('radarr',cursor)
    assert cursor['page']==6 and cursor['last_id']==1000
    records[:0]=[{'id':n,'date':'2026-10-14T23:01:00Z','eventType':'downloadFolderImported',
                 'data':{'importedPath':str(library/f'{n}.mkv')}} for n in range(1775,1750,-1)]
    with get_connection() as c:
        stored=c.execute("SELECT page,last_id,upper_id FROM intake_cursors WHERE service='radarr'").fetchone()
    assert tuple(stored)==(6,1000,1750)
    intake.init_schema()
    intake.poll_arr('radarr',cursor)
    assert cursor['last_id']==1750 and cursor['page']==1
    intake.poll_arr('radarr',cursor)
    assert cursor['last_id']==1775
    with get_connection() as c:
        assert c.execute('SELECT COUNT(*) FROM media_intake').fetchone()[0]==775
    assert automation.counts()=={}


def test_bad_history_destination_cannot_block_a_valid_new_import(library,monkeypatch):
    valid=media(library,'ValidHistory')
    records=[{'id':21,'eventType':'downloadFolderImported','date':'2026-10-14T23:00:00Z','data':{'importedPath':'/downloads/not-imported.mkv'}},
             {'id':20,'eventType':'downloadFolderImported','date':'2026-10-14T23:00:00Z','data':{'importedPath':str(valid)}}]
    monkeypatch.setattr(intake,'api',lambda _,route: {'records':[]} if 'queue?' in route else {'records':records})
    cursor={'page':1,'last_id':0,'upper_id':0,'activation_at':'2026-10-14T22:00:00+00:00'}
    intake.poll_arr('sonarr',cursor)
    assert cursor['last_id']==21
    assert len(intake.snapshot()['imports'])==1
    assert intake.snapshot()['downloads'][0]['state']=='import_rejected'


def test_movie_fairness_after_three_episodes(library,monkeypatch):
    monkeypatch.setattr(settings,'automation_job_concurrency',1)
    episodes=[]
    for i in range(10):
        video=media(library,str(i))
        episodes.append(automation.enqueue(str(video),'sonarr'))
    movie=automation.enqueue(str(media(library,'Movie')),'radarr')
    for i in range(3):
        item=automation.claim()
        assert item['id']==episodes[i]['id']
        automation.finish(item,'done','fixture')
    assert automation.claim()['id']==movie['id']


def test_arr_file_identity_recovers_moved_pending_import(library,monkeypatch):
    old=library/'Before.mkv'
    new=media(library,'After')
    item=intake.ingest('sonarr',{'series':{'id':1},'episodeFile':{'id':2}},old)
    monkeypatch.setattr(intake,'services',lambda:{'sonarr':{}})
    monkeypatch.setattr(intake,'api',lambda *_:{'path':str(new),'seriesId':1})
    intake.prepare_one()
    assert state(item)['video_path']==str(new)
    assert state(item)['state']=='validation_pending'
    assert automation.counts()=={}
