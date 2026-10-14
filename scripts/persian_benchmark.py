"""Prepare/mock quality evaluation; live calls require explicitly approved budget flags."""
import argparse
import csv
import hashlib
import json
import math
import os
import random
import sys
import time
from pathlib import Path

os.environ["PYTHON_DOTENV_DISABLED"] = "1"
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from app.services.translator import build_batch_prompt, parse_translated_blocks, SYSTEM_PROMPT  # noqa: E402


def scenes():
    return json.loads((ROOT / "benchmarks/persian_dialogue.json").read_text())["cases"]


def target_cues(case):
    # Only the middle cue is translated; context adds genuinely new information.
    return [case["cues"][1]]


def payload(case, context):
    import pysrt
    from app.services.subtitle_io import batch_subtitles
    subs = pysrt.SubRipFile([pysrt.SubRipItem(index=c["id"],
        start=pysrt.SubRipTime(milliseconds=c["start_ms"]),
        end=pysrt.SubRipTime(milliseconds=c["end_ms"]),text=c["text"]) for c in case["cues"]])
    batch = list(batch_subtitles(subs,40,12000,"English",
        context_cues=2 if context else 0,context_gap_seconds=15))
    if len(batch) != 1:
        raise ValueError("Benchmark scene must fit one production-sized batch.")
    selected = [item for item in batch[0] if item["index"] == target_cues(case)[0]["id"]]
    return build_batch_prompt(selected,"Persian","natural_conversational","English")


def run(output, models, mode="prepare", allow_paid=False, budget_usd=0):
    catalog = json.loads((ROOT/"benchmarks/models.json").read_text())
    if mode == "live" and (not allow_paid or not math.isfinite(budget_usd) or budget_usd <= 0):
        raise ValueError("Live evaluation requires --allow-paid and a positive --budget-usd after user approval.")
    if any(model not in catalog["models"] for model in models):
        raise ValueError("Select a model with verified endpoint/pricing metadata.")
    plan = []
    max_output = 2048
    for model in models:
        rates = catalog["models"][model]
        for case in scenes():
            for context in [False,True]:
                prompt = payload(case,context)
                # UTF-8 byte count plus overhead conservatively bounds input tokens.
                maximum = ((len((SYSTEM_PROMPT + prompt).encode())+1024)*rates.get("input_ceiling", rates["input"]) + max_output*rates["output"])/1_000_000
                plan.append((model,case,context,prompt,maximum))
    ceiling = sum(item[4] for item in plan)
    if mode == "live" and ceiling > budget_usd:
        raise ValueError(f"Maximum USD {ceiling:.4f} exceeds approved budget USD {budget_usd:.4f}; no calls made.")
    output = Path(output)
    output.mkdir(parents=True,exist_ok=True)
    import pysrt
    from app.services.subtitle_io import write_srt
    def save_cues(cues, destination, translated=False):
        subs = pysrt.SubRipFile([pysrt.SubRipItem(index=c["id"],
            start=pysrt.SubRipTime(milliseconds=c["start_ms"]),
            end=pysrt.SubRipTime(milliseconds=c["end_ms"]),
            text=c["translation"] if translated else c["text"]) for c in cues])
        write_srt(subs, destination, add_credit=False)
    for case in scenes():
        save_cues(target_cues(case), output/"source-en"/(case["id"]+".en.srt"))
    manifest = {"mode":mode,"models":models,"scenes":len(scenes()),
        "variants":["no_context","surrounding_context"],"calls_planned":len(plan),
        "max_output_tokens":max_output,"conservative_cost_ceiling_usd":ceiling,
        "target":"middle cue only; neighbors are reference only","context_cues":2,"context_gap_seconds":15,"neighbor_max_chars":500,
        "request_parameters":{m:{"service_tier":"default","max_completion_tokens":max_output,
            **({"reasoning_effort":catalog["models"][m]["reasoning_effort"]} if catalog["models"][m]["reasoning"] else {"temperature":0.1})} for m in models},
        "pricing_verified":catalog["verified_date"],
        "shuffle_seed":42,"system_prompt":SYSTEM_PROMPT,"sdk_max_retries":0,
        "cost_reporting":"usage valued at conservative input/cache-write ceiling; invoice may be lower",
        "pricing_hash":hashlib.sha256((ROOT/"benchmarks/models.json").read_bytes()).hexdigest(),
        "prompt_hashes":[hashlib.sha256(p.encode()).hexdigest() for _,_,_,p,_ in plan],
        "fixture_hash":hashlib.sha256((ROOT/"benchmarks/persian_dialogue.json").read_bytes()).hexdigest()}
    (output/"manifest.json").write_text(json.dumps(manifest,indent=2))
    if mode == "prepare":
        (output/"prompts.json").write_text(json.dumps([{"model":m,"case":c["id"],"context":ctx,
            "prompt":p,"maximum_cost_usd":cost} for m,c,ctx,p,cost in plan],ensure_ascii=False,indent=2))
        return manifest
    client = None
    if mode == "live":
        from openai import OpenAI
        if not os.getenv("OPENAI_API_KEY"):
            raise ValueError("Supply the key through the environment, never arguments.")
        client = OpenAI(max_retries=0,timeout=60)
    results = []
    try:
        for model,case,context,prompt,maximum in plan:
            started = time.monotonic()
            usage = {"input_tokens":0,"output_tokens":0}
            if mode == "mock":
                answer = "\n\n".join(f"BEGIN[{c['id']}]\nترجمهٔ آزمایشی\nEND[{c['id']}]" for c in target_cues(case))
            else:
                rates = catalog["models"][model]
                kwargs = {"model":model,"messages":[{"role":"system","content":SYSTEM_PROMPT},
                    {"role":"user","content":prompt}],"max_completion_tokens":max_output,"service_tier":"default"}
                if rates["reasoning"]:
                    kwargs["reasoning_effort"] = rates["reasoning_effort"]
                else:
                    kwargs["temperature"] = 0.1
                response = client.chat.completions.create(**kwargs)
                answer = response.choices[0].message.content or ""
                usage = {"input_tokens":response.usage.prompt_tokens,"output_tokens":response.usage.completion_tokens}
            parsed = parse_translated_blocks(answer)
            expected = [cue["id"] for cue in target_cues(case)]
            aligned = parsed.returned_indexes == expected and not parsed.duplicate_indexes and not parsed.malformed_block_count
            aligned = aligned and all(parsed.translations.get(index,"").strip() for index in expected)
            rates = catalog["models"][model]
            results.append({"model":model,"case":case["id"],"context":context,"aligned":bool(aligned),
                "latency_seconds":time.monotonic()-started,
                "cues":[{**cue,"translation":parsed.translations.get(cue["id"],"")} for cue in target_cues(case)],
                "scene_source":" | ".join(c["text"] for c in case["cues"]),
                "usage":usage,"cost_usd":(usage["input_tokens"]*rates.get("input_ceiling",rates["input"])+usage["output_tokens"]*rates["output"])/1_000_000})
            if aligned:
                save_cues(results[-1]["cues"], output/model/("context" if context else "no-context")/(case["id"]+".fa.srt"), True)
            (output/"results.json").write_text(json.dumps(results,ensure_ascii=False,indent=2))
    finally:
        if client:
            client.close()
    (output/"results.json").write_text(json.dumps(results,ensure_ascii=False,indent=2))
    blinded = list(results)
    random.Random(42).shuffle(blinded)
    reviewer = output/"reviewer"
    reviewer.mkdir(exist_ok=True)
    with (output/"blind-review.csv").open("w",newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["review_id","scene","scene_source","target_source","translation","naturalness_0_5","meaning_0_5",
                         "tone_humor_0_5","context_0_5","readability_0_5","character_voice_0_5","profanity_register_0_5","notes"])
        for number,row in enumerate(blinded,1):
            writer.writerow([number,row["case"],row["scene_source"]," | ".join(c["text"] for c in row["cues"]),
                " | ".join(c["translation"] for c in row["cues"]),"","","","","","","",""])
    (reviewer/"blind-review.csv").write_bytes((output/"blind-review.csv").read_bytes())
    for number, row in enumerate(blinded, 1):
        if row["aligned"]:
            save_cues(row["cues"], reviewer/f"{number:03d}.fa.srt", True)
    (output/"review-key.json").write_text(json.dumps([{"review_id":n,"model":row["model"],"case":row["case"],"context":row["context"]}
        for n,row in enumerate(blinded,1)],indent=2))
    manifest.update(calls_made=0 if mode=="mock" else len(results), aligned=sum(row["aligned"] for row in results),
                    actual_cost_usd=sum(row["cost_usd"] for row in results))
    (output/"manifest.json").write_text(json.dumps(manifest,indent=2))
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode",choices=["prepare","mock","live"],default="prepare")
    parser.add_argument("--models",nargs="+",default=["gpt-4o-mini","gpt-5.4-mini","gpt-5.6-terra","gpt-6-luna"])
    parser.add_argument("--output",default=str(ROOT/"dev/runtime/benchmark"))
    parser.add_argument("--allow-paid",action="store_true")
    parser.add_argument("--budget-usd",type=float,default=0)
    args = parser.parse_args()
    try:
        print(json.dumps(run(args.output,args.models,args.mode,args.allow_paid,args.budget_usd)))
    except ValueError as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
