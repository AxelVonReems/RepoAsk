# RepoAsk

Ask questions about the READMEs of the 1,000 most-starred GitHub repositories and get answers
that cite their sources.

**Live demo: [repoask.wonderfulisland-eb2f1426.spaincentral.azurecontainerapps.io](https://repoask.wonderfulisland-eb2f1426.spaincentral.azurecontainerapps.io)**
(the server sleeps when idle; the first request can take ~25 s)

> **Q:** Which fast, GPU-accelerated terminal emulators are there?
>
> **A:** Based on the provided README excerpts, there are two fast, GPU-accelerated
> cross-platform terminal emulators available: alacritty/alacritty [1][4] and
> ghostty-org/ghostty [2]. *(On the page, each [n] links to the README section it came from.)*

A retrieval-augmented generation (RAG) pipeline built as a learning project: TypeScript ingest,
local embeddings, vector search, an LLM that only answers from what it retrieved, an eval set
to measure it, and CI/CD to Azure that costs nothing to run.

## Contents

- [How it works](#how-it-works)
- [Quick start](#quick-start)
- [Full pipeline](#full-pipeline)
- [Configuration](#configuration)
- [Evaluation](#evaluation)
- [Deployment and CI/CD](#deployment-and-cicd)
- [Cost](#cost)
- [Limitations](#limitations)
- [Why Gemini](#why-gemini)
- [How Claude Code was used](#how-claude-code-was-used)

## How it works

```mermaid
flowchart TB
    subgraph actions["GitHub Actions, weekly"]
        A["ingest/ (TypeScript)<br/>GitHub Search API +<br/>README fetch with ETags"] --> B[(worker.db)]
        B --> C["rag/indexing (Python)<br/>clean → chunk → embed<br/>(incremental)"]
        C --> D[(index.db)]
    end
    D -- "release asset<br/>index-latest" --> E["Docker image<br/>model + index baked in"]
    E --> F["Azure Container Apps<br/>FastAPI"]
    U([Browser]) -- "question" --> F
    F -- "top 5 chunks + question" --> G["Gemini"]
    G -- "answer with [n] citations" --> F
```

All heavy work (fetching, chunking, embedding) runs in GitHub Actions. The deployed container
only loads a prebuilt, read-only index and answers questions.

**1. Ingest** ([ingest/](ingest/)), Node 22 + TypeScript. Pulls the top 1,000 repositories by stars
from the GitHub Search API and fetches each README. Every response is validated with Zod.
README requests send the stored ETag, so unchanged READMEs come back as `304 Not Modified`,
which doesn't count against GitHub's rate limit. Results go to SQLite (`worker.db`).

**2. Index** ([rag/indexing/](rag/indexing/)), Python 3.12.
- **Clean:** strips badges, images, HTML wrappers, link URLs, tables of contents and link walls;
  keeps prose, headings, tables and code blocks untouched.
- **Chunk:** splits at Markdown headings into chunks of at most 350 tokens with 50 tokens of
  overlap. Each chunk starts with `repo — description — topics`, so repository metadata is
  searchable too.
- **Embed:** [BAAI/bge-small-en-v1.5](https://huggingface.co/BAAI/bge-small-en-v1.5) through
  fastembed (ONNX, CPU only, no PyTorch). 384-dimensional normalized vectors stored in SQLite
  (`index.db`).
- **Incremental:** a hash of everything that ends up in a repo's chunks decides whether it needs
  re-embedding; the weekly refresh re-embeds only changed READMEs (4 minutes instead of ~25).

**3. Retrieve** ([rag/retrieval/](rag/retrieval/)). The whole index (12,500 chunks × 384 floats)
fits in memory as one NumPy matrix, so search is a single matrix-vector product: no vector
database needed at this size. At most 2 chunks per repo (otherwise a few huge "awesome" lists
fill every slot), and chunks below a similarity of 0.68 are dropped.

**4. Answer** ([rag/llm/](rag/llm/)). The question and the top 5 chunks go to Gemini with a system
prompt: answer only from the excerpts, cite them as `[n]`, say so when they don't cover the
question, and treat excerpts as data, not instructions (README text is written by strangers).
When no chunk passes the threshold, the API declines without calling the LLM at all.

**5. Serve** ([rag/api/](rag/api/)). FastAPI with `POST /ask`, `GET /health` and a one-file demo
page at `/`. LLM rate limits and quota errors map to `503` with `Retry-After`, not a bare `500`.

## Quick start

Runs the API locally with the published index: no GitHub token, no index build.

**Needs:** [uv](https://docs.astral.sh/uv/getting-started/installation/) (installs Python 3.12
itself) and a free [Gemini API key](https://aistudio.google.com/apikey).

```bash
git clone https://github.com/AxelVonReems/RepoAsk.git
cd RepoAsk
uv sync
curl -L -o data/index.db https://github.com/AxelVonReems/RepoAsk/releases/download/index-latest/index.db
cp .env.example .env    # then set GEMINI_API_KEY in .env
uv run uvicorn rag.api.main:app
```

Open <http://127.0.0.1:8000> for the demo page, or <http://127.0.0.1:8000/docs> for the API.
The embedding model (~65 MB) downloads on the first start.

**Or with Docker**, exactly as deployed (after the `curl` step above):

```bash
docker build -t repoask .
docker run --rm -p 8000:8000 --env-file .env repoask
```

**From the command line**, without the server:

```bash
uv run python -m rag.retrieval.search "fuzzy finder for the terminal"   # retrieval only, no LLM
uv run python -m rag.llm.answer "fuzzy finder for the terminal"         # full answer
```

## Full pipeline

To build everything yourself. Also needs Node 22 and a
[fine-grained GitHub token](https://github.com/settings/personal-access-tokens) with read-only
access to public repositories (set `GITHUB_TOKEN` in `.env`).

```bash
cd ingest && npm ci && npm run sync && cd ..    # ~6 min: 1,000 repos + READMEs → data/worker.db
uv run python -m rag.indexing.build_index       # ~25 min on a 4-core laptop CPU → data/index.db
```

`build_index --limit 50` builds a small index in about a minute for trying things out.

**Tests and checks**, the same ones CI runs (no network, no secrets):

```bash
cd ingest && npm run typecheck && npm test && cd ..   # 23 tests
uv run ruff check && uv run ruff format --check
uv run pytest                                         # 98 tests
```

## Configuration

Defaults live in [rag/config.py](rag/config.py) and [ingest/src/config.ts](ingest/src/config.ts);
any of them can be overridden in `.env` or the environment. Secrets come only from there.

| Variable | Default | What it does |
| --- | --- | --- |
| `GEMINI_API_KEY` | (required) | Gemini key; in Azure a Container Apps secret |
| `GITHUB_TOKEN` | (required for ingest) | read-only token for the GitHub API |
| `SOURCE` | `search:stars:>5000` | what to ingest: `search:<query>` or `org:<name>` |
| `GEMINI_MODEL` | `gemini-3.5-flash-lite` | answering model |
| `SEARCH_TOP_K` | `5` | chunks given to the LLM |
| `SEARCH_MAX_PER_REPO` | `2` | chunks per repository |
| `SEARCH_MIN_SCORE` | `0.68` | similarity threshold, calibrated in [eval/TUNING.md](eval/TUNING.md) |
| `CHUNK_MAX_TOKENS` / `CHUNK_OVERLAP_TOKENS` | `350` / `50` | chunk size (changing it rebuilds the index) |
| `INDEX_STALE_DAYS` | `14` | `/health` reports `index_stale` after this |

## Evaluation

[eval/questions.yaml](eval/questions.yaml) holds 10 questions with the repositories a good answer
must include: 7 with one obvious repo, 2 comparative, 1 out of scope.
[eval/run_eval.py](eval/run_eval.py) runs them against the real index.

| Metric | Result |
| --- | --- |
| Retrieval hit@5 (an expected repo among the sources) | 8/9 |
| MRR (rank of the best expected repo, top 100) | 0.78 |
| Answer citation rate (answer names an expected repo) | 8/9 |
| Out-of-scope question declined | 1/1, without an LLM call |
| Median answer time | 0.8 s |

Full per-question results: [eval/results.md](eval/results.md). One tuning round, with every
experiment and why it was kept or rejected (query prefix, k, per-repo cap, BM25 hybrid search,
repository cards, the threshold): [eval/TUNING.md](eval/TUNING.md).

The miss is instructive: *"Which repos help me run large language models locally?"* expects
ollama, which ranks 64th. Its README, description and topics never say "run locally", and no
retrieval trick finds text that isn't there.

CI runs a real-model retrieval test on a 5-README fixture instead (the real index isn't in the
repository). The retrieval-only eval runs in every weekly refresh, and the full eval with Gemini
runs on demand ([eval.yml](.github/workflows/eval.yml)).

## Deployment and CI/CD

| Workflow | Trigger | What it does |
| --- | --- | --- |
| [ci.yml](.github/workflows/ci.yml) | every PR, pushes to `dev` | typecheck, tests, `npm audit`, ruff, pytest. No secrets, no network calls. |
| [deploy.yml](.github/workflows/deploy.yml) | push to `main`, after each refresh | CI → download `index.db` → build image → push to ghcr.io → update the container app → smoke test `/health` |
| [refresh.yml](.github/workflows/refresh.yml) | Mondays + manual | sync → incremental index build → check ≥ 900 repos → retrieval eval → upload to the `index-latest` release → deploy |
| [eval.yml](.github/workflows/eval.yml) | manual | full eval with Gemini; results in the run summary |

- **Image:** `python:3.12-slim`, two-stage build, embedding model and index baked in, runs as a
  non-root user with read-only files. 749 MB on disk, 214 MB compressed.
- **Azure sign-in with OIDC:** GitHub issues a short-lived token per run, and Azure trusts it only
  for this repository's `main` branch. No Azure password or key is stored anywhere. The deploy
  identity is Contributor on the project's resource group only.
- **Image tags** are `<commit>-<run ID>`, never only `latest`; rolling back is
  `az containerapp update --image` with an earlier tag.
- **Index delivery:** the index is a GitHub Release asset, rebuilt weekly. The release also keeps
  `worker.db`, so each refresh starts from the previous ETags and hashes instead of from scratch.

## Cost

Runs at €0. Every paid path is either blocked by design or watched.

| Part | Why it costs nothing |
| --- | --- |
| Azure Container Apps | consumption plan, 0.5 vCPU / 1 GiB, scales to zero when idle, at most 1 replica: inside the monthly free grant. No Log Analytics workspace (log storage is billed). |
| Gemini | API key from a Google Cloud project with no billing account: over-limit requests get `429`, never a bill |
| ghcr.io, GitHub Actions | free for public repositories |
| Embeddings | run locally in the container and in CI, no API |

Safety nets: a €1 budget alert on the subscription and on the resource group.
The price is a cold start of about 25 seconds after ~8 minutes without traffic.

## Limitations

- **Retrieval can't find what a README never says** (see the ollama example above).
- **A weekly snapshot** of the top 1,000 repositories by stars, which skews toward big, older
  projects, awesome lists and English READMEs.
- **Cold start** of ~25 s after the app scales to zero.
- **Free-tier limits:** Gemini allows 500 requests a day; a busy public demo can use them up, and
  `/ask` then answers `503` until the next day.
- **Azure settings are set by hand** with the Azure CLI, not in code. For one app that's fine; more
  would call for infrastructure as code (Bicep or Terraform).
- **Single-turn:** no follow-up questions or chat history.

## Why Gemini

The plan was Azure OpenAI, to keep everything in Azure. A free Azure account has no usable quota
for it, while Gemini's free tier covers this project's traffic, and a key without a billing account
cannot generate a bill. The LLM sits behind a small `LLMClient` interface
([rag/llm/client.py](rag/llm/client.py)), so switching providers means one new class.

## How Claude Code was used

This project was built with [Claude Code](https://claude.com/claude-code) as a pair programmer and
mentor, to learn a stack that was new to me (Python RAG, FastAPI, Docker, GitHub Actions, Azure).
I set the plan and the workflow, Claude Code proposed and explained each step, and I made
important decisions, commits and pull requests. The ingest worker is based on an earlier project
of mine.

**What it did:** most of the code and workflows, the eval runner and tuning experiments, and
step-by-step explanations of the stack (uv, FastAPI, fastembed, GitHub Actions, OIDC, Container
Apps).

**What I did:**
- **Scope and constraints:** €0 running cost as a hard requirement; the demo page as a small bonus
  served from the same container, not a separate frontend.
- **Workflow:** feature branches → `dev` → `main` per phase, a branch ruleset that requires the CI
  checks, and every change merged through a pull request.
- **Cloud setup, by hand:** the Azure resources and the OIDC identity with the Azure CLI, budget
  alerts at subscription and resource-group scope, GitHub variables and secrets, and the
  `index-latest` release.
- **Checks:** tried the demo page locally before committing it and the live app after each deploy,
  and confirmed the billing setup (a Free Trial with a spending limit) before deploying anything.


**What it got wrong**, and how it was caught:
- **OIDC subject format.** It registered the federated credential as `repo:Owner/Repo:ref:…`, but
  GitHub now sends `repo:Owner@<id>/Repo@<id>:ref:…`. The first deploy failed at Azure sign-in, and
  the error message showed the subject actually sent.
- **Image tag collisions.** It tagged images with the run number, which each workflow counts on its
  own, so a refresh and a push deploy could produce the same tag and overwrite an image. Every run
  was green; it was found by checking a successful run's output, and fixed by using the run ID.
- **A deploy setting that would have broken sign-in.** Adding `environment: production` to the
  deploy job changes the OIDC subject, so Azure would have refused the login. Caught while
  writing the workflow, before it ran.
- **Smaller ones caught by tests:** a snippet function that dropped a whole word at an exact word
  boundary, model cache files the container's non-root user couldn't read, and an eval script that
  crashed on a relative output path.

Every one of these was caught by a failing run, a test, or checking a result, not by reading the
code: verifying behavior was the safety net.
