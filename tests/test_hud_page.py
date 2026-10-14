"""Static checks of the HUD page against the frozen design mockup."""

import re
import typing
from pathlib import Path

import pytest

from jarvis.hud.page import read_page
from jarvis.orchestrator.hud import HudState

MOCKUP = Path(__file__).resolve().parents[1] / "docs" / "design" / "jarvis-ui-mockup.html"
PAGE_PATH = Path(__file__).resolve().parents[1] / "src" / "jarvis" / "hud" / "page.html"


def _root_tokens(html: str) -> dict[str, str]:
    """Extract custom property declarations from the first :root block."""
    match = re.search(r":root\s*\{([^}]*)\}", html)
    if match is None:
        return {}
    tokens: dict[str, str] = {}
    for decl in match.group(1).split(";"):
        if ":" not in decl:
            continue
        name, _, value = decl.partition(":")
        tokens[name.strip()] = value.strip()
    return tokens


def _rules(html: str) -> dict[str, str]:
    """Map normalised selectors to normalised declaration bodies."""
    rules: dict[str, str] = {}
    css = re.sub(r"/\*.*?\*/", "", html, flags=re.S)
    for selector, body in re.findall(r"([^{}@;]+?)\s*\{([^{}]*)\}", css):
        rules[re.sub(r"\s+", "", selector)] = re.sub(r"\s+", "", body)
    return rules


def _keyframes(html: str) -> dict[str, str]:
    """Map keyframe names to whitespace-stripped bodies."""
    frames: dict[str, str] = {}
    css = re.sub(r"/\*.*?\*/", "", html, flags=re.S)
    for name, body in re.findall(r"@keyframes\s+([\w-]+)\s*\{((?:[^{}]|\{[^{}]*\})*)\}", css):
        frames[name] = re.sub(r"\s+", "", body)
    return frames


def test_should_match_mockup_tokens_when_page_defines_root_tokens() -> None:
    page = read_page()
    mockup = MOCKUP.read_text(encoding="utf-8")
    page_tokens = _root_tokens(page)
    mockup_tokens = _root_tokens(mockup)
    required = {
        "--surface",
        "--hairline",
        "--hairline-strong",
        "--ink",
        "--body",
        "--mute",
        "--ash",
        "--blue",
        "--green",
        "--yellow",
        "--red",
        "--think",
        "--r-xs",
        "--r-full",
    }
    assert required <= set(page_tokens)
    for name, value in page_tokens.items():
        assert name in mockup_tokens
        assert value == mockup_tokens[name]


@pytest.mark.parametrize(
    "selector",
    [
        ".orb",
        ".orb::before",
        ".orb::after",
        ".orb.listen",
        ".orb.think",
        ".orb.confirm",
        ".orb.error",
        ".orb.idle",
        ".orb.idle::after",
        ".orb.listen::before",
        ".orb.think::after",
        ".wave",
        ".wave i",
        ".wave i:nth-child(1)",
        ".wave i:nth-child(6)",
        ".pill",
        ".pill .text",
        ".pill .label",
    ],
)
def test_should_match_mockup_signature_rules_when_selector_is_signature(
    selector: str,
) -> None:
    page = read_page()
    mockup = MOCKUP.read_text(encoding="utf-8")
    page_rules = _rules(page)
    mockup_rules = _rules(mockup)
    key = re.sub(r"\s+", "", selector)
    assert key in page_rules
    assert key in mockup_rules
    assert page_rules[key] == mockup_rules[key]


@pytest.mark.parametrize("name", ["ring", "breathe", "wave"])
def test_should_match_mockup_keyframes_when_name_is_signature(name: str) -> None:
    page = read_page()
    mockup = MOCKUP.read_text(encoding="utf-8")
    page_frames = _keyframes(page)
    mockup_frames = _keyframes(mockup)
    assert name in page_frames
    assert name in mockup_frames
    assert page_frames[name] == mockup_frames[name]


def test_should_use_mockup_font_stack_when_page_defines_typography() -> None:
    page = read_page()
    normalised = re.sub(r"\s+", "", page)
    assert 'font-feature-settings:"calt","kern","liga","ss03"' in normalised
    assert "Inter" in page


def test_should_list_all_hud_states_when_page_defines_looks_table() -> None:
    page = read_page()
    assert "/* LOOKS */" in page
    assert "/* END LOOKS */" in page
    start = page.index("/* LOOKS */")
    end = page.index("/* END LOOKS */")
    looks = page[start:end]
    for state in typing.get_args(HudState):
        assert re.search(rf"\b{state}\s*:", looks)


def test_should_never_insert_event_text_as_html_when_page_renders_events() -> None:
    page = read_page()
    for forbidden in (
        "innerHTML",
        "outerHTML",
        "insertAdjacentHTML",
        "document.write",
        "eval(",
        "new Function",
    ):
        assert forbidden not in page
    assert "textContent" in page


def test_should_make_no_external_request_when_page_is_self_contained() -> None:
    page = read_page()
    assert "http://" not in page
    assert "https://" not in page
    assert "<link" not in page
    assert "@import" not in page
    assert "EventSource" not in page


def test_should_stream_with_fetch_and_bearer_when_page_polls_events() -> None:
    page = read_page()
    assert "fetch(" in page
    assert "Authorization" in page
    assert "Bearer " in page
    assert "location.hash" in page


def test_should_auto_hide_after_four_seconds_when_page_defines_hide_delay() -> None:
    page = read_page()
    assert "const HIDE_MS = 4000;" in page


def test_should_respect_reduced_motion_when_page_defines_motion_styles() -> None:
    page = read_page()
    normalised = re.sub(r"\s+", "", page)
    assert "@media(prefers-reduced-motion:reduce)" in normalised
    start = normalised.index("@media(prefers-reduced-motion:reduce)")
    block = normalised[start:]
    assert "animation:none" in block
    assert "transition:none" in block


def test_should_keep_background_transparent_when_page_defines_body_rule() -> None:
    page = read_page()
    rules = _rules(page)
    assert "html,body" in rules
    assert "background:transparent" in rules["html,body"]


def test_should_return_page_file_text_when_reading_page() -> None:
    assert read_page() == PAGE_PATH.read_text(encoding="utf-8")
