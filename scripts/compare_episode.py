"""Sequential, resumable full-source comparison with one persistent spending cap.

prepare makes no inference calls or library writes. live requires --allow-paid.
Use a separate process inside the development backend; never enable automation.
"""
import argparse
from copy import deepcopy
from decimal import Decimal, ROUND_CEILING
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import sys
import time
from uuid import uuid4

sys.path.insert(0, str(Path.cwd()))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from app.config import settings  # noqa: E402
from app.database import create_job, update_job  # noqa: E402
from app.models import has_persian_characters  # noqa: E402
from app.services import automation, translator, job_runner  # noqa: E402
from app.services.subtitle_io import read_srt, batch_subtitles, wrap_subtitle_text, write_srt  # noqa: E402
from app.services.validator import validate_subtitles  # noqa: E402

COMPARISON_GUIDANCE = "\nPreserve profanity and emotional intensity without censorship or gratuitous intensification. Keep character-specific voice, sarcasm, humor and idioms natural in contemporary Iranian Persian. Preserve HI sound descriptions, speaker labels and lyrics. Never invent dialogue or add credits, advertisements, model labels or watermark cues.\n"

VARIANTS = [
    {"id":"gpt-4o-mini","model":"gpt-4o-mini","effort":None,"cap":8192},
    {"id":"gpt-6-luna-none","model":"gpt-6-luna","effort":"none","cap":8192},
    {"id":"gpt-6-luna-medium","model":"gpt-6-luna","effort":"medium","cap":32768},
    {"id":"gpt-5.4-mini","model":"gpt-5.4-mini","effort":"none","cap":8192},
    {"id":"gpt-5.6-terra","model":"gpt-5.6-terra","effort":"none","cap":8192},
]


def digest(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(4*1024*1024), b""):
            h.update(chunk)
    return h.hexdigest()


def units(amount):
    return int((Decimal(str(amount))*1_000_000_000).to_integral_value(rounding=ROUND_CEILING))


def maximum(prompt, variant, rates):
    count = len((translator.SYSTEM_PROMPT+prompt).encode())+1024
    if count > 272000:
        raise ValueError("Comparison supports priced short-context requests only.")
    return units((Decimal(count)*Decimal(str(rates.get("input_ceiling",rates["input"])))
                  +Decimal(variant["cap"])*Decimal(str(rates["output"])))/1_000_000)


def request_parameters(variant, prompt):
    params = {"model":variant["model"],"messages":[
        {"role":"system","content":translator.SYSTEM_PROMPT},
        {"role":"user","content":prompt}],
        "max_completion_tokens":variant["cap"],"service_tier":"default"}
    if variant["effort"] is None:
        params["temperature"] = 0.1
    else:
        params["reasoning_effort"] = variant["effort"]
    return params


def validate_output(source, result):
    def ids(subs):
        return [(c.index,c.start.ordinal,c.end.ordinal) for c in subs]
    if ids(source) != ids(result):
        raise ValueError("Cue IDs, order or exact timestamps differ from the original.")
    report = validate_subtitles(result,"Persian")
    bad = []
    unchanged = []
    for original, translated in zip(source,result):
        plain_source = re.sub(r"<[^>]*>|\{[^}]*\}", "",original.text).strip()
        plain_result = re.sub(r"<[^>]*>|\{[^}]*\}", "",translated.text).strip()
        if not plain_result or (re.search(r"[A-Za-z]",plain_source) and not has_persian_characters(plain_result)):
            bad.append(original.index)
        if re.search(r"[A-Za-z]",plain_source) and plain_source == plain_result:
            unchanged.append(original.index)
    if not report["passed"] or bad or unchanged:
        raise ValueError(f"Invalid Persian cues: {bad}; unchanged English cues: {unchanged}")
    return {"cue_count":len(result),"exact_alignment":True,"blank_or_untranslated":bad,
            "unchanged_english":unchanged,"application_validation":report}


class Ledger:
    def __init__(self, path, plan, tasks):
        self.path = Path(path)
        self.limit = units(plan["budget_usd"])
        fingerprint = json.dumps(plan,sort_keys=True)
        with self.connect() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS config(id INTEGER PRIMARY KEY,value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS tasks(variant TEXT,number INTEGER,reservation INTEGER,
                    status TEXT DEFAULT 'pending',translations TEXT,PRIMARY KEY(variant,number));
                CREATE TABLE IF NOT EXISTS calls(id TEXT PRIMARY KEY,variant TEXT,number INTEGER,
                    reservation INTEGER,status TEXT,record TEXT);
                CREATE TABLE IF NOT EXISTS jobs(variant TEXT PRIMARY KEY,id TEXT);
            """)
            conn.execute("BEGIN IMMEDIATE")
            old = conn.execute("SELECT value FROM config WHERE id=1").fetchone()
            if old and old[0] != fingerprint:
                raise ValueError("Existing ledger plan differs; do not reset/bypass its budget.")
            conn.execute("INSERT OR IGNORE INTO config VALUES(1,?)",(fingerprint,))
            for variant,number,reserve in tasks:
                conn.execute("INSERT OR IGNORE INTO tasks(variant,number,reservation) VALUES(?,?,?)",
                             (variant,number,reserve))
        self.path.chmod(0o600)

    def connect(self):
        return sqlite3.connect(self.path,timeout=30)

    def reserve(self, variant, number, reserve, prompt_hash):
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            task = conn.execute("SELECT status,reservation FROM tasks WHERE variant=? AND number=?",
                                (variant,number)).fetchone()
            if not task or task[0] == "done":
                raise ValueError("Unexpected or already completed request task.")
            spent = conn.execute("SELECT COALESCE(SUM(reservation),0) FROM calls").fetchone()[0]
            future = conn.execute("SELECT COALESCE(SUM(reservation),0) FROM tasks WHERE status='pending'").fetchone()[0]
            if task[0] == "pending":
                future -= task[1]
            if spent + reserve + future > self.limit:
                raise RuntimeError("USD ceiling reached including unfinished model reservations; no request sent.")
            sequence = conn.execute("SELECT COUNT(*) FROM calls WHERE variant=? AND number=?",(variant,number)).fetchone()[0]+1
            key = uuid4().hex
            conn.execute("INSERT INTO calls VALUES(?,?,?,?,?,?)",(key,variant,number,reserve,"reserved",
                        json.dumps({"prompt_sha256":prompt_hash,"sequence_for_batch":sequence,"retry_or_repair":sequence>1})))
            conn.execute("UPDATE tasks SET status='started' WHERE variant=? AND number=?",(variant,number))
        return key

    def record(self, key, status, record):
        with self.connect() as conn:
            original = json.loads(conn.execute("SELECT record FROM calls WHERE id=?",(key,)).fetchone()[0])
            record = {**original,**record}
            conn.execute("UPDATE calls SET status=?,record=? WHERE id=?",(status,json.dumps(record,ensure_ascii=False),key))

    def cached(self, variant, number):
        with self.connect() as conn:
            row = conn.execute("SELECT translations FROM tasks WHERE variant=? AND number=? AND status='done'",
                               (variant,number)).fetchone()
        return {int(k):v for k,v in json.loads(row[0]).items()} if row else None

    def complete(self, variant, number, translated):
        with self.connect() as conn:
            conn.execute("UPDATE tasks SET status='done',translations=? WHERE variant=? AND number=?",
                         (json.dumps(translated,ensure_ascii=False),variant,number))

    def skip_existing(self, variant):
        with self.connect() as conn:
            conn.execute("UPDATE tasks SET status='done' WHERE variant=?",(variant,))

    def job(self, variant, source):
        with self.connect() as conn:
            row = conn.execute("SELECT id FROM jobs WHERE variant=?",(variant["id"],)).fetchone()
            if row:
                return row[0]
            job_id = uuid4().hex
            create_job(job_id, source.name, str(source), "Persian","English",
                       "natural_conversational",variant["model"])
            conn.execute("INSERT INTO jobs VALUES(?,?)",(variant["id"],job_id))
        return job_id

    def summary(self):
        with self.connect() as conn:
            rows = conn.execute("SELECT variant,reservation,status,record FROM calls ORDER BY rowid").fetchall()
        summary = {}
        for variant in VARIANTS:
            selected = [r for r in rows if r[0]==variant["id"]]
            records = [json.loads(r[3]) for r in selected]
            summary[variant["id"]] = {"requests":len(selected),
                "retry_or_repair_requests":sum(bool(r.get("retry_or_repair")) for r in records),
                "reserved_max_usd":sum(r[1] for r in selected)/1e9,
                "input_tokens":sum(r.get("input_tokens",0) for r in records),
                "output_tokens":sum(r.get("output_tokens",0) for r in records),
                "reasoning_tokens":sum(r.get("reasoning_tokens",0) for r in records),
                "api_seconds":sum(r.get("latency_seconds",0) for r in records),
                "usage_cost_usd":sum(r.get("usage_cost_usd",0) for r in records),
                "usage_cost_upper_usd":sum(r.get("usage_cost_upper_usd",0) for r in records),
                "unknown_usage_requests":sum(r[2]!="done" for r in selected),
                "errors":[r.get("error") for r in records if r.get("error")]}
        return summary


def provider(ledger, variant, rates, number, ensure_sources):
    def call(prompt):
        ensure_sources()
        prompt += COMPARISON_GUIDANCE
        reservation = maximum(prompt,variant,rates)
        key = ledger.reserve(variant["id"],number,reservation,hashlib.sha256(prompt.encode()).hexdigest())
        started = time.monotonic()
        try:
            with translator.get_openai_client() as base:
                if str(base.base_url).rstrip("/") != "https://api.openai.com/v1":
                    raise ValueError("Verified prices apply only to the official OpenAI endpoint.")
                response = base.with_options(max_retries=0,timeout=180).chat.completions.create(
                    **request_parameters(variant,prompt))
            usage = response.usage
            if usage is None:
                raise RuntimeError("Provider response has no usage; its full reservation remains charged.")
            raw_usage = usage.model_dump()
            detail = raw_usage.get("prompt_tokens_details") or {}
            cache = detail.get("cached_tokens") or 0
            write = detail.get("cache_write_tokens",raw_usage.get("cache_write_tokens"))
            normal = usage.prompt_tokens - cache - (write or 0)
            cached_rate = rates.get("cached_input",rates["input"])
            cost = (normal*rates["input"]+cache*cached_rate+(write or 0)*rates.get("cache_write",rates.get("input_ceiling",rates["input"]))
                    +usage.completion_tokens*rates["output"])/1e6
            upper = cost
            if write is None:
                upper += normal*(rates.get("input_ceiling",rates["input"])-rates["input"])/1e6
            record = {"usage":raw_usage,"input_tokens":usage.prompt_tokens,
                "output_tokens":usage.completion_tokens,
                "reasoning_tokens":(raw_usage.get("completion_tokens_details") or {}).get("reasoning_tokens") or 0,
                "usage_cost_usd":cost,"usage_cost_upper_usd":upper,
                "cache_write_usage_exposed":write is not None,
                "latency_seconds":time.monotonic()-started,
                "response_model":response.model,"request_id":getattr(response,"_request_id",None),
                "finish_reason":response.choices[0].finish_reason if response.choices else None}
            ledger.record(key,"done",record)
            if not response.choices or response.choices[0].finish_reason != "stop":
                raise RuntimeError(f"Incompatible/truncated provider response: {record['finish_reason']}")
            answer = response.choices[0].message.content or ""
            parsed = translator.parse_translated_blocks(answer)
            return translator.TranslationResult(parsed.translations,usage.prompt_tokens,
                usage.completion_tokens,usage.total_tokens,answer,parsed.returned_indexes,
                parsed.duplicate_indexes,parsed.malformed_block_count)
        except Exception as exc:
            # Preserve recorded usage for billable but invalid/truncated responses.
            with ledger.connect() as conn:
                row = conn.execute("SELECT status FROM calls WHERE id=?",(key,)).fetchone()
            if row[0] != "done":
                ledger.record(key,"error",{"error":f"{type(exc).__name__}: {exc}",
                                          "latency_seconds":time.monotonic()-started})
            raise
    return call


def run(video, source, pricing_file, budget=5, live=False):
    video, source = Path(video).resolve(), Path(source).resolve()
    if source.parent != video.parent or not video.is_file() or not source.is_file():
        raise ValueError("Select an existing video and its explicit same-directory English subtitle.")
    if video.suffix.lower() not in {".mkv",".mp4",".avi",".m4v"} or source.suffix.lower() != ".srt":
        raise ValueError("Unsupported explicit video/SRT selection.")
    if automation.config()["enabled"]:
        raise ValueError("Unattended automation must remain paused.")
    if os.getenv("UST_PILOT_BUDGET_FILE"):
        raise ValueError("Do not combine separate pilot ledgers.")
    source_hash, video_hash = digest(source), digest(video)
    video_stat = video.stat()
    subs = read_srt(source)
    if not subs or len({s.index for s in subs})!=len(subs) or any(not s.text.strip() or s.end<=s.start for s in subs):
        raise ValueError("Source contains empty/invalid/duplicate cues.")
    batches = list(batch_subtitles(subs,40,12000,"English",context_cues=2,context_gap_seconds=15))
    prices = json.loads(Path(pricing_file).read_text())
    prompts = [translator.build_batch_prompt(b,"Persian","natural_conversational","English")+COMPARISON_GUIDANCE for b in batches]
    tasks = [(v["id"],n,maximum(p,v,prices["models"][v["model"]]))
             for v in VARIANTS for n,p in enumerate(prompts,1)]
    ceiling = sum(t[2] for t in tasks)/1e9
    if not Decimal(str(budget)).is_finite() or budget <= 0 or ceiling > budget:
        raise ValueError(f"First-pass reserved maximum USD {ceiling:.6f} exceeds approved USD {budget}; no inference made.")
    plan = {"video":str(video),"source":str(source),"source_sha256":source_hash,"video_sha256":video_hash,
        "cue_count":len(subs),"batch_count":len(batches),"variants":VARIANTS,"budget_usd":budget,
        "first_pass_reserved_usd":ceiling,"prices":prices,"style":"natural_conversational",
        "batch_size":40,"max_chars":12000,"context_cues":2,"context_gap_seconds":15,
        "prompt_hashes":[hashlib.sha256(p.encode()).hexdigest() for p in prompts]}
    run_id = hashlib.sha256((str(video)+"\n"+str(source)).encode()).hexdigest()[:20]
    directory = settings.data_dir/"comparisons"/run_id
    directory.mkdir(parents=True,exist_ok=True)
    directory.chmod(0o700)
    with (directory/"run.lock").open("a") as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        ledger = Ledger(directory/"cost.sqlite",plan,tasks)
        (directory/"plan.json").write_text(json.dumps(plan,indent=2))
        print(json.dumps({"run_dir":str(directory),"cues":len(subs),"batches":len(batches),
                          "first_pass_max_usd":ceiling,"operational_max_usd":budget}),flush=True)
        if not live:
            return plan
        if not settings.openai_api_key:
            raise ValueError("No provider credential configured; no inference made.")
        with translator.get_openai_client() as client:
            for variant in VARIANTS:
                client.models.retrieve(variant["model"])
        existing = {str(p):digest(p) for p in source.parent.iterdir()
                    if p.is_file() and p.suffix.lower() in {".srt",".ass",".ssa",".vtt",".idx",".sub"}
                    and p.name not in [video.stem+"."+v["id"]+".fa.srt" for v in VARIANTS]}
        def ensure_sources():
            if automation.config()["enabled"]:
                raise RuntimeError("Unattended automation was enabled unexpectedly.")
            if digest(source)!=source_hash or video.stat().st_size!=video_stat.st_size or video.stat().st_mtime_ns!=video_stat.st_mtime_ns:
                raise RuntimeError("Original source/video changed.")
        outcomes = {}
        old_call, old_model = translator.call_openai, settings.openai_model
        started = time.monotonic()
        try:
            for variant in VARIANTS:
                output = video.with_name(video.stem+"."+variant["id"]+".fa.srt")
                if output.exists():
                    outcomes[variant["id"]]={"status":"preserved_existing","path":str(output),
                        "validation":validate_output(subs,read_srt(output)),"sha256":digest(output)}
                    ledger.skip_existing(variant["id"])
                    continue
                ensure_sources()
                translated_subs = deepcopy(subs)
                job_id = ledger.job(variant,source)
                settings.openai_model = variant["model"]
                update_job(job_id,status="running",message="Explicit comparison: "+variant["id"],total_subtitles=len(subs))
                try:
                    for number,batch in enumerate(batches,1):
                        translated = ledger.cached(variant["id"],number)
                        if translated is None:
                            translator.call_openai = provider(ledger,variant,prices["models"][variant["model"]],number,ensure_sources)
                            translated = job_runner.translate_batch_with_repair(job_id,batch,"English","Persian",
                                "natural_conversational",number,len(batches),cancel_check=ensure_sources)
                            by_id = {c.index:c for c in subs}
                            candidate = type(subs)([deepcopy(by_id[item["index"]]) for item in batch])
                            for cue in candidate:
                                cue.text = translated[cue.index]
                            source_batch = type(subs)([by_id[item["index"]] for item in batch])
                            try:
                                validate_output(source_batch,candidate)
                            except ValueError:
                                bad_ids = {cue.index for cue in candidate if not cue.text.strip()
                                    or (re.search(r"[A-Za-z]",re.sub(r"<[^>]*>|\{[^}]*\}", "",by_id[cue.index].text))
                                        and (not has_persian_characters(cue.text) or cue.text.strip()==by_id[cue.index].text.strip()))}
                                if not bad_ids:
                                    raise
                                repair = job_runner.translate_batch_with_repair(job_id,
                                    [item for item in batch if item["index"] in bad_ids],"English","Persian",
                                    "natural_conversational",number,len(batches),cancel_check=ensure_sources)
                                translated.update(repair)
                                for cue in candidate:
                                    cue.text = translated[cue.index]
                                validate_output(source_batch,candidate)
                            ledger.complete(variant["id"],number,translated)
                        for cue in translated_subs:
                            if cue.index in translated:
                                cue.text = wrap_subtitle_text(translated[cue.index],"Persian")
                        done = min(number*40,len(subs))
                        update_job(job_id,translated_count=done,progress_percent=int(number*100/len(batches)),
                                   message=f"{variant['id']}: batch {number}/{len(batches)}")
                        print(json.dumps({"variant":variant["id"],"batch":number,"batches":len(batches)}),flush=True)
                    validation = validate_output(subs,translated_subs)
                    ensure_sources()
                    write_srt(translated_subs,output,overwrite=False,add_credit=False)
                    validation = validate_output(subs,read_srt(output))
                    outcomes[variant["id"]]={"status":"done","path":str(output),"validation":validation,"sha256":digest(output)}
                    update_job(job_id,status="done",output_file=output.name,output_path=str(output),progress_percent=100,
                               message="Explicit comparison completed: "+variant["id"])
                except Exception as exc:
                    outcomes[variant["id"]]={"status":"failed","error":f"{type(exc).__name__}: {exc}","path":str(output)}
                    update_job(job_id,status="failed",error=str(exc),message="Comparison failed: "+variant["id"])
                    print(json.dumps({"variant":variant["id"],"error":type(exc).__name__}),flush=True)
                (directory/"results.json").write_text(json.dumps({"outcomes":outcomes,"models":ledger.summary()},ensure_ascii=False,indent=2))
        finally:
            translator.call_openai, settings.openai_model = old_call, old_model
        ensure_sources()
        if digest(video)!=video_hash or digest(source)!=source_hash or any(digest(p)!=h for p,h in existing.items()):
            raise RuntimeError("Original video/subtitle preservation check failed.")
        result = {"outcomes":outcomes,"models":ledger.summary(),"processing_seconds":time.monotonic()-started,
                  "originals_unchanged":True,"ledger":str(ledger.path)}
        (directory/"results.json").write_text(json.dumps(result,ensure_ascii=False,indent=2))
        print(json.dumps({"complete":sum(o["status"]!="failed" for o in outcomes.values()),
                          "results":str(directory/"results.json")}),flush=True)
        return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--video",required=True)
    p.add_argument("--source",required=True)
    p.add_argument("--pricing-file",required=True)
    p.add_argument("--budget-usd",type=float,default=5)
    p.add_argument("--allow-paid",action="store_true")
    args = p.parse_args()
    run(args.video,args.source,args.pricing_file,args.budget_usd,args.allow_paid)


if __name__=="__main__":
    main()
