"""Measures retrieval and answer quality on eval/questions.yaml against the real index.

    uv run python eval/run_eval.py          # retrieval only: no LLM calls, a few seconds
    uv run python eval/run_eval.py --llm    # also asks Gemini, one request per question

Writes eval/results.md. Metrics, over the questions that have expected repos:
- hit@k: share where an expected repo is among the k sources /ask would use
- MRR: mean of 1/rank of the best expected repo in a deep, one-chunk-per-repo ranking
  (top 100, else 0). Moves when tuning improves ranks that are still outside the top k.
- citation rate (--llm): share of answers that name an expected repo
Out-of-scope questions (expected: []) pass when the answer says the READMEs don't cover it.
"""

import argparse
import re
import statistics
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import yaml

from rag import config
from rag.indexing.embed import FastEmbedEmbedder
from rag.llm.answer import Answerer
from rag.llm.client import GeminiClient
from rag.retrieval.search import Index, Retriever

EVAL_DIR = Path(__file__).resolve().parent
DEEP_K = 100

# How the system prompt tells the model to decline; matches NO_MATCHES as well
REFUSAL = re.compile(
    r"(do(es)? not|don't|doesn't) (cover|contain|mention|include)|could(n't| not) find"
    r"|not (covered|mentioned)|no (relevant|information)|(don't|do not) know",
    re.IGNORECASE,
)


@dataclass
class Result:
    question: str
    expected: list[str]
    sources: list[str]  # repo names of the retrieved chunks, in order, deduplicated
    top_score: float
    rank: int | None = None  # 1-based repo rank of the best expected repo in the deep ranking
    answer: str | None = None
    seconds: float | None = None
    llm_error: str | None = None
    notes: list[str] = field(default_factory=list)

    @property
    def in_scope(self) -> bool:
        return bool(self.expected)

    @property
    def hit(self) -> bool:
        return any(repo in self.sources for repo in self.expected)

    @property
    def cited(self) -> bool:
        text = (self.answer or "").lower()
        return any(repo.lower() in text for repo in self.expected)

    @property
    def refused(self) -> bool:
        return bool(self.answer and REFUSAL.search(self.answer))


def evaluate(
    questions: list[dict], retriever: Retriever, answerer: Answerer | None
) -> list[Result]:
    results = []
    for item in questions:
        question, expected = item["question"], item["expected"]
        vector = retriever.embedder.embed_query(question)
        hits = retriever.index.search(vector)  # same settings as /ask
        # No score threshold here: the rank of a repo matters even when it scores too low to be used
        deep_hits = retriever.index.search(vector, k=DEEP_K, max_per_repo=1, min_score=-1.0)
        deep = [h.full_name for h in deep_hits]
        ranks = [deep.index(repo) + 1 for repo in expected if repo in deep]
        result = Result(
            question,
            expected,
            sources=list(dict.fromkeys(h.full_name for h in hits)),
            top_score=deep_hits[0].score,  # also when the threshold left no sources
            rank=min(ranks) if ranks else None,
        )
        if answerer:
            started = time.perf_counter()
            try:
                result.answer = answerer.ask(question).text
            except Exception as error:  # one failed request must not lose the whole run
                result.llm_error = f"{type(error).__name__}: {error}"
            result.seconds = round(time.perf_counter() - started, 1)
        results.append(result)
        mark = ("✓" if result.hit else "✗") if result.in_scope else "-"
        print(f"  {mark} {question}")
    return results


def summary(results: list[Result], with_llm: bool) -> list[tuple[str, str]]:
    scoped = [r for r in results if r.in_scope]
    out_of_scope = [r for r in results if not r.in_scope]
    k = config.SEARCH_TOP_K
    mrr = statistics.mean(1 / r.rank if r.rank else 0 for r in scoped)
    rows = [
        (f"Retrieval hit@{k}", f"{sum(r.hit for r in scoped)}/{len(scoped)}"),
        (f"MRR (repo rank, top {DEEP_K})", f"{mrr:.2f}"),
    ]
    if with_llm:
        latencies = [r.seconds for r in results if r.seconds is not None and not r.llm_error]
        rows += [
            ("Answer citation rate", f"{sum(r.cited for r in scoped)}/{len(scoped)}"),
            (
                "Out-of-scope declined",
                f"{sum(r.refused for r in out_of_scope)}/{len(out_of_scope)}",
            ),
            ("LLM errors", str(sum(bool(r.llm_error) for r in results))),
            ("Median answer time", f"{statistics.median(latencies):.1f}s" if latencies else "-"),
        ]
    return rows


def render(results: list[Result], retriever: Retriever, model: str | None) -> str:
    index = retriever.index
    settings = [
        ("Run", datetime.now(UTC).isoformat(timespec="minutes")),
        ("Index", f"{index.repo_count} repos, {index.chunk_count} chunks, built {index.built_at}"),
        ("Embedding model", index.model or "-"),
        ("Query prefix", "on" if config.EMBED_QUERY_PREFIX else "off"),
        (
            "Search",
            f"k={config.SEARCH_TOP_K}, max {config.SEARCH_MAX_PER_REPO}/repo, "
            f"min score {config.SEARCH_MIN_SCORE}",
        ),
        ("LLM", model or "not run (retrieval only)"),
    ]
    lines = ["# Eval results", "", "Generated by `eval/run_eval.py`. Do not edit by hand.", ""]
    lines += _table(["Setting", "Value"], settings)
    lines += ["", "## Summary", ""]
    lines += _table(["Metric", "Value"], summary(results, model is not None))
    lines += ["", "## Questions", ""]

    header = ["Question", "Expected", f"Hit@{config.SEARCH_TOP_K}", "Rank", "Top score", "Sources"]
    if model:
        header += ["Cited / declined", "Time"]
    rows = []
    for r in results:
        row = [
            r.question,
            ", ".join(r.expected) or "*(out of scope)*",
            ("✓" if r.hit else "✗") if r.in_scope else "-",
            str(r.rank or f">{DEEP_K}") if r.in_scope else "-",
            f"{r.top_score:.3f}",
            ", ".join(r.sources),
        ]
        if model:
            passed = r.cited if r.in_scope else r.refused
            row += ["error" if r.llm_error else ("✓" if passed else "✗"), f"{r.seconds}s"]
        rows.append(row)
    lines += _table(header, rows)

    if model:
        lines += ["", "## Answers", ""]
        for r in results:
            text = r.llm_error or (r.answer or "").strip()
            lines += [f"**{r.question}**", "", *[f"> {line}" for line in text.splitlines()], ""]
    return "\n".join(lines).rstrip() + "\n"


def _table(header: list[str], rows: list) -> list[str]:
    def cells(values) -> str:
        return "| " + " | ".join(str(v).replace("|", "\\|") for v in values) + " |"

    return [cells(header), cells(["---"] * len(header)), *(cells(row) for row in rows)]


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate retrieval (and answers) on the eval set")
    parser.add_argument("--llm", action="store_true", help="also ask Gemini (1 request/question)")
    parser.add_argument("--questions", type=Path, default=EVAL_DIR / "questions.yaml")
    parser.add_argument("--out", type=Path, default=EVAL_DIR / "results.md")
    args = parser.parse_args()

    questions = yaml.safe_load(args.questions.read_text())["questions"]
    retriever = Retriever(Index.load(config.INDEX_DB_PATH), FastEmbedEmbedder())
    llm = GeminiClient() if args.llm else None
    answerer = Answerer(retriever, llm) if llm else None

    results = evaluate(questions, retriever, answerer)
    args.out.write_text(render(results, retriever, llm.model_name if llm else None))

    print()
    for metric, value in summary(results, llm is not None):
        print(f"{metric}: {value}")
    print(f"\nWrote {args.out}")


if __name__ == "__main__":
    main()
