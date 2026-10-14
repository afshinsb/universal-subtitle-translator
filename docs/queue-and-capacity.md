# Automatic queue and capacity

New import events commit one SQLite row per canonical physical media path. Duplicate
imports and Bazarr wakeups reuse that row. Events-only discovery does not enumerate
the library; Bazarr cannot create historical work. Waiting English sources consume
no translation attempts. Existing Persian sidecars and embedded tracks are preserved.

The scheduler admits at most two files, with a bounded pool and no task for each
pending item. Due work is FIFO by original arrival, independent of service. Files
have fenced owners, renewable five-minute leases, retry backoff and cancellation
through pause. SQLite checkpoints retain completed translation batches across
retries/restarts. Batch identity includes source hash, model, reasoning, style and
segmentation/context policy. Two batches per active file can run concurrently;
completion order does not affect cue ordering or timestamps.

A separate renewable SQLite semaphore caps all API requests at four and all
FFprobe/FFmpeg commands at one. Host available memory, memory PSI, CPU load and
container working-set headroom reduce admission to one file/one request when busy.
Provider throttling temporarily reduces capacity. Hard limits always apply. The
controller returns to the measured configured capacity after pressure clears;
it never creates replicas or unbounded futures. Host pressure includes competition
from Jellyfin and downloads, without reading the Docker socket inside UST.

Initial production limits: 1.5 CPUs, 1024 MiB backend; 128 MiB frontend; 64 MiB
gateway. Prime has six vCPUs and roughly 1.5 GiB available memory at preflight.
Memory pressure below 768 MiB available or 128 MiB container headroom reduces
admission. These limits bound throughput rather than promising four requests under
all host loads. Large imports are persistent metadata, not in-memory translations.

The official Luna Medium request cap remains 32768 including hidden reasoning.
Automatic batches initially allow 16384; a provider length response retains its
usage and retries with 32768. Coyote's measured largest completion was 2443,
including 1416 reasoning tokens. Context is precomputed from the English source;
parallelization does not use other batches' generated Persian as input.

The UTC daily ledger atomically reserves worst-case input and capped output costs
before every call, including repairs and retries. Confirmed response usage settles
at verified standard-tier rates. Uncertain/failed calls retain the full bound.
Reservations and usage survive restart. Budget exhaustion waits until next UTC day;
completed checkpoints are reused. Production initially has USD 5/day. Changing
pricing/model/limit requires an audited policy update; deleting a ledger is forbidden.

Exactly-once remote billing cannot be guaranteed after an ambiguous network loss:
OpenAI may complete a request whose response never arrives. Such requests remain
reserved; completed local results are never intentionally billed twice. Lease
fencing and atomic no-overwrite publication protect outputs from stale workers.

The automation page shows queue status, progress, batch detail, queue position,
per-file cost, estimated remaining time, resource admission and daily usage.
Docker logs rotate at 10 MiB with three files. Manual history is retained.
