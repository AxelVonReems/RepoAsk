"""Question in, answer with sources out: the whole RAG pipeline in one call.

    uv run python -m rag.llm.answer "how do I run LLMs locally"

Each run makes one Gemini request (free tier: 500 a day).
"""

import argparse
from dataclasses import dataclass

from rag import config
from rag.indexing.embed import FastEmbedEmbedder
from rag.llm.client import GeminiClient, LLMClient
from rag.llm.prompt import SYSTEM_PROMPT, build_prompt
from rag.retrieval.search import Hit, Index, Retriever

NO_MATCHES = "I could not find anything relevant to that question in the indexed READMEs."


@dataclass(frozen=True)
class Answer:
    text: str
    sources: list[Hit]  # in prompt order, so sources[n - 1] is the excerpt cited as [n]


class Answerer:
    def __init__(self, retriever: Retriever, llm: LLMClient) -> None:
        self.retriever = retriever
        self.llm = llm

    def ask(self, question: str, k: int = config.SEARCH_TOP_K) -> Answer:
        hits = self.retriever.retrieve(question, k=k)
        # Nothing passed the score threshold: answering would only invite a made-up reply,
        # and skipping the call saves quota
        if not hits:
            return Answer(NO_MATCHES, [])
        return Answer(self.llm.generate(SYSTEM_PROMPT, build_prompt(question, hits)), hits)


def main() -> None:
    parser = argparse.ArgumentParser(description="Ask a question about the indexed READMEs")
    parser.add_argument("question")
    args = parser.parse_args()

    retriever = Retriever(Index.load(config.INDEX_DB_PATH), FastEmbedEmbedder())
    answer = Answerer(retriever, GeminiClient()).ask(args.question)

    print(answer.text.strip())
    if answer.sources:
        print("\nSources:")
        for n, hit in enumerate(answer.sources, 1):
            print(f"  [{n}] {hit.full_name} ({hit.score:.3f})  {hit.url}")


if __name__ == "__main__":
    main()
