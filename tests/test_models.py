import hashlib
from collections.abc import Callable

import httpx
import pytest

from jarvis import models, paths
from jarvis.models import ModelIntegrityError, ModelSpec, UnknownModelError

PAYLOAD = b"synthetic model bytes" * 100
SPEC = ModelSpec(
    name="fake",
    url="https://models.example/fake.bin",
    sha256=hashlib.sha256(PAYLOAD).hexdigest(),
    filename="fake.bin",
)


@pytest.fixture
def served(monkeypatch: pytest.MonkeyPatch) -> Callable[[bytes], list[str]]:
    """Register SPEC and serve `body` for it through a mock transport; returns the request log."""
    monkeypatch.setitem(models.REGISTRY, "fake", SPEC)
    requests: list[str] = []

    def serve(body: bytes) -> list[str]:
        def handler(request: httpx.Request) -> httpx.Response:
            requests.append(str(request.url))
            return httpx.Response(200, content=body)

        monkeypatch.setattr(
            models, "_open_client", lambda: httpx.Client(transport=httpx.MockTransport(handler))
        )
        return requests

    return serve


def test_should_download_verify_and_place_file_when_hash_matches(
    served: Callable[[bytes], list[str]],
) -> None:
    served(PAYLOAD)
    path = models.ensure("fake")
    assert path.read_bytes() == PAYLOAD
    assert path.parent == paths.cache_dir() / "models"
    assert [p.name for p in path.parent.iterdir()] == ["fake.bin"]


def test_should_raise_and_leave_no_files_when_hash_mismatches(
    served: Callable[[bytes], list[str]],
) -> None:
    served(b"tampered")
    with pytest.raises(ModelIntegrityError) as caught:
        models.ensure("fake")
    assert SPEC.sha256 in str(caught.value)
    assert hashlib.sha256(b"tampered").hexdigest() in str(caught.value)
    assert list((paths.cache_dir() / "models").iterdir()) == []


def test_should_not_download_again_when_cached_file_is_valid(
    served: Callable[[bytes], list[str]],
) -> None:
    requests = served(PAYLOAD)
    models.ensure("fake")
    models.ensure("fake")
    assert len(requests) == 1


def test_should_replace_cached_file_when_its_hash_is_wrong(
    served: Callable[[bytes], list[str]],
) -> None:
    requests = served(PAYLOAD)
    target = models.model_path(SPEC)
    target.parent.mkdir(parents=True)
    target.write_bytes(b"corrupt")
    assert models.ensure("fake").read_bytes() == PAYLOAD
    assert len(requests) == 1


def test_should_list_known_names_when_model_is_unknown() -> None:
    with pytest.raises(UnknownModelError, match=r"whisper-base\.en"):
        models.ensure("nope")


def test_should_register_exactly_the_seven_m1_models() -> None:
    assert sorted(models.REGISTRY) == [
        "hey_jarvis_v0.1",
        "oww-embedding",
        "oww-melspectrogram",
        "silero-vad",
        "whisper-base.en",
        "whisper-small.en",
        "whisper-tiny.en",
    ]
    for name, spec in models.REGISTRY.items():
        assert spec.name == name
        assert spec.url.startswith("https://")
        assert len(spec.sha256) == 64
