"""Read-only title enrichment and download lifecycle reconciliation.

Nothing here creates a translation job, changes Arr settings, or controls torrents.
"""
import json
import time
import urllib.parse
from pathlib import Path

from app.database import get_connection, utc_now

TERMINAL = {'imported', 'download_removed', 'download_untracked', 'request_completed',
            'request_available', 'request_deleted', 'request_declined', 'request_blocked'}
DOWNLOAD_STATES = ('downloading', 'download_queued', 'download_paused', 'download_stalled',
                   'download_failed', 'download_untracked', 'completed_not_imported', 'import_failed', 'import_rejected')


def init_schema():
    with get_connection() as c:
        c.execute('CREATE TABLE IF NOT EXISTS upstream_metadata (identity TEXT PRIMARY KEY,payload TEXT NOT NULL)')
        c.execute('''CREATE TABLE IF NOT EXISTS intake_title_cache (
            identity TEXT PRIMARY KEY, title TEXT NOT NULL, expires REAL NOT NULL)''')
        c.execute('CREATE INDEX IF NOT EXISTS upstream_download ON upstream_activity(service,download_id)')
        c.execute('CREATE INDEX IF NOT EXISTS upstream_normalized_download ON upstream_activity(service,lower(download_id),media_id)')


def title(service, key, fallback, loader, allowance):
    """Bound metadata API requests; cache failures briefly as well as real titles."""
    identity = service + ':' + str(key)
    with get_connection() as c:
        row = c.execute('SELECT title,expires FROM intake_title_cache WHERE identity=?', (identity,)).fetchone()
    if row and row['expires'] > time.time():
        return row['title'] or fallback
    if allowance[0] <= 0:
        return (row['title'] if row else '') or fallback
    allowance[0] -= 1
    try:
        value = loader()
        result = value.get('title') or value.get('name') or ''
    except Exception:
        result = row['title'] if row else ''
    with get_connection() as c:
        c.execute('INSERT OR REPLACE INTO intake_title_cache VALUES(?,?,?)',
                  (identity, result, time.time() + (43200 if result else 120)))
    return result or fallback


def enrich_arr(service, record, allowance):
    from app.services.media_intake import api
    item = record.get('movie' if service == 'radarr' else 'series') or {}
    item_id = record.get('movieId' if service == 'radarr' else 'seriesId') or item.get('id')
    release = record.get('title') or record.get('sourceTitle') or ''
    display = item.get('title')
    if not display and item_id:
        display = title(service, item_id, release, lambda: api(service, 'api/v3/' + ('movie/' if service == 'radarr' else 'series/') + str(item_id)), allowance)
    episode = record.get('episode') or {}
    return {**record, '_ust': {'display_title': display or release or 'Media download',
        'release_title': release, 'arr_item': item_id,
        'season': episode.get('seasonNumber'), 'episode': episode.get('episodeNumber'),
        'episode_title': episode.get('title'), 'kind': 'movie' if service == 'radarr' else 'tv'}}


def refresh_stored_titles(service, allowance):
    """Enrich old observations without querying or scanning the media library."""
    import re
    with get_connection() as c:
        rows = c.execute("SELECT a.identity,a.media_id,a.title,coalesce(m.payload,'{}') AS metadata FROM upstream_activity a LEFT JOIN upstream_metadata m ON m.identity=a.identity WHERE a.service=? AND (json_extract(coalesce(m.payload,'{}'),'$.display_title') IS NULL OR json_extract(m.payload,'$.title_pending')=1) ORDER BY a.updated_at DESC LIMIT 100", (service,)).fetchall()
    for row in rows:
        match = re.search(r'series:(\d+)', row['media_id'] or '')
        item_id = int(match.group(1)) if match else int(row['media_id']) if (row['media_id'] or '').isdigit() else None
        if not item_id:
            continue
        record = {'seriesId' if service == 'sonarr' else 'movieId': item_id, 'title': row['title']}
        enriched = enrich_arr(service, record, allowance)['_ust']
        with get_connection() as c:
            cached = c.execute('SELECT title FROM intake_title_cache WHERE identity=?', (service+':'+str(item_id),)).fetchone()
        enriched['title_pending'] = not cached or not cached['title']
        with get_connection() as c:
            c.execute('UPDATE upstream_activity SET title=? WHERE identity=?', (enriched['display_title'],row['identity']))
            c.execute('INSERT OR REPLACE INTO upstream_metadata VALUES(?,?)',(row['identity'],json.dumps(enriched)))


def seerr_record(request, allowance):
    from app.services.media_intake import api
    media = request.get('media') or {}
    kind = request.get('type')
    tmdb = media.get('tmdbId')
    fallback = media.get('title') or media.get('name') or (media.get('externalServiceSlug') or '').replace('-', ' ').title() or ('TV request' if kind == 'tv' else 'Movie request')
    resolved = fallback
    if kind in {'tv', 'movie'} and isinstance(tmdb, int) and tmdb > 0:
        resolved = title('seerr', kind + ':' + str(tmdb), fallback,
                         lambda: api('seerr', 'api/v1/' + kind + '/' + str(tmdb)), allowance)
    status = {1: 'requested', 2: 'requested_approved', 3: 'request_declined',
              4: 'request_failed', 5: 'request_completed'}.get(request.get('status'), 'requested')
    media_state = media.get('status4k' if request.get('is4k') else 'status')
    if status not in {'request_declined', 'request_failed'}:
        status = {4: 'request_partial', 5: 'request_available', 6: 'request_blocked',
                  7: 'request_deleted'}.get(media_state, status)
    record = {'id': request['id'], 'title': resolved,
              'mediaId': media.get('externalServiceId4k' if request.get('is4k') else 'externalServiceId'),
              '_ust': {'display_title': resolved, 'kind': kind, 'tmdb_id': tmdb,
                       'arr_service': 'sonarr' if kind == 'tv' else 'radarr',
                       'seasons': [s.get('seasonNumber') for s in request.get('seasons', [])]}}
    return record, status


def poll_seerr(cursor):
    """Always refresh newest requests, plus one rotating older page for lifecycle changes."""
    from app.services.media_intake import api, upstream
    newest = api('seerr', 'api/v1/request?take=25&skip=0&sort=added')
    pages = max(1, int((newest.get('pageInfo') or {}).get('pages') or 1))
    page = max(2, min(int(cursor.get('page') or 2), pages)) if pages > 1 else 1
    records = list(newest.get('results', []))
    if page > 1:
        older = api('seerr', 'api/v1/request?' + urllib.parse.urlencode({'take':25,'skip':(page-1)*25,'sort':'added'}))
        records.extend(older.get('results', []))
    allowance = [6]
    for request in records:
        record, state = seerr_record(request, allowance)
        upstream('seerr', record, state)
    with get_connection() as c:
        c.execute("UPDATE intake_cursors SET page=? WHERE service='seerr'", (page+1 if page < pages else 2 if pages>1 else 1,))


def reconcile_missing(service, seen, complete):
    """Absence only counts after a complete successful queue read and exact qBit read."""
    from app.services import media_intake
    if not complete:
        return
    with get_connection() as c:
        rows = c.execute("SELECT identity,download_id FROM upstream_activity WHERE service=? AND identity LIKE ? AND state IN (" + ','.join('?' for _ in DOWNLOAD_STATES) + ") ORDER BY updated_at LIMIT 500",
                         (service, service + ':queue:%', *DOWNLOAD_STATES)).fetchall()
    missing = [dict(r) for r in rows if r['identity'] not in seen]
    hashes = list(dict.fromkeys(r['download_id'].lower() for r in missing if r['download_id']))[:100]
    if not hashes:
        return
    if 'qbit' not in media_intake.services():
        return  # No unverified deletion claims.
    torrents = media_intake.api('qbit', 'api/v2/torrents/info?' + urllib.parse.urlencode({'hashes': '|'.join(hashes)}))
    present = {t['hash'].lower(): t for t in torrents}
    with get_connection() as c:
        for hash_value in hashes:
            imported = c.execute('SELECT id FROM media_intake WHERE service=? AND lower(download_id)=? LIMIT 1', (service, hash_value)).fetchone()
            torrent = present.get(hash_value)
            state = 'imported' if imported else 'download_removed' if torrent is None else 'download_failed' if torrent.get('state') in {'error','missingFiles'} else 'completed_not_imported' if torrent.get('progress', 0) >= 1 else 'download_untracked'
            reason = '' if imported else 'No longer present in the download client or ' + service.title() + ' queue.' if torrent is None else 'Still in the download client, but no longer tracked by ' + service.title() + '. No imported file has been reported.'
            # Keep previous import-failure reasons available alongside the lifecycle change.
            c.execute("UPDATE upstream_activity SET state=?,progress=CASE WHEN ?='download_removed' THEN NULL ELSE progress END,error=?,updated_at=? WHERE lower(download_id)=? AND state IN (" + ','.join('?' for _ in DOWNLOAD_STATES + ('download_complete',)) + ')',
                      (state, state, reason, utc_now(), hash_value, *DOWNLOAD_STATES, 'download_complete'))


def removed_by_guard(hash_value):
    with get_connection() as c:
        c.execute("UPDATE upstream_activity SET state='download_removed',progress=NULL,error='Removed by Download Guard: confirmed invalid executable download.',updated_at=? WHERE lower(download_id)=? AND state!='imported'",
                  (utc_now(), hash_value.lower()))


def display_name(title_value, path):
    """Use verified media title and filename episode notation only for presentation."""
    import re
    name = Path(path or '').name
    episode = re.search(r'(?i)S\d{1,3}E\d{1,4}(?:(?:-?E|-)\d{1,4})*', name)
    if title_value and episode:
        return title_value + ' · ' + episode.group().upper()
    return title_value or name or 'Media'


# Deduplicate one physical download, while imported files remain independent.
# The SQL is used by pagination and summary counts so their totals agree.
UPSTREAM_VIEW = """(
 SELECT r.*,(SELECT count(DISTINCT g.media_id) FROM upstream_activity g WHERE g.service=r.service AND lower(g.download_id)=lower(r.download_id) AND g.media_id NOT LIKE '%:episode:None') AS related_records FROM (
  SELECT a.*,coalesce(m.payload,'{}') AS metadata,
   row_number() OVER(PARTITION BY a.service,CASE WHEN a.download_id IS NOT NULL AND a.download_id!='' THEN lower(a.download_id) ELSE a.identity END ORDER BY a.updated_at DESC,a.identity DESC) AS rank
  FROM upstream_activity a LEFT JOIN upstream_metadata m ON m.identity=a.identity
  WHERE service!='qbit' OR NOT EXISTS(SELECT 1 FROM upstream_activity b WHERE b.service IN ('sonarr','radarr') AND lower(b.download_id)=lower(a.download_id))
 ) r WHERE rank=1
)"""
