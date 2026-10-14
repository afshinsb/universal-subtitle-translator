import json

import pytest
from scripts.persian_benchmark import run, scenes, payload
from app.services.subtitle_io import read_srt


def test_benchmark_is_original_contextual_and_alignment_safe(tmp_path):
    assert len(scenes()) == 12
    assert "REFERENCE CONTEXT" in payload(scenes()[0], True)
    assert "REFERENCE CONTEXT" not in payload(scenes()[0], False)
    result = run(tmp_path, ["gpt-4o-mini", "gpt-5.4-mini"], "mock")
    assert result["calls_made"] == 0 and result["aligned"] == 48
    assert result["actual_cost_usd"] == 0
    source = read_srt(tmp_path/"source-en/idiom.en.srt")
    translated = read_srt(tmp_path/"gpt-5.4-mini/context/idiom.fa.srt")
    assert [(c.index,c.start.ordinal,c.end.ordinal) for c in source] == [(c.index,c.start.ordinal,c.end.ordinal) for c in translated]
    assert (tmp_path/"blind-review.csv").is_file()
    assert len(json.loads((tmp_path/"review-key.json").read_text())) == 48


@pytest.mark.parametrize("approval,budget",[(False,10),(True,0),(True,float("nan")),(True,0.00001)])
def test_live_benchmark_blocks_unapproved_or_insufficient_budget(tmp_path,approval,budget):
    with pytest.raises(ValueError):
        run(tmp_path,["gpt-5.6-terra"],"live",approval,budget)
    assert not list(tmp_path.iterdir())
