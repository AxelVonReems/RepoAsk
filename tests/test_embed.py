"""Tests against the real model. The first run downloads it (~67 MB) into .cache/fastembed."""

import numpy as np
import pytest

from rag.indexing.embed import Embedder, FastEmbedEmbedder


@pytest.fixture(scope="module")
def embedder() -> Embedder:
    # Loading the model takes a few seconds, so all tests in this file share one instance
    return FastEmbedEmbedder()


def test_document_vectors_are_normalized_float32(embedder: Embedder):
    vectors = embedder.embed_documents(["Ollama runs models locally.", "A CSS framework."])

    assert vectors.shape == (2, embedder.dim)
    assert vectors.dtype == np.float32
    assert np.allclose(np.linalg.norm(vectors, axis=1), 1.0, atol=1e-3)


def test_query_vector_is_normalized(embedder: Embedder):
    vector = embedder.embed_query("how do I run LLMs locally")

    assert vector.shape == (embedder.dim,)
    assert np.isclose(np.linalg.norm(vector), 1.0, atol=1e-3)


def test_no_documents_gives_empty_matrix(embedder: Embedder):
    assert embedder.embed_documents([]).shape == (0, embedder.dim)


def test_query_is_closer_to_the_relevant_document(embedder: Embedder):
    docs = embedder.embed_documents(
        [
            "ollama/ollama — Get up and running with large language models on your own machine.",
            "twbs/bootstrap — The most popular HTML, CSS, and JavaScript framework for websites.",
        ]
    )
    query = embedder.embed_query("tool to run an LLM on my laptop")

    scores = docs @ query  # cosine similarity, since all vectors are normalized
    assert scores[0] > scores[1]


def test_query_prefix_changes_the_query_vector(embedder: Embedder):
    text = "run LLMs locally"
    as_query = embedder.embed_query(text)
    as_document = embedder.embed_documents([text])[0]

    assert not np.allclose(as_query, as_document), "BGE query instruction should be applied"


def test_count_tokens_has_no_special_tokens_and_no_truncation(embedder: Embedder):
    assert embedder.count_tokens("hello") == 1
    assert embedder.count_tokens("word " * 2000) > 512


def test_long_input_is_still_embedded(embedder: Embedder):
    # Regression: counting must not disable the model's own truncation at 512 tokens
    embedder.count_tokens("word " * 2000)

    vector = embedder.embed_documents(["word " * 2000])

    assert vector.shape == (1, embedder.dim)
