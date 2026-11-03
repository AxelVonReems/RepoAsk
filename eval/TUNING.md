# Tuning record

One tuning round, measured with `eval/run_eval.py` on the full index (1,000 repos,
12,544 chunks). Each experiment changed one setting from the baseline. Retrieval runs
make no LLM calls, so they are free to repeat.

## Baseline (before)

`k=5`, max 2 chunks per repo, BGE query prefix on, no score threshold.

| Metric | Value |
| --- | --- |
| Retrieval hit@5 | 8/9 |
| MRR (repo rank, top 100) | 0.78 |
| Answer citation rate | 8/9 |
| Out-of-scope declined | 1/1, by the LLM, after a Gemini request |

The only miss: "Which repos help me run large language models locally?" expects
ollama/ollama or ggml-org/llama.cpp; the best of them ranks 64th.

## Experiments

| Change | hit@5 | MRR | LLM question: best expected rank | Verdict |
| --- | --- | --- | --- | --- |
| Baseline | 8/9 | 0.78 | 64 | |
| Query prefix off | 8/9 | 0.78 | 57 | No measurable effect; keep BGE's recommended prefix |
| Max 1 chunk per repo | 8/9 | 0.78 | 64 | No effect on hits; 2 gives the LLM more context per repo |
| k = 3 | 8/9 (hit@3) | 0.78 | 64 | Same hits with a shorter prompt, but less context for comparative questions |
| k = 8 | 8/9 (hit@8) | 0.78 | 64 | No gain; keep 5 |
| Hybrid: BM25 + vector (reciprocal rank fusion, BM25 weight 0.3 / 0.5 / 1.0) | 8/9 | 0.76 | 65 / 71 / 90 | Worse: ollama's README lacks the query's words too |
| One extra "repo card" chunk per repo (name, description, topics) | 8/9 | 0.78 | 65 | No effect |
| **Score threshold 0.68** | **8/9** | **0.78** | 64 | **Adopted** |

### Why 0.68

Top scores of 25 extra questions not in the eval set:

- 10 off-topic (weather, pizza, flights, world cup, ...): 0.551 to 0.652 (sourdough bread)
- 15 real (password manager, dotfiles, video editor, ...): 0.709 to 0.871
- Short queries ("vim", "LLM", "game engine"): 0.733 to 0.828, all 5 sources kept

0.68 sits in the gap. Below it, `/ask` answers "could not find anything relevant" without
calling Gemini: no quota spent, no chance of an answer made up from unrelated excerpts.
The threshold is calibrated for this corpus and model; rebuilding with another model means
measuring again. Short fixture READMEs score lower, so the CI tests set it to -1.

## After

| Metric | Before | After |
| --- | --- | --- |
| Retrieval hit@5 | 8/9 | 8/9 |
| MRR | 0.78 | 0.78 |
| Answer citation rate | 8/9 | 8/9 |
| Out-of-scope declined | 1/1 (Gemini request) | 1/1 (no Gemini request) |

Full results: [results.md](results.md).

## Known limitation

Retrieval cannot find what a repository never says. ollama's README is mostly model and
integration lists; its description lists model names; its topics are model names. None
mention running models locally, so no vector, keyword or metadata variant tried here ranks
it for that question. Possible next steps, not done: an LLM rewriting the question into
likely README wording before search (one extra request per question), or a hand-written
alias list for well-known repositories.

Chunk size was not changed: every experiment points at missing text, not at chunk
boundaries, and a rebuild takes about 25 minutes on this machine.
