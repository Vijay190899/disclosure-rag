def test_e5_models_carry_their_asymmetric_prefixes() -> None:
    """Omitting them is a silent misuse that reads as the model being bad."""
    from disclosure_rag.retrieval.dense import DenseRetriever

    e5 = DenseRetriever("intfloat/multilingual-e5-large")
    assert (e5.query_prefix, e5.passage_prefix) == ("query: ", "passage: ")


def test_models_without_prefixes_get_none() -> None:
    from disclosure_rag.retrieval.dense import DenseRetriever

    mini = DenseRetriever("sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2")
    assert (mini.query_prefix, mini.passage_prefix) == ("", "")
