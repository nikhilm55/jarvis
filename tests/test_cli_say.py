import pytest

from jarvis.cli import main


class _FakeHandle:
    def __init__(self, first_audio_s: float | None) -> None:
        self.first_audio_s = first_audio_s

    def wait(self, timeout: float | None = None) -> bool:
        return True


class _FakeSpeaker:
    def __init__(self, settings: object, *, first_audio_s: float | None, boom: bool) -> None:
        self.settings = settings
        self.first_audio_s = first_audio_s
        self.boom = boom
        self.said: list[str] = []
        self.earcons: list[str] = []
        self.closed = False

    def say(self, text: str) -> _FakeHandle:
        if self.boom:
            raise RuntimeError("boom")
        self.said.append(text)
        return _FakeHandle(self.first_audio_s)

    def earcon(self, name: str) -> _FakeHandle:
        self.earcons.append(name)
        return _FakeHandle(self.first_audio_s)

    def close(self) -> None:
        self.closed = True


class _Rig:
    def __init__(self, first_audio_s: float | None, boom: bool) -> None:
        self.first_audio_s = first_audio_s
        self.boom = boom
        self.speakers: list[_FakeSpeaker] = []

    def make(self, settings: object) -> _FakeSpeaker:
        speaker = _FakeSpeaker(
            settings,
            first_audio_s=self.first_audio_s,
            boom=self.boom,
        )
        self.speakers.append(speaker)
        return speaker


@pytest.fixture
def fake_speakers(monkeypatch: pytest.MonkeyPatch) -> _Rig:
    rig = _Rig(first_audio_s=0.1874, boom=False)
    monkeypatch.setattr("jarvis.cli.Speaker", rig.make)
    return rig


def test_should_print_first_audio_ms_and_close_speaker_when_say_succeeds(
    fake_speakers: _Rig,
    capsys: pytest.CaptureFixture[str],
) -> None:
    rc = main(["say", "Opening Calculator."])

    out = capsys.readouterr().out
    assert rc == 0
    assert "first audio: 187 ms" in out
    assert fake_speakers.speakers[0].said == ["Opening Calculator."]
    assert fake_speakers.speakers[0].closed is True


def test_should_call_earcon_and_return_zero_when_earcon_given(
    fake_speakers: _Rig,
    capsys: pytest.CaptureFixture[str],
) -> None:
    rc = main(["say", "--earcon", "wake"])

    out = capsys.readouterr().out
    assert rc == 0
    assert out == ""
    assert fake_speakers.speakers[0].said == []
    assert fake_speakers.speakers[0].earcons == ["wake"]
    assert fake_speakers.speakers[0].closed is True


@pytest.mark.parametrize(
    "argv",
    [
        ["say"],
        ["say", "hello", "--earcon", "wake"],
    ],
)
def test_should_return_two_and_not_construct_speaker_when_args_invalid(
    fake_speakers: _Rig,
    capsys: pytest.CaptureFixture[str],
    argv: list[str],
) -> None:
    rc = main(argv)

    err = capsys.readouterr().err
    assert rc == 2
    assert "jarvis say: give TEXT or --earcon NAME" in err
    assert fake_speakers.speakers == []


def test_should_return_one_and_print_message_when_first_audio_is_none(
    fake_speakers: _Rig,
    capsys: pytest.CaptureFixture[str],
) -> None:
    fake_speakers.first_audio_s = None

    rc = main(["say", "hello"])

    err = capsys.readouterr().err
    assert rc == 1
    assert "jarvis say: no audio was produced (see the log)" in err


def test_should_close_speaker_when_say_raises_runtime_error(
    fake_speakers: _Rig,
) -> None:
    fake_speakers.boom = True

    with pytest.raises(RuntimeError):
        main(["say", "hello"])

    assert fake_speakers.speakers[0].closed is True


def test_should_exit_with_code_two_when_earcon_is_unknown() -> None:
    with pytest.raises(SystemExit) as excinfo:
        main(["say", "--earcon", "unknown"])

    assert excinfo.value.code == 2
