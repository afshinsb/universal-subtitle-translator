import json
import re
from types import SimpleNamespace

import pytest

from app.config import settings
from app.database import init_db
from app.services import automation, translator
from app.services.subtitle_io import read_srt
from scripts.compare_episode import Ledger, VARIANTS, run, validate_output, request_parameters


def setup(tmp_path,monkeypatch):
    settings.data_dir.mkdir(parents=True,exist_ok=True)
    init_db()
    automation.init_schema()
    movie = tmp_path/"Episode.mkv"
    source = tmp_path/"Episode.en.hi.srt"
    movie.write_bytes(b"original fixture video")
    source.write_text("7\n00:00:01,001 --> 00:00:02,002\nHello.\n\n12\n00:00:03,003 --> 00:00:04,004\nGoodbye.\n")
    prices = tmp_path/"prices.json"
    prices.write_text(json.dumps({"verified_date":"fixture","models":{
        v["model"]:{"input":.1,"input_ceiling":.125,"output":.5} for v in VARIANTS}}))
    monkeypatch.setattr(settings,"openai_api_key","fixture-only")
    calls = []
    class Client:
        base_url = "https://api.openai.com/v1/"
        models = SimpleNamespace(retrieve=lambda model:None)
        def __enter__(self):
            return self
        def __exit__(self,*args):
            pass
        def with_options(self,**kwargs):
            assert kwargs["max_retries"]==0
            self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))
            return self
        def create(self,**params):
            calls.append(params)
            ids = re.findall(r"BEGIN\[(\d+)\]",params["messages"][1]["content"])
            ids = list(dict.fromkeys(ids))
            usage = SimpleNamespace(prompt_tokens=10,completion_tokens=20,total_tokens=30,
                model_dump=lambda:{"prompt_tokens_details":{"cached_tokens":0,"cache_write_tokens":0},
                                  "completion_tokens_details":{"reasoning_tokens":5}})
            return SimpleNamespace(usage=usage,model=params["model"],
                choices=[SimpleNamespace(finish_reason="stop",message=SimpleNamespace(content="\n\n".join(
                    f"BEGIN[{i}]\nسلام دنیا\nEND[{i}]" for i in ids)))])
    monkeypatch.setattr(translator,"get_openai_client",lambda:Client())
    return movie,source,prices,calls


def test_full_comparison_preserves_cues_and_resumes_without_paid_repetition(tmp_path,monkeypatch):
    movie,source,prices,calls = setup(tmp_path,monkeypatch)
    original = source.read_bytes()
    plan = run(movie,source,prices,5,False)
    assert not calls and plan["cue_count"]==2
    result = run(movie,source,prices,5,True)
    assert len(calls)==5 and all(o["status"]=="done" for o in result["outcomes"].values())
    assert source.read_bytes()==original and movie.read_bytes()==b"original fixture video"
    assert not movie.with_suffix(".fa.srt").exists()
    for variant in VARIANTS:
        output = movie.with_name(movie.stem+"."+variant["id"]+".fa.srt")
        assert validate_output(read_srt(source),read_srt(output))["exact_alignment"]
    result = run(movie,source,prices,5,True)
    assert len(calls)==5
    assert all(o["status"]=="preserved_existing" for o in result["outcomes"].values())
    assert result["models"]["gpt-6-luna-medium"]["reasoning_tokens"]==5


def test_budget_reserves_unfinished_variants_and_never_refunds(tmp_path):
    plan = {"budget_usd":.1}
    ledger = Ledger(tmp_path/"cost.sqlite",plan,[("a",1,40_000_000),("b",1,40_000_000)])
    ledger.reserve("a",1,40_000_000,"first")
    # A repeat cannot consume the reserved allowance for the second variant.
    with pytest.raises(RuntimeError,match="ceiling"):
        Ledger(ledger.path,plan,[]).reserve("a",1,30_000_000,"retry")
    ledger.reserve("b",1,40_000_000,"second")
    with pytest.raises(ValueError,match="differs"):
        Ledger(ledger.path,{"budget_usd":1},[])


def test_existing_output_is_never_overwritten_even_if_invalid(tmp_path,monkeypatch):
    movie,source,prices,calls = setup(tmp_path,monkeypatch)
    output = movie.with_name(movie.stem+".gpt-4o-mini.fa.srt")
    output.write_bytes(b"do not overwrite")
    with pytest.raises(RuntimeError,match="Invalid SRT"):
        run(movie,source,prices,5,True)
    assert output.read_bytes()==b"do not overwrite" and not calls


def test_medium_is_bounded_without_unsupported_temperature():
    params = request_parameters(VARIANTS[2],"dialogue")
    assert params["reasoning_effort"]=="medium"
    assert params["max_completion_tokens"]==32768
    assert "temperature" not in params


def test_unfinished_model_resumes_from_cached_batches(tmp_path,monkeypatch):
    import pysrt
    from app.services.subtitle_io import write_srt
    movie,source,prices,calls = setup(tmp_path,monkeypatch)
    cues = pysrt.SubRipFile([pysrt.SubRipItem(index=i,
        start=pysrt.SubRipTime(milliseconds=i*1000),
        end=pysrt.SubRipTime(milliseconds=i*1000+500),text="Hello.") for i in range(1,42)])
    write_srt(cues,source,add_credit=False)
    factory = translator.get_openai_client
    def flaky():
        c = factory()
        original = c.create
        def create(**params):
            if len(calls)==1:
                calls.append(params)
                raise RuntimeError("simulated ambiguous connection failure")
            return original(**params)
        c.create = create
        return c
    monkeypatch.setattr(translator,"get_openai_client",flaky)
    first = run(movie,source,prices,5,True)
    assert first["outcomes"]["gpt-4o-mini"]["status"]=="failed"
    assert len(calls)==10
    second = run(movie,source,prices,5,True)
    assert second["outcomes"]["gpt-4o-mini"]["status"]=="done"
    assert len(calls)==11  # One unfinished batch, without resending its completed first batch.
    assert second["models"]["gpt-4o-mini"]["unknown_usage_requests"]==1
