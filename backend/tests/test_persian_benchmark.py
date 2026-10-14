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


def test_luna_is_blinded_and_uses_current_context_contract(tmp_path):
    result = run(tmp_path, ["gpt-6-luna"], "mock")
    assert result["aligned"] == 24
    assert result["request_parameters"]["gpt-6-luna"]["reasoning_effort"] == "none"
    assert len(list((tmp_path/"reviewer").glob("*.fa.srt"))) == 24
    assert not (tmp_path/"reviewer/review-key.json").exists()
    assert "gpt-6-luna" not in (tmp_path/"reviewer/blind-review.csv").read_text()


def test_context_ablation_adds_information_not_already_in_target_batch():
    scene = scenes()[0]
    without = payload(scene, False)
    with_context = payload(scene, True)
    assert "You look nervous." not in without
    assert "You look nervous." in with_context
    assert "BEGIN[12]" in without and "BEGIN[7]" not in without
