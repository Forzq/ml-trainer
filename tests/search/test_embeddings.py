from unittest.mock import Mock, patch
from app.core.config import Settings
from app.search.embeddings import Embeddings


def settings_at(path):
    return Settings(data_dir=path, openrouter_key="", embedding_model="", qdrant_url="", qdrant_key="")


def test_embedding_is_stable_and_remote_vectors_keep_input_order(tmp_path):
    assert Embeddings._hash("Переобучение") == Embeddings._hash("переобучение")
    settings = settings_at(tmp_path)
    settings.openrouter_key = "test"
    settings.embedding_model = "test-model"
    response = Mock()
    response.json.return_value = {"data": [{"index": 1, "embedding": [0, 1]}, {"index": 0, "embedding": [1, 0]}]}
    with patch("app.search.embeddings.httpx.Client") as client:
        client.return_value.__enter__.return_value.post.return_value = response
        assert Embeddings(settings).encode(["first", "second"]) == [[1, 0], [0, 1]]

def test_embedding_batches_preserve_order_across_requests(tmp_path):
    settings = settings_at(tmp_path)
    settings.openrouter_key = "test"
    settings.embedding_model = "test-model"
    embedding = Embeddings(settings)
    embedding.BATCH_SIZE = 2
    responses = [Mock(), Mock()]
    responses[0].json.return_value = {"data": [{"index": 1, "embedding": [0, 1]}, {"index": 0, "embedding": [1, 0]}]}
    responses[1].json.return_value = {"data": [{"index": 0, "embedding": [0.5, 0.5]}]}
    with patch("app.search.embeddings.httpx.Client") as client:
        post = client.return_value.__enter__.return_value.post
        post.side_effect = responses
        assert embedding.encode(["first", "second", "third"]) == [[1, 0], [0, 1], [0.5, 0.5]]
        assert [call.kwargs["json"]["input"] for call in post.call_args_list] == [["first", "second"], ["third"]]
