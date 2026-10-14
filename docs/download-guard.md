# Download Guard

Optional background task in the UST backend, independent of translation and intake.
Every five minutes it requests up to 20 torrents per approved category (`tv-sonarr`,
`radarr`) and their file lists. Larger lists rotate through a persisted offset.
No recursive scan, hashing, downloaded code execution, antivirus or extra container.

Enable `DOWNLOAD_GUARD_ENABLED=true` for the initial dry run, and mount the completed
qBittorrent download root **read-only**:

```yaml
volumes:
  - /tank/share/downloads:/downloads-guard:ro
environment:
  DOWNLOAD_GUARD_ENABLED: 'true'
  DOWNLOAD_GUARD_ROOT: /downloads-guard
  DOWNLOAD_GUARD_QBIT_ROOT: /downloads
```

The existing private `DATA_DIR/media-services.json` qbit connection is reused;
keep that file mode 0600 and outside Git. Back up the persistent application database,
service credentials, settings and mount mapping for migration/reinstallation.
The Automation page enables/disables scanning and automatic removal. Removal defaults
off and cannot be enabled before a dry run. Disable Guard independently of translation.

All requested dangerous extensions are detected case-insensitively. Strict automatic
removal additionally requires: completed/stable files observed at least five minutes
apart; only executable files; conclusive tiny-header format confirmation (PE, MSI or
Windows shortcut); exact safe paths without symlinks/hardlinks; matching qBittorrent
metadata; fresh Arr completed-import rejection explicitly reporting no eligible video;
no accepted UST import for the same hash. Immediately recheck torrent identity, state,
paths and Arr rejection before calling qBittorrent's delete API with `deleteFiles=true`.
UST never deletes through filesystem operations. Ambiguous scripts/COM, mixed contents,
archives, potential media, incomplete downloads, personal categories and uncertain
imports are reported without deletion. Valid-media seeding remains untouched.

Recent activities are deduplicated and bounded to 500 records. Confirmation identities
expire after 30 days; completed removal identities remain to count removals. Failed API
deletions are logged and require a fresh complete classification on subsequent scans.
The UI shows dry run / automatic mode, suspicious and removed counts, scan time and errors.

On Prime, `findmnt -T /tank/share/downloads` identifies **tank/share** mounted at
`/tank/share`, rather than an independent downloads dataset. Changing its `exec` property
would affect the whole shared dataset, including unrelated paths. No ZFS property was
changed. `exec=off` also does not prevent scripts from being read by an interpreter;
it is not a substitute for this narrow torrent policy.
