"""Isolated 100-file scheduler benchmark; no network and no paid provider calls."""
import json
import re
import tempfile
import threading
import time
from pathlib import Path
from unittest.mock import patch

import httpx
from openai import OpenAI

from app.config import settings, ensure_directories
from app.database import init_db
from app.services import automation, translator, resources


def main():
    active = 0
    peak = 0
    requests = 0
    lock = threading.Lock()
    def request(req):
        nonlocal active, peak, requests
        with lock:
            active += 1
            peak = max(active, peak)
            requests += 1
        time.sleep(1)
        prompt = json.loads(req.content)['messages'][-1]['content']
        blocks = re.findall(r'BEGIN\[(\d+)\]\n(.*?)\nEND\[\1\]', prompt, re.S)
        content = '\n\n'.join(f'BEGIN[{i}]\nسلام، خوبی؟\nEND[{i}]' for i, _ in blocks)
        with lock:
            active -= 1
        return httpx.Response(200, json={'id':'mock','object':'chat.completion','created':0,
            'model':'mock','choices':[{'index':0,'message':{'role':'assistant','content':content},'finish_reason':'stop'}],
            'usage':{'prompt_tokens':100,'completion_tokens':100,'total_tokens':200}})
    def client():
        return OpenAI(api_key='sk-fixture', base_url='https://api.openai.com/v1', max_retries=0,
                      http_client=httpx.Client(transport=httpx.MockTransport(request)))
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        media = root/'media'
        media.mkdir()
        data = root/'data'
        with patch.multiple(settings, data_dir=data, database_path=data/'app.db',
                temp_dir=data/'temp', upload_dir=data/'uploads', output_dir=data/'outputs',
                media_root=None, dev_mode=True, openai_daily_budget_usd=0,
                openai_api_key='sk-fixture', openai_model='gpt-6-luna',
                openai_reasoning_effort='medium', openai_max_completion_tokens=32768,
                automation_job_concurrency=2, automation_api_concurrency=4), \
                patch.object(translator,'get_openai_client',client), \
                patch.object(automation,'list_subtitle_streams',lambda _: []), \
                patch('app.services.ffmpeg_service.get_media_info', lambda _: {'format':{'duration':'100'}}):
            ensure_directories()
            init_db()
            automation.init_schema()
            automation.save_config(False,[str(media)],{},'events_only')
            started = time.monotonic()
            for i in range(100):
                video = media/f'Fixture{i}.mkv'
                video.write_bytes(b'video mock; ffprobe mocked')
                video.with_suffix('.en.srt').write_text('\n\n'.join(
                    f'{n}\n00:{n // 60:02}:{n % 60:02},000 --> 00:{n // 60:02}:{n % 60:02},900\nHello, how are you? File {i}, line {n}.'
                    for n in range(1,81)))
                automation.enqueue(str(video),'sonarr' if i%2 else 'radarr')
                automation.enqueue(str(video),'bazarr')
            ingestion = time.monotonic()-started
            assert automation.counts()=={'queued':100}
            automation.save_config(True,[str(media)],{},'events_only')
            automation.worker.start()
            maximum_files = 0
            deadline = time.monotonic()+180
            try:
                while time.monotonic()<deadline:
                    counts = automation.counts()
                    maximum_files = max(maximum_files,counts.get('running',0))
                    if counts.get('done')==100:
                        break
                    assert not counts.get('failed'), counts
                    time.sleep(.1)
                assert automation.counts()=={'done':100}, automation.counts()
            finally:
                automation.pause()
                automation.worker.stop()
            assert requests==200 and maximum_files<=2 and peak<=4
            print(json.dumps({'files':100,'cues_per_file':80,'queue_ingestion_seconds':round(ingestion,3),
                'total_seconds':round(time.monotonic()-started,3),'active_files_peak':maximum_files,
                'api_requests_peak':peak,'mock_requests':requests,'outputs':len(list(media.glob('*.fa.srt'))),
                'pressure':resources.status(),'paid_requests':0}))


if __name__=='__main__':
    main()
