import asyncio
import hashlib
import re
from pathlib import Path

import httpx

from jarvis.hud.page import read_page
from tests.hud_rig import started

HUD_DIR = Path(__file__).resolve().parents[1] / "src" / "jarvis" / "hud"
FONT_PATH = HUD_DIR / "fonts" / "InterVariable.woff2"
LICENSE_PATH = HUD_DIR / "fonts" / "LICENSE.txt"
FONT_SHA256 = (
    "693b77d4f32ee9b8bfc995589b5fad5e99adf2832738661f5402f9978429a8e3"  # pragma: allowlist secret
)
LICENSE_SHA256 = (
    "262481e844521b326f5ecd053e59b98c8b2da78c8ee1bdbb6e8174305e54935a"  # pragma: allowlist secret
)


def test_should_serve_font_without_token_when_path_is_exact() -> None:
    async def scenario() -> None:
        server = await started()
        try:
            base = server.url.removesuffix("/hud")
            url = base + "/fonts/InterVariable.woff2"
            async with httpx.AsyncClient() as client:
                async with asyncio.timeout(5):
                    response = await client.get(url)
            assert response.status_code == 200
            assert response.headers["content-type"] == "font/woff2"
            assert response.content == FONT_PATH.read_bytes()
            assert "immutable" in response.headers["cache-control"]
            assert response.headers["x-content-type-options"] == "nosniff"
        finally:
            await server.close()

    asyncio.run(scenario())


def test_should_include_font_src_in_csp_when_page_is_served() -> None:
    async def scenario() -> None:
        server = await started()
        try:
            async with httpx.AsyncClient() as client:
                async with asyncio.timeout(5):
                    response = await client.get(server.url)
            assert "font-src 'self'" in response.headers["content-security-policy"]
        finally:
            await server.close()

    asyncio.run(scenario())


def test_should_reject_unauthorised_paths_when_no_token_is_present() -> None:
    async def scenario() -> None:
        server = await started()
        try:
            base = server.url.removesuffix("/hud")
            async with httpx.AsyncClient() as client:
                async with asyncio.timeout(5):
                    other = await client.get(base + "/fonts/other.woff2")
                    trailing = await client.get(base + "/fonts/InterVariable.woff2/")
                    events = await client.get(base + "/events")
            assert other.status_code == 401
            assert trailing.status_code == 401
            assert events.status_code == 401
        finally:
            await server.close()

    asyncio.run(scenario())


def test_should_reject_font_when_host_is_evil() -> None:
    async def scenario() -> None:
        server = await started()
        try:
            base = server.url.removesuffix("/hud")
            url = base + "/fonts/InterVariable.woff2"
            async with httpx.AsyncClient() as client:
                async with asyncio.timeout(5):
                    response = await client.get(url, headers={"Host": "evil.example"})
            assert response.status_code == 403
        finally:
            await server.close()

    asyncio.run(scenario())


def test_should_define_inter_font_face_when_page_is_read() -> None:
    page = read_page()
    normalised = re.sub(r"\s+", "", page)
    assert (
        "@font-face{font-family:Inter;src:url(/fonts/InterVariable.woff2)"
        'format("woff2");' in normalised
    )
    assert "font-display:swap" in normalised


def test_should_match_audited_hashes_when_files_are_shipped() -> None:
    font_bytes = FONT_PATH.read_bytes()
    assert hashlib.sha256(font_bytes).hexdigest() == FONT_SHA256
    assert font_bytes.startswith(b"wOF2")
    assert hashlib.sha256(LICENSE_PATH.read_bytes()).hexdigest() == LICENSE_SHA256
    assert "SIL OPEN FONT LICENSE" in LICENSE_PATH.read_text(encoding="utf-8")
