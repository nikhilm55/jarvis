"""Downloadable model files: a pinned registry plus a verified, atomic `ensure()`."""

import hashlib
from dataclasses import dataclass
from pathlib import Path

import httpx

from jarvis.paths import cache_dir
from jarvis.paths import ensure as ensure_dir

_OWW = "https://github.com/dscripka/openWakeWord/releases/download/v0.5.1"
_WHISPER = "https://huggingface.co/ggerganov/whisper.cpp/resolve/main"


class ModelIntegrityError(RuntimeError):
    """A downloaded file's SHA-256 did not match the registry."""


class UnknownModelError(KeyError):
    """The requested model name is not in the registry."""

    def __str__(self) -> str:
        return str(self.args[0])


@dataclass(frozen=True)
class ModelSpec:
    name: str
    url: str
    sha256: str
    filename: str


REGISTRY: dict[str, ModelSpec] = {
    spec.name: spec
    for spec in (
        ModelSpec(
            "oww-melspectrogram",
            f"{_OWW}/melspectrogram.onnx",
            # pragma: allowlist nextline secret
            "ba2b0e0f8b7b875369a2c89cb13360ff53bac436f2895cced9f479fa65eb176f",
            "melspectrogram.onnx",
        ),
        ModelSpec(
            "oww-embedding",
            f"{_OWW}/embedding_model.onnx",
            # pragma: allowlist nextline secret
            "70d164290c1d095d1d4ee149bc5e00543250a7316b59f31d056cff7bd3075c1f",
            "embedding_model.onnx",
        ),
        ModelSpec(
            "hey_jarvis_v0.1",
            f"{_OWW}/hey_jarvis_v0.1.onnx",
            # pragma: allowlist nextline secret
            "94a13cfe60075b132f6a472e7e462e8123ee70861bc3fb58434a73712ee0d2cb",
            "hey_jarvis_v0.1.onnx",
        ),
        ModelSpec(
            "whisper-tiny.en",
            f"{_WHISPER}/ggml-tiny.en.bin",
            # pragma: allowlist nextline secret
            "921e4cf8686fdd993dcd081a5da5b6c365bfde1162e72b08d75ac75289920b1f",
            "ggml-tiny.en.bin",
        ),
        ModelSpec(
            "whisper-base.en",
            f"{_WHISPER}/ggml-base.en.bin",
            # pragma: allowlist nextline secret
            "a03779c86df3323075f5e796cb2ce5029f00ec8869eee3fdfb897afe36c6d002",
            "ggml-base.en.bin",
        ),
    )
}


def get_spec(name: str) -> ModelSpec:
    try:
        return REGISTRY[name]
    except KeyError:
        known = ", ".join(sorted(REGISTRY))
        raise UnknownModelError(f"unknown model {name!r}; known models: {known}") from None


def model_path(spec: ModelSpec) -> Path:
    return cache_dir() / "models" / spec.filename


def _sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        while chunk := file.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def is_cached(spec: ModelSpec) -> bool:
    """True when the cached file exists and its SHA-256 matches (local check, no network)."""
    path = model_path(spec)
    return path.is_file() and _sha256_of(path) == spec.sha256


def _open_client() -> httpx.Client:
    return httpx.Client(follow_redirects=True, timeout=httpx.Timeout(30.0, read=120.0))


def ensure(name: str) -> Path:
    """Return the verified local path of model `name`, downloading it first if needed."""
    spec = get_spec(name)
    final = model_path(spec)
    if is_cached(spec):
        return final
    ensure_dir(final.parent)
    part = final.with_name(final.name + ".part")
    digest = hashlib.sha256()
    try:
        with _open_client() as client, client.stream("GET", spec.url) as response:
            response.raise_for_status()
            with part.open("wb") as file:
                for chunk in response.iter_bytes(1024 * 1024):
                    digest.update(chunk)
                    file.write(chunk)
        if digest.hexdigest() != spec.sha256:
            raise ModelIntegrityError(
                f"{name}: SHA-256 mismatch: expected {spec.sha256}, got {digest.hexdigest()}"
            )
        part.replace(final)
    finally:
        part.unlink(missing_ok=True)
    return final
