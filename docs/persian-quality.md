# Repeatable Iranian Persian subtitle evaluation

Fixtures: benchmarks/persian_dialogue.json (12 original scenes, 36 cues).
Topics include idioms, humor, slang, sarcasm, emotion, pronouns, threats,
politeness, relationships, profanity and wordplay. Persian hints are review
guidance, not mandatory exact-match translations.

Compare identical source cues/prompt/style across four models, with and
without surrounding source dialogue. Twelve scenes × two context variants ×
four models = 96 planned requests. Only the middle cue is a translation target; neighbors are reference-only.
Without context the model cannot see those neighbors, so this is a true
context ablation. Reviewers see the full source scene for both variants.
Exact target IDs/timestamps are exported as SRTs (12 target cues per variant).

| Model | Standard input USD / 1M | Standard output USD / 1M | API metadata check |
| --- | --- | --- | --- |
| gpt-4o-mini | 0.15 | 0.60 | Available; existing configured baseline |
| gpt-5.4-mini | 0.75 | 4.50 | Available |
| gpt-5.6-terra | 2.00 | 12.00 | Available |
| gpt-6-luna | 0.10 | 0.50 | Available; additional candidate |

Verified 2026-10-14 through official model pages and non-inference models.retrieve
requests using the existing key. Chat Completions is documented for all four.
Reasoning candidates use reasoning_effort=none and omit temperature; the baseline
uses temperature=0.1. These inference parameter combinations are documented,
not verified with paid calls. Account metadata access does not prove successful
inference or equal translation quality. No model was changed in the app.

The official GPT-4o mini page is marked deprecated; retain it as the requested
baseline and recheck availability/deprecation dates before a paid comparison.
Sources:
https://developers.openai.com/api/docs/models/gpt-4o-mini
https://developers.openai.com/api/docs/models/gpt-5.4-mini
https://developers.openai.com/api/docs/models/gpt-5.6-terra
https://developers.openai.com/api/docs/models/gpt-6-luna

## Current artifacts and preparation

dev/runtime/pilot-benchmark-plan contains prompts and manifest.
dev/runtime/pilot-benchmark-mock contains deterministic mock outputs, scorecard,
review-key and manifest. Regenerate after code/data changes before evaluation.
Mock outputs prove alignment/export mechanics, not translation quality.

Offline preparation command (no provider key or network):

~~~sh
docker run --rm --network none --memory 256m --cpus 0.5 --user 1000:1000 \
  -e OPENAI_API_KEY= -v "$PWD:/workspace:ro" -v "$PWD/dev/runtime:/results" \
  --workdir /workspace --entrypoint python ust-dev-backend:1.8.2-5568f9e \
  scripts/persian_benchmark.py --mode prepare --output /results/pilot-benchmark-plan
~~~

Replace prepare with mock and benchmark-plan with benchmark-mock to verify
96 aligned outputs offline. Source and output SRTs preserve exact cue numbers
and timing, without watermark cues. Manifest contains fixture hash, model list,
context variants, price verification date, output cap and request plan.
Blind scorecard has fixed shuffled review IDs; give reviewers ONLY the reviewer/ directory. The mapping, models, costs and
context identities stay outside it until scoring is complete. Shuffle seed is
42. Hashes and request parameters are recorded; model outputs themselves are
not guaranteed deterministic across repeated API calls.

## Paid evaluation — not authorized or run

The runner defaults to prepare. Live mode requires BOTH --allow-paid and a
positive finite --budget-usd. It rejects missing approval flags, NaN/zero budget,
unknown unpriced models and a budget below the conservative request ceiling
before making any requests.

The full current plan has a conservative maximum of USD 1.1463 (proposed approval ceiling USD 1.20) using UTF-8
bytes plus input overhead and a 2048 completion-token ceiling per call. This is
an upper bound under the recorded standard prices, including potential
cache writes (Luna 0.125 and Terra 2.5 input USD/million), not an expected charge or
a guarantee if provider prices change. Refresh pricing before approval.
SDK retries are disabled; reasoning tokens count within the completion limit.
Partial completed results are checkpointed; after a failure review artifacts
rather than blindly rerunning the whole benchmark.

After separately approved budget/model selection, live runs may use a disposable
container with --env-file dev/.env and outbound network. Never pass the key as
a CLI argument or copy it into benchmark artifacts. Do not change the production
provider/model or enable automation just to run the benchmark.

## Scoring and acceptance

Use at least one fluent Iranian Persian reviewer, preferably two independently.
Score 0–5 for naturalness, semantic fidelity, tone/humor, context consistency,
subtitle readability, character voice and profanity register (N/A where absent).
Predeclare the main metric as mean naturalness and meaning, each weighted 50%;
tone, voice, profanity, context and readability are secondary diagnostics.
Any semantic inversion, invented fact or structural failure fails a scene even
with a high mean. Apply selection acceptance to the surrounding_context variant; report the
no_context ablation separately. A candidate must have zero structural failures and no critical
meaning/register failures, mean naturalness/meaning at least 4/5, and no
systematic voice flattening or profanity censorship. Resolve reviewer disputes
before unblinding. No live provider or model judge is used for scoring. Note lost negation, invented facts, literal idioms,
overformal wording, inconsistent pronouns, censorship/intensification and
unnecessary explanations. Do not use exact-string matching against hints.

Reject any output with missing/extra/duplicate/reordered cue IDs, changed timing,
blank dialogue, unsupported language or invented subtitle cues. These structural
checks precede subjective scoring. Compare blinded per-scene averages and
failure counts; unblind models only afterward. Add measured usage/cost/latency
from an approved run before choosing a model. The runner records usage, conservative usage-valued cost and per-request
latency. Invoice charges may be lower because of cached-token discounts.

The app now stops surrounding context at gaps greater than 15 seconds and
bounds neighboring text to 500 characters per cue, two cues on each side.
Context is source-only reference data; it never changes output IDs or timestamps.
Regression tests verify scene-gap behavior and manual pipeline compatibility.

No quality winner is claimed: paid outputs and human evaluation remain pending.

The first real-movie sequence, bounded request ledger and Jellyfin checks are
in [first-real-pilot.md](first-real-pilot.md). No paid benchmark or real pilot
is authorized yet; the current 96 outputs are mocked mechanics checks only.
