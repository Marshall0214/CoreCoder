import json
import math

import pytest

from corecoder.tools.search_code import SearchCodeTool
from docs.experiments.vector_retrieval_v1 import OllamaEmbeddings, VectorIndex, VectorSearchCodeTool, unit


class Provider:
    model_digest = "fake-digest"

    def __init__(self):
        self.inputs = []

    def embed(self, texts):
        self.inputs.extend(texts)
        return [unit([1, 0] if "alpha" in t else [0, 1]) for t in texts]


@pytest.mark.parametrize("vector", [[], [0, 0], [math.nan], [math.inf], [True], ["1"]])
def test_invalid_vectors_fail(vector):
    with pytest.raises(ValueError):
        unit(vector)


def test_index_refresh_invalidates_and_excludes_private_files(tmp_path):
    (tmp_path / "a.py").write_text("alpha = 1\n", encoding="utf-8")
    (tmp_path / "b.py").write_text("beta = 1\n", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "secret.py").write_text("hidden_answer", encoding="utf-8")
    provider = Provider()
    index = VectorIndex(tmp_path, provider, ["a.py"])
    first = index.refresh()["index_hash"]
    assert len(provider.inputs) == 1
    index.refresh()
    assert len(provider.inputs) == 1
    assert index.rank("alpha")[0][1].path == "a.py"
    (tmp_path / "a.py").write_text("beta = 2\n", encoding="utf-8")
    assert index.refresh()["index_hash"] != first
    assert all("hidden_answer" not in t for t in provider.inputs)


def test_hybrid_deterministic_and_tool_preserves_interface(tmp_path):
    (tmp_path / "a.py").write_text("alpha = 1\n", encoding="utf-8")
    (tmp_path / "b.py").write_text("beta = 1\n", encoding="utf-8")
    events = []
    tool = VectorSearchCodeTool(tmp_path, Provider(), strategy="hybrid",
                                emit=lambda event, **fields: events.append(fields))
    assert tool.schema() == SearchCodeTool(tmp_path).schema()
    result = json.loads(tool.execute("alpha", 1))
    assert result["results"][0]["path"] == "a.py"
    assert result["results"][0]["content"] == "alpha = 1"
    assert events[0]["backend"] == "hybrid"
    assert tool.execute("alpha", 1) == tool.execute("alpha", 1)


class MockOllama(OllamaEmbeddings):
    def request(self, path, body=None):
        if path == "/api/tags":
            return {"models": [{"name": "test", "digest": getattr(self, "digest", "v1")}]}
        assert body["truncate"] is False
        self.body = body
        return getattr(self, "response", {"embeddings": [[3, 4] for _ in body["input"]], "prompt_eval_count": 2})


def test_cache_dimension_and_identity_guard():
    client = MockOllama(model="test")
    assert client.embed(["a", "a"]) == [(0.6, 0.8)] * 2
    assert client.usage["inputs"] == 1
    client.embed(["a"])
    assert client.usage["calls"] == 1
    client.response = {"embeddings": [[1, 1, 1]]}
    with pytest.raises(ValueError, match="dimension"):
        client.embed(["b"])
    client.digest = "v2"
    with pytest.raises(ValueError, match="digest"):
        client.embed(["a"])


def test_bad_response_count_and_remote_server_fail():
    client = MockOllama(model="test")
    client.response = {"embeddings": []}
    with pytest.raises(ValueError, match="count"):
        client.embed(["a"])
    with pytest.raises(ValueError, match="local"):
        OllamaEmbeddings(base_url="https://example.com")


def test_labels_only_open_after_observations_are_persisted(tmp_path, monkeypatch):
    from docs.experiments import vector_retrieval_eval_v1 as evaluator
    from evals.schema import Task

    root = tmp_path / "task"
    (root / "workspace").mkdir(parents=True)
    (root / "workspace" / "a.py").write_text("alpha = 1\n", encoding="utf-8")
    task = Task("toy", "toy", "alpha", ("a.py",), root)
    provider = Provider()
    provider.model = "fake"
    provider.dimension = 2
    provider.usage = {"calls": 0}
    provider.verify_identity = lambda: None
    output = tmp_path / "report"
    monkeypatch.setattr(evaluator, "load_suite", lambda _: [task])

    def labels(_):
        saved = json.loads((output / "observations.json").read_text(encoding="utf-8"))
        assert set(saved[0]["rankings"]) == {"bm25", "dense", "hybrid"}
        assert "targets" not in saved[0]
        assert all("secret_label" not in text for text in provider.inputs)
        return [{"file": "a.py", "content": "secret_label"}]

    monkeypatch.setattr(evaluator, "reference_edits", labels)
    report = evaluator.evaluate([root], output, provider)
    assert all(report["mean_file_recall"][name]["1"] == 1 for name in ("bm25", "dense", "hybrid"))
