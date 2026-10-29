"""Validate and route the brain's file tool calls (FR-PC-08): policy names in, service calls out."""

from collections.abc import Callable, Coroutine, Mapping
from typing import Any, Protocol

from jarvis.brain.failures import ToolError
from jarvis.files.ops import FileError
from jarvis.files.search import KINDS, WHENS

__all__ = ["FilesLike", "call_files"]

_MAX_PATH = 1000
_MAX_PATHS = 2000  # a whole Downloads folder goes as one folder with contents=true, not a list
_Call = Coroutine[Any, Any, dict[str, object]]


class FilesLike(Protocol):
    """The file service surface the brain uses (jarvis.files.service.FilesService)."""

    async def search_files(
        self, query: str, folder: str = "~", when: str | None = None, kind: str | None = None
    ) -> dict[str, object]: ...

    async def open_file(self, path: str) -> dict[str, object]: ...

    async def reveal(self, path: str) -> dict[str, object]: ...

    async def trash(self, paths: list[str], contents: bool = False) -> dict[str, object]: ...

    async def delete_permanently(self, paths: list[str]) -> dict[str, object]: ...

    async def move(self, paths: list[str], dest: str) -> dict[str, object]: ...

    async def rename(self, path: str, name: str) -> dict[str, object]: ...

    async def copy(self, paths: list[str], dest: str) -> dict[str, object]: ...

    async def zip(self, paths: list[str], dest: str) -> dict[str, object]: ...


def _path(label: str, value: object) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > _MAX_PATH:
        raise ToolError(f"{label} must be a path of 1 to {_MAX_PATH} characters")
    if "\x00" in value or not value.isprintable():
        raise ToolError(f"{label} must not contain control characters")
    return value.strip()


def _paths(value: object) -> list[str]:
    if not isinstance(value, list) or not value or len(value) > _MAX_PATHS:
        raise ToolError(f"paths must be a list of 1 to {_MAX_PATHS} paths")
    return [_path("each path", item) for item in value]


def _keys(name: str, args: Mapping[str, object], required: set[str], optional: set[str]) -> None:
    keys = set(args)
    if not required <= keys or keys - required - optional:
        wanted = sorted(required) + [f"{k}?" for k in sorted(optional)]
        raise ToolError(f"{name}: expected arguments {', '.join(wanted)}")


def _search(files: FilesLike, args: Mapping[str, object]) -> _Call:
    _keys("files.search", args, {"query"}, {"folder", "when", "kind"})
    query = args["query"]
    if not isinstance(query, str) or not query.strip() or len(query) > 200:
        raise ToolError("query must be 1 to 200 characters")
    when, kind = args.get("when"), args.get("kind")
    if when is not None and when not in WHENS:
        raise ToolError(f"when must be one of {', '.join(WHENS)}")
    if kind is not None and kind not in (*KINDS, "folder"):
        raise ToolError(f"kind must be one of {', '.join([*KINDS, 'folder'])}")
    folder = _path("folder", args.get("folder", "~"))
    return files.search_files(query.strip(), folder, when, kind)


def _one_path(method: str) -> Callable[[FilesLike, Mapping[str, object]], _Call]:
    def build(files: FilesLike, args: Mapping[str, object]) -> _Call:
        _keys(f"files.{method}", args, {"path"}, set())
        return getattr(files, method)(_path("path", args["path"]))  # type: ignore[no-any-return]

    return build


def _trash(files: FilesLike, args: Mapping[str, object]) -> _Call:
    _keys("files.trash", args, {"paths"}, {"contents"})
    contents = args.get("contents", False)
    if not isinstance(contents, bool):
        raise ToolError("contents must be true or false")
    return files.trash(_paths(args["paths"]), contents)


def _delete(files: FilesLike, args: Mapping[str, object]) -> _Call:
    _keys("files.delete_permanently", args, {"paths"}, set())
    return files.delete_permanently(_paths(args["paths"]))


def _into(method: str) -> Callable[[FilesLike, Mapping[str, object]], _Call]:
    def build(files: FilesLike, args: Mapping[str, object]) -> _Call:
        _keys(f"files.{method}", args, {"paths", "dest"}, set())
        call = getattr(files, method)
        return call(_paths(args["paths"]), _path("dest", args["dest"]))  # type: ignore[no-any-return]

    return build


def _rename(files: FilesLike, args: Mapping[str, object]) -> _Call:
    _keys("files.rename", args, {"path", "name"}, set())
    return files.rename(_path("path", args["path"]), _path("name", args["name"]))


_HANDLERS: dict[str, Callable[[FilesLike, Mapping[str, object]], _Call]] = {
    "files.search": _search,
    "files.open": _one_path("open_file"),
    "files.reveal": _one_path("reveal"),
    "files.trash": _trash,
    "files.delete_permanently": _delete,
    "files.move": _into("move"),
    "files.copy": _into("copy"),
    "files.zip": _into("zip"),
    "files.rename": _rename,
}


async def call_files(
    files: FilesLike, policy_name: str, args: Mapping[str, object]
) -> dict[str, object]:
    """Validate and run a file tool call; file errors become ToolError with their code."""
    handler = _HANDLERS.get(policy_name)
    if handler is None:
        raise ToolError(f"unknown file tool {policy_name}")
    try:
        return await handler(files, args)
    except FileError as exc:
        raise ToolError(f"{exc.code}: {exc.message}") from None
    except (OSError, ValueError) as exc:
        raise ToolError(f"INTERNAL: {exc}") from None
