import urllib.error

import pytest

from app.database import get_connection, utc_now
from app.services import automation, intake_tracking as tracking, media_intake as intake, ui_state


def episode(number, download='ABC123', title='How I Met Your Mother'):
    return {'id':number,'seriesId':28,'episodeId':100+number,'downloadId':download,
            'title':'Release.Name.S01.1080p','size':100,'sizeleft':41,
            'series':{'id':28,'title':title},'episode':{'seasonNumber':1,'episodeNumber':number}}


def test_one_download_row_for_season_pack_but_independent_import_files(client, tmp_path):
    for number in range(1,23):
        intake.upstream('sonarr',tracking.enrich_arr('sonarr',episode(number),[0]),'downloading')
    intake.upstream('qbit',{'id':'abc123','downloadId':'abc123','title':'Release'},'downloading')
    page=ui_state.pagination('downloads')
    assert page['total']==1
    row=page['items'][0]
    assert row['related_records']==22 and row['progress']==pytest.approx(59)
    assert row['name']=='How I Met Your Mother · 22 episodes'
    assert ui_state.snapshot()['upstream']['downloading']==1
    root=tmp_path/'library'
    root.mkdir()
    automation.save_config(False,[str(root)],{},'events_only')
    for number in range(1,23):
        intake.ingest('sonarr',{'series':{'title':'How I Met Your Mother'},'downloadId':'ABC123'},root/f'Show.S01E{number:02}.mkv')
    assert ui_state.pagination('downloads',state='all')['total']==23
    assert automation.counts()=={}  # Twenty-two independent imports, no premature translations.


def test_removed_torrent_disappears_from_active_view_without_creating_jobs(client,monkeypatch):
    intake.upstream('sonarr',episode(1),'downloading')
    monkeypatch.setattr(intake,'services',lambda:{'qbit':{}})
    calls=[]
    def api(service,route):
        calls.append((service,route))
        return []
    monkeypatch.setattr(intake,'api',api)
    tracking.reconcile_missing('sonarr',set(),False)
    assert calls==[] and ui_state.pagination('downloads')['total']==1
    tracking.reconcile_missing('sonarr',set(),True)
    assert len(calls)==1 and 'abc123' in calls[0][1]
    assert ui_state.pagination('downloads')['total']==0
    row=ui_state.pagination('downloads',state='all')['items'][0]
    assert row['state']=='download_removed' and row['progress'] is None
    assert automation.counts()=={}
    tracking.reconcile_missing('sonarr',set(),True)
    assert len(calls)==1  # Terminal observations are not repeatedly re-polled.


def test_missing_queue_does_not_override_import_or_claim_download_success(client,monkeypatch,tmp_path):
    intake.upstream('sonarr',episode(1),'downloading')
    monkeypatch.setattr(intake,'services',lambda:{'qbit':{}})
    monkeypatch.setattr(intake,'api',lambda *_:[{'hash':'abc123','progress':1}])
    tracking.reconcile_missing('sonarr',set(),True)
    assert ui_state.pagination('downloads')['items'][0]['state']=='completed_not_imported'
    assert automation.counts()=={}
    with get_connection() as c:
        c.execute("INSERT INTO media_intake(id,video_path,service,download_id,state,imported_at,updated_at) VALUES('accepted',?,'sonarr','ABC123','validation_pending',?,?)",(str(tmp_path/'Show.mkv'),utc_now(),utc_now()))
    monkeypatch.setattr(intake,'api',lambda *_:[])
    tracking.reconcile_missing('sonarr',set(),True)
    with get_connection() as c:
        assert c.execute("SELECT state FROM upstream_activity").fetchone()[0]=='imported'
    assert automation.counts()=={}


def test_outage_preserves_observation_and_shows_stale_status(client,monkeypatch):
    intake.upstream('sonarr',episode(1),'downloading')
    monkeypatch.setattr(intake,'services',lambda:{'qbit':{}})
    def fail(*_):
        raise TimeoutError('Fixture timeout')
    monkeypatch.setattr(intake,'api',fail)
    with pytest.raises(TimeoutError):
        tracking.reconcile_missing('sonarr',set(),True)
    with get_connection() as c:
        assert c.execute('SELECT state FROM upstream_activity').fetchone()[0]=='downloading'
        c.execute("UPDATE upstream_activity SET updated_at='2020-01-01T00:00:00+00:00'")
    assert ui_state.pagination('downloads')['items'][0]['state']=='status_unverified'


def test_seerr_real_names_all_statuses_and_bounded_title_cache(client,monkeypatch):
    calls=[]
    def api(service,route):
        calls.append((service,route))
        return {'name':'How I Met Your Mother'}
    monkeypatch.setattr(intake,'api',api)
    req={'id':43,'type':'tv','status':5,'media':{'tmdbId':1100,'status':5,'externalServiceId':28},'seasons':[{'seasonNumber':1}]}
    record,state=tracking.seerr_record(req,[1])
    assert record['title']=='How I Met Your Mother' and state=='request_available'
    intake.upstream('seerr',record,state)
    assert ui_state.pagination('downloads')['total']==0
    assert ui_state.pagination('downloads',state='all')['items'][0]['name']=='How I Met Your Mother · Season 1'
    for status,expected in [(1,'requested'),(2,'requested_approved'),(3,'request_declined'),(4,'request_failed'),(5,'request_completed')]:
        _,actual=tracking.seerr_record({**req,'status':status,'media':{**req['media'],'status':1}},[1])
        assert actual==expected
    assert len(calls)==1
    for number in range(20):
        tracking.seerr_record({**req,'media':{'tmdbId':2000+number}},[0])
    assert len(calls)==1
    _,removed=tracking.seerr_record({**req,'media':{**req['media'],'status':7}},[0])
    assert removed=='request_deleted'


def test_old_season_rows_gain_real_series_title_without_network_on_page(client,monkeypatch):
    for n in range(1,11):
        intake.upstream('sonarr',{**episode(n),'series':None},'downloading')
    calls=[]
    monkeypatch.setattr(intake,'api',lambda *args: calls.append(args) or {'title':'Ted Lasso'})
    tracking.refresh_stored_titles('sonarr',[1])
    assert len(calls)==1
    assert ui_state.pagination('downloads')['items'][0]['name']=='Ted Lasso · 10 episodes'
    assert len(calls)==1


def test_guard_removal_retires_upstream_only_and_preserves_imports(client):
    intake.upstream('sonarr',episode(1),'import_rejected')
    tracking.removed_by_guard('ABC123')
    row=ui_state.pagination('downloads',state='all')['items'][0]
    assert row['state']=='download_removed' and 'Download Guard' in row['error']
    assert automation.counts()=={}


def test_deleted_import_file_is_terminal_and_does_not_block_other_files(client,monkeypatch,tmp_path):
    root=tmp_path/'library'
    root.mkdir()
    automation.save_config(True,[str(root)],{},'events_only')
    missing=root/'Missing.S01E01.mkv'
    item=intake.ingest('sonarr',{'series':{'id':1},'episodeFile':{'id':123}},missing)
    monkeypatch.setattr(intake,'services',lambda:{'sonarr':{}})
    intake.worker.stop_event.clear()
    def gone(*_):
        raise urllib.error.HTTPError('http://fixture',404,'Removed',{},None)
    monkeypatch.setattr(intake,'api',gone)
    with get_connection() as c:
        c.execute("UPDATE media_intake SET imported_at='2026-01-01T00:00:00+00:00' WHERE id=?",(item,))
    assert intake.prepare_one()
    with get_connection() as c:
        assert c.execute('SELECT state FROM media_intake WHERE id=?',(item,)).fetchone()[0]=='invalid_media'
    assert intake.claim() is None and automation.counts()=={}


def test_polling_text_removed_and_shared_forms_use_inline_confirmation(client):
    for path in ('/ui','/ui/queue','/ui/downloads','/ui/guard'):
        text=client.get(path).text
        assert 'Updates every' not in text and 'refresh-cadence' not in text
        assert 'Upstream only' not in text
    script=client.get('/static/modern.js').text
    assert 'confirmAction' in script and 'confirm(' not in script
    assert 'confirm-controls' in script
    # The provider/account settings and Legacy workflows are still shared.
    assert 'window.UST.confirmAction' in client.get('/ui/settings').text


def test_complete_queue_pagination_does_not_remove_second_page(client,monkeypatch):
    rows=[{**episode(n),'downloadId':'hash'+str(n)} for n in range(1,102)]
    for row in rows:
        intake.upstream('sonarr',row,'downloading')
    seen=[]
    def api(service,route):
        assert service=='sonarr'
        seen.append(route)
        if 'queue?' in route:
            from urllib.parse import parse_qs,urlsplit
            page=int(parse_qs(urlsplit(route).query)['page'][0])
            return {'records':rows[(page-1)*100:page*100],'totalRecords':101}
        return {'records':[]}
    monkeypatch.setattr(intake,'api',api)
    monkeypatch.setattr(intake,'services',lambda:{'qbit':{}})
    intake.poll_arr('sonarr',{'page':1,'last_id':0,'upper_id':0,'activation_at':'2026-01-01T00:00:00+00:00'})
    assert sum('queue?' in route for route in seen)==2
    assert ui_state.pagination('downloads')['total']==101
    assert automation.counts()=={}


def test_additive_metadata_keeps_previous_release_writes_compatible(client):
    with get_connection() as c:
        assert len(c.execute('PRAGMA table_info(upstream_activity)').fetchall())==13
        c.execute("INSERT INTO upstream_activity VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",('old','sonarr','series:1:episode:2','old-hash','Old release','downloading',50,'','',0,0,utc_now(),None))
    assert ui_state.pagination('downloads')['total']==1


def test_rotating_request_page_updates_old_fulfilled_request(client,monkeypatch):
    requested={'id':1,'type':'movie','status':2,'media':{'tmdbId':1}}
    intake.upstream('seerr',{'id':1,'title':'movie TMDB 1'},'requested_unknown')
    def api(service,route):
        assert service=='seerr'
        if 'skip=0' in route:
            return {'pageInfo':{'pages':2},'results':[{'id':2,'type':'movie','status':2,'media':{'tmdbId':2}}]}
        if 'skip=25' in route:
            return {'results':[{**requested,'status':5,'media':{'tmdbId':1,'status':5}}]}
        return {'title':'Proper movie title'}
    monkeypatch.setattr(intake,'api',api)
    tracking.poll_seerr({'page':1})
    all_rows=ui_state.pagination('downloads',state='all')['items']
    assert len(all_rows)==2
    assert all('TMDB' not in row['name'] for row in all_rows)
    assert any(row['state']=='request_available' for row in all_rows)
    assert ui_state.pagination('downloads')['total']==1
    assert automation.counts()=={}


def test_stale_preparation_cannot_fail_a_new_owners_queue_item(client,tmp_path):
    root=tmp_path/'library'
    root.mkdir()
    automation.save_config(False,[str(root)],{},'events_only')
    path=root/'Episode.mkv'
    job=automation.enqueue(str(path),'sonarr')
    item=intake.ingest('sonarr',{},path)
    with get_connection() as c:
        c.execute("UPDATE media_intake SET owner='new',queue_id=? WHERE id=?",(job['id'],item))
        c.execute("UPDATE automation_queue SET status='waiting_intake' WHERE id=?",(job['id'],))
        stale=dict(c.execute('SELECT * FROM media_intake WHERE id=?',(item,)).fetchone())
    stale['owner']='old'
    intake.update(stale,'invalid_media','Stale worker error')
    with get_connection() as c:
        assert c.execute('SELECT status FROM automation_queue WHERE id=?',(job['id'],)).fetchone()[0]=='waiting_intake'


def test_automatic_history_uses_movie_episode_title_instead_of_cache_filename(client,tmp_path):
    with get_connection() as c:
        c.execute("INSERT INTO jobs(id,input_file,input_path,target_language,status,created_at,updated_at) VALUES('translated','a4f81c.srt','/tmp/a4f81c.srt','Persian','done',?,?)",(utc_now(),utc_now()))
        c.execute("INSERT INTO automation_queue(id,video_path,origin,status,job_id,created_at,updated_at) VALUES('file',?,'sonarr','done','translated',?,?)",(str(tmp_path/'Release.S01E03.mkv'),utc_now(),utc_now()))
        c.execute("INSERT INTO media_intake(id,video_path,title,state,queue_id,updated_at) VALUES('i',?,'How I Met Your Mother','completed','file',?)",(str(tmp_path/'Release.S01E03.mkv'),utc_now()))
    assert ui_state.pagination('history',state='all')['items'][0]['name']=='How I Met Your Mother · S01E03'
    assert ui_state.pagination('queue',state='all')['items'][0]['name']=='How I Met Your Mother · S01E03'


def test_corrupt_import_retries_are_bounded_and_do_not_block_valid_import(client,monkeypatch,tmp_path):
    from app.config import settings
    root=tmp_path/'library'
    root.mkdir()
    automation.save_config(True,[str(root)],{},'events_only')
    monkeypatch.setattr(settings,'media_stability_seconds',0)
    monkeypatch.setattr(intake,'services',lambda:{})
    intake.worker.stop_event.clear()
    bad=root/'Bad.mkv'
    good=root/'Good.mkv'
    bad.write_bytes(b'corrupt fixture')
    good.write_bytes(b'video inspection mocked')
    source=good.with_suffix('.en.srt')
    source.write_text('1\n00:00:01,000 --> 00:00:02,000\nHello.\n')
    first=intake.ingest('sonarr',{},bad)
    second=intake.ingest('sonarr',{},good)
    def probe(path,**_):
        if path==bad:
            raise RuntimeError('Corrupt video fixture')
        return {'streams':[{'codec_type':'video','codec_name':'ffv1'}],'format':{'format_name':'matroska','duration':6}}
    monkeypatch.setattr(intake,'get_media_info',probe)
    monkeypatch.setattr(intake,'list_subtitle_streams',lambda *a,**k:[])
    monkeypatch.setattr(automation,'select_source',lambda *a,**k:source)
    for _ in range(8):
        with get_connection() as c:
            c.execute('UPDATE media_intake SET next_run=0 WHERE id=?',(first,))
        intake.prepare_one()
        intake.prepare_one()
    with get_connection() as c:
        failed=dict(c.execute('SELECT * FROM media_intake WHERE id=?',(first,)).fetchone())
        valid=dict(c.execute('SELECT * FROM media_intake WHERE id=?',(second,)).fetchone())
    assert failed['state']=='invalid_media' and failed['attempts']==5
    assert valid['state']=='queued' and automation.counts()=={'queued':1}
