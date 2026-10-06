"""Command-line entry point. Grows into `jarvis doctor`, `jarvis ptt`, … (FRS §5.17)."""

import argparse

from jarvis import __version__


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="jarvis", description="Voice control for your whole PC.")
    parser.add_argument("--version", action="version", version=f"jarvis {__version__}")
    return parser


def main(argv: list[str] | None = None) -> int:
    build_parser().parse_args(argv)
    return 0
