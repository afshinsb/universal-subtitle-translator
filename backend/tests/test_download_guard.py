import time

import pytest

from app.config import settings, ensure_directories
from app.database import get_connection, init_db
from app.services import automation, download_guard as guard, media_intake


@pytest.fixture
def example(monkeypatch,tmp_path):
    ensure_directories()
    init_db()
    automation.init_schema()
    media_intake.init_schema()
    guard.init_schema()
    root=tmp_path/'downloads'
    root.mkdir()
    monkeypatch.setattr(settings,'download_guard_root',root)
    path=root/'Fake.Ep.EXE'
    path.write_bytes(b'MZ'+b'0'*100)
    torrent={'hash':'a'*40,'name':'Fake episode','category':'tv-sonarr','progress':1,
             'amount_left':0,'state':'stalledUP','save_path':'/downloads'}
    files=[{'name':path.name,'size':102,'progress':1}]
    calls=[]
    def api(service,route):
        if service=='sonarr':
            return {'records':[{'downloadId':'a'*40,'status':'completed','trackedDownloadStatus':'warning',
                'trackedDownloadState':'importPending','statusMessages':[{'messages':['No files found are eligible for import']}]}]}
        if '/files?' in route:
            return files
        return [] if calls else [torrent]
    monkeypatch.setattr(media_intake,'api',api)
    monkeypatch.setattr(media_intake,'qbit_request',lambda route,data: calls.append((route,data)))
    return torrent,files,path,calls


def test_fake_confirmed_case_and_dry_run(example):
    torrent,files,path,calls=example
    assert guard.classify(torrent,files)[0]
    guard.configure(True,False)
    guard.inspect(torrent)
    assert guard.snapshot()['suspicious_count']==1
    assert not calls and path.exists()
    with pytest.raises(ValueError,match='dry-run'):
        guard.configure(True,True)


@pytest.mark.parametrize('category,progress,state',[
    ('software',1,'stalledUP'),('tv-sonarr',.99,'downloading'),('tv-sonarr',1,'checkingUP')])
def test_personal_incomplete_checking_never_deleted(example,category,progress,state):
    torrent,files,path,calls=example
    torrent.update(category=category,progress=progress,state=state)
    assert not guard.classify(torrent,files)[0]
    guard.inspect(torrent,True)
    assert not calls


def test_media_mixed_and_extension_only_are_not_confirmed(example):
    torrent,files,path,calls=example
    assert not guard.classify(torrent,[{'name':'movie.mkv','size':20,'progress':1}])[0]
    assert not guard.classify(torrent,files+[{'name':'movie.mkv','size':20,'progress':1}])[0]
    path.write_bytes(b'plain text'+b'0'*92)
    assert not guard.classify(torrent,files)[0]


@pytest.mark.parametrize('name',['../Fake.Ep.EXE','/Fake.Ep.EXE','bad\\Fake.EXE'])
def test_traversal_rejected(example,name):
    torrent,files,path,calls=example
    files[0]['name']=name
    assert not guard.classify(torrent,files)[0]


def test_symlink_and_shared_hardlink_rejected(example):
    torrent,files,path,calls=example
    other=path.with_name('other.exe')
    other.write_bytes(path.read_bytes())
    path.unlink()
    path.symlink_to(other)
    assert not guard.classify(torrent,files)[0]
    path.unlink()
    import os
    os.link(other,path)
    assert not guard.classify(torrent,files)[0]


def arm():
    with get_connection() as conn:
        conn.execute("UPDATE download_guard_config SET enabled=1,auto_remove=1,last_scan='dry run completed'")
        conn.execute('UPDATE download_guard_seen SET first_seen=?',(time.time()-301,))


def test_repeated_checks_one_api_delete(example):
    torrent,files,path,calls=example
    guard.configure(True,False)
    guard.inspect(torrent)
    arm()
    guard.inspect(torrent,True)
    assert len(calls)==1
    assert calls[0][1]=={'hashes':'a'*40,'deleteFiles':'true'}
    assert guard.snapshot()['removed_count']==1
    # Stale snapshot does not repeat deletion when exact identity disappears.
    guard.inspect(torrent,True)
    assert len(calls)==1


def test_imported_identity_protects_data(example):
    torrent,files,path,calls=example
    with get_connection() as conn:
        conn.execute("INSERT INTO media_intake(id,video_path,download_id,state) VALUES('i','/media/video.mkv',?,'completed')",(torrent['hash'],))
    guard.inspect(torrent)
    arm()
    guard.inspect(torrent,True)
    assert not calls


def test_failed_delete_is_reported_and_never_fs_deleted(example,monkeypatch):
    torrent,files,path,calls=example
    guard.configure(True,False)
    guard.inspect(torrent)
    arm()
    def fail(*args):
        raise RuntimeError('API deletion rejected')
    monkeypatch.setattr(media_intake,'qbit_request',fail)
    guard.scan()
    assert path.exists()
    assert guard.snapshot()['removed_count']==0
    assert any(r['action']=='failed' for r in guard.snapshot()['recent'])


def test_changed_save_path_is_not_deleted(example,monkeypatch):
    torrent,files,path,calls=example
    guard.inspect(torrent)
    arm()
    old=media_intake.api
    def api(service,route):
        if '/info?' in route:
            return [{**torrent,'save_path':'/incomplete'}]
        return old(service,route)
    monkeypatch.setattr(media_intake,'api',api)
    guard.inspect(torrent,True)
    assert not calls


@pytest.mark.parametrize('status,body',[(200,b'Ok.'),(204,b'')])
def test_qbit_login_accepts_current_and_legacy_api(monkeypatch,status,body):
    import io
    class Response(io.BytesIO):
        def __init__(self,content,code):
            super().__init__(content)
            self.status=code
    class Opener:
        def open(self,request,timeout):
            route=request.full_url
            return Response(body,status) if '/auth/login' in route else Response(b'[]',200)
    monkeypatch.setattr(media_intake,'services',lambda: {'qbit':{'url':'http://qbit','username':'u','password':'p'}})
    monkeypatch.setattr(media_intake,'_qbit_client',None)
    monkeypatch.setattr(media_intake.urllib.request,'build_opener',lambda *a: Opener())
    assert media_intake.qbit_request('api/v2/torrents/info?limit=1')==[]
