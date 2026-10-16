"""Stage 1 — fetch: download every pinned input, verify it, and keep a ledger of bytes.

  uv run --no-project --python 3.11 python tools/wakeword/fetch.py [--only KEY ...] [--list]

Stdlib only. Every item is pinned by SHA-256 in pins.py (for Hugging Face files it is the LFS etag the
host publishes; Zenodo's own md5 is checked as well). An unpinned item is refused unless named in
`--trust-new`, which prints the pin to add. Unpacked archives are deleted unless `--keep-archives`. The ledger
(data/ledger.json) sums the bytes downloaded, and the run refuses to start a download that would
take the total past 2 GB (R73): that is a stop-and-ask line, not a setting.
"""

from __future__ import annotations

import argparse
import hashlib
import shutil
import sys
import tarfile
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path

from common import DATA, MAX_DOWNLOAD_BYTES, read_json, sha256_file, write_json
from pins import MD5, SHA256

_PIPER = "https://huggingface.co/rhasspy/piper-voices/resolve/c10ece1aade47bb51c153c893d14e5bf8e5b7117/en"
_OWW = "https://github.com/dscripka/openWakeWord/releases/download/v0.5.1"
_DEMAND = "https://zenodo.org/api/records/1227121/files"


@dataclass(frozen=True)
class Item:
    key: str
    url: str
    size: int
    licence: str
    source: str
    dest: str  # file name under data/downloads/, or (with `unpack`) a directory under data/ to unpack into
    unpack: str = ""  # "", "zip" or "tar.gz"


def _voice(path: str, size: int, licence: str) -> list[Item]:
    name = path.rsplit("/", 1)[1]
    base = f"{_PIPER}/{path}"
    source = "rhasspy/piper-voices"
    return [
        Item(f"piper:{name}", f"{base}.onnx", size, licence, source, f"{name}.onnx"),
        Item(f"piper:{name}.json", f"{base}.onnx.json", 0, licence, source, f"{name}.onnx.json"),
    ]


def _demand(name: str, size: int) -> Item:
    url = f"{_DEMAND}/{name}_16k.zip/content"
    return Item(
        f"demand:{name}", url, size, "CC BY 4.0", "Zenodo 1227121 (DEMAND)", f"noise/{name}", "zip"
    )


_OWW_SOURCE = "dscripka/openWakeWord v0.5.1"
ITEMS: list[Item] = [
    Item("oww:melspectrogram", f"{_OWW}/melspectrogram.onnx", 1_087_958, "Apache-2.0", _OWW_SOURCE, "melspectrogram.onnx"),
    Item("oww:embedding", f"{_OWW}/embedding_model.onnx", 1_326_578, "Apache-2.0", _OWW_SOURCE, "embedding_model.onnx"),
    *_voice("en_US/libritts_r/medium/en_US-libritts_r-medium", 78_580_914, "CC BY 4.0 (LibriTTS-R)"),
    *_voice("en_GB/vctk/medium/en_GB-vctk-medium", 76_952_753, "CC BY 4.0 (VCTK)"),
    *_voice("en_GB/aru/medium/en_GB-aru-medium", 76_754_097, "CC BY 4.0 (ARU)"),
    *_voice("en_US/ljspeech/medium/en_US-ljspeech-medium", 63_531_379, "public domain (LJ Speech)"),
    *_voice("en_US/joe/medium/en_US-joe-medium", 63_201_294, "CC0 (OHF-Voice)"),
    Item("librispeech:dev-clean", "https://www.openslr.org/resources/12/dev-clean.tar.gz", 337_926_286, "CC BY 4.0", "OpenSLR 12 (LibriSpeech)", "librispeech", "tar.gz"),
    _demand("OOFFICE", 88_995_191),
    _demand("OMEETING", 82_703_355),
    _demand("DKITCHEN", 110_501_049),
    _demand("DLIVING", 80_170_627),
    _demand("PCAFETER", 107_431_494),
]  # fmt: skip

LEDGER = DATA / "ledger.json"


def _ledger() -> dict[str, int]:
    return read_json(LEDGER) if LEDGER.exists() else {}


class OverBudget(RuntimeError):
    """A download passed the byte allowance before it finished; `args[0]` is the bytes received."""


def _download(url: str, out: Path, allowance: int) -> tuple[int, str]:
    """Download `url` to `out`, giving up (and deleting the partial file) past `allowance` bytes."""
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(out.suffix + ".part")
    md5, n = hashlib.md5(usedforsecurity=False), 0
    request = urllib.request.Request(url, headers={"User-Agent": "jarvis-wakeword-fetch/1"})  # noqa: S310
    try:
        with urllib.request.urlopen(request, timeout=60) as resp, tmp.open("wb") as handle:  # noqa: S310
            for block in iter(lambda: resp.read(1 << 20), b""):
                n += len(block)
                if n > allowance:
                    raise OverBudget(n)
                handle.write(block)
                md5.update(block)
        tmp.replace(out)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    return n, md5.hexdigest()


def _unpack(archive: Path, kind: str, into: Path) -> None:
    """Unpack into a staging directory and rename it, so `into` exists only when the unpack finished."""
    staging = into.with_name(into.name + ".unpacking")
    shutil.rmtree(staging, ignore_errors=True)  # left behind by an interrupted run
    staging.mkdir(parents=True)
    try:
        if kind == "zip":
            with zipfile.ZipFile(archive) as zf:
                zf.extractall(staging)  # noqa: S202 — pinned archive, hash-checked before this
        else:
            with tarfile.open(archive) as tf:
                tf.extractall(staging, filter="data")
        staging.rename(into)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def fetch(item: Item, *, trust_new: bool, keep_archives: bool) -> None:
    ledger = _ledger()
    target = DATA / "downloads" / Path(item.dest).name
    unpacked = DATA / item.dest
    want = SHA256.get(item.key, "")
    if item.unpack and unpacked.exists():
        print(f"have  {item.key} (unpacked)")
        return
    if not item.unpack and want and target.exists() and sha256_file(target) == want:
        print(f"have  {item.key}")
        return
    spent = sum(ledger.values())
    if spent + item.size > MAX_DOWNLOAD_BYTES:
        sys.exit(
            f"STOP: {item.key} ({item.size} B) would take the total past 2 GB ({spent} B so far)"
        )
    if not want and not trust_new:
        sys.exit(
            f"{item.key} has no pin in pins.py; run with --trust-new {item.key} to fetch and print one"
        )
    print(f"fetch {item.key}  {item.size / 1e6:.0f} MB  {item.url}", flush=True)
    try:
        n, md5 = _download(item.url, target, MAX_DOWNLOAD_BYTES - spent)
    except OverBudget as over:
        ledger[item.key] = int(over.args[0])
        write_json(LEDGER, ledger)
        sys.exit(
            f"STOP: {item.key} went past the 2 GB total after {over.args[0]} B; ask the owner (R73)"
        )
    ledger[item.key] = n
    write_json(LEDGER, ledger)
    published = MD5.get(item.key, "")
    if published and md5 != published:
        target.unlink()
        sys.exit(f"{item.key}: md5 {md5} != published {published}")
    got = sha256_file(target)
    if want and got != want:
        target.unlink()
        sys.exit(f"{item.key}: sha256 {got} != pinned {want}")
    if not want:
        print(f'  pin it in pins.py:  "{item.key}": "{got}"  # pragma: allowlist secret')
    if item.unpack:
        _unpack(target, item.unpack, unpacked)
        if not keep_archives:
            target.unlink()  # the archive is only an intermediate; the pin still guards a re-download


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--only", nargs="*", help="item keys (prefix match)")
    parser.add_argument(
        "--list", action="store_true", help="print the table (name, size, licence) and exit"
    )
    parser.add_argument(
        "--trust-new", nargs="*", default=[], help="fetch these unpinned items and print their pins"
    )
    parser.add_argument(
        "--keep-archives", action="store_true", help="keep .zip/.tar.gz files after unpacking"
    )
    args = parser.parse_args()
    items = [i for i in ITEMS if not args.only or any(i.key.startswith(p) for p in args.only)]
    if args.list:
        for i in items:
            print(f"{i.key}\t{i.size}\t{i.licence}\t{i.url}")
        print(f"total\t{sum(i.size for i in items)}")
        return 0
    for item in items:
        fetch(item, trust_new=item.key in args.trust_new, keep_archives=args.keep_archives)
    print(f"downloaded so far: {sum(_ledger().values()) / 1e6:.0f} MB of 2000 MB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
