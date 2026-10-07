import numpy as np

from jarvis.audio import FRAME_SAMPLES, SAMPLE_RATE, PreRoll


def _ramp(frame_count: int) -> list[np.ndarray]:
    """Frames of a continuous counter, so ordering and trimming are visible in the values."""
    pcm = (np.arange(frame_count * FRAME_SAMPLES) % 30000).astype(np.int16)
    return [pcm[i : i + FRAME_SAMPLES] for i in range(0, len(pcm), FRAME_SAMPLES)]


def test_should_keep_exactly_the_last_1_5_seconds_when_more_audio_was_pushed() -> None:
    preroll = PreRoll()
    frames = _ramp(40)

    for frame in frames:
        preroll.push(frame)

    snapshot = preroll.snapshot()
    assert len(snapshot) == int(1.5 * SAMPLE_RATE)
    assert np.array_equal(snapshot, np.concatenate(frames)[-len(snapshot) :])


def test_should_return_everything_oldest_first_when_less_than_capacity_was_pushed() -> None:
    preroll = PreRoll()
    frames = _ramp(3)

    for frame in frames:
        preroll.push(frame)

    assert np.array_equal(preroll.snapshot(), np.concatenate(frames))


def test_should_return_empty_int16_when_nothing_was_pushed() -> None:
    snapshot = PreRoll().snapshot()

    assert snapshot.shape == (0,) and snapshot.dtype == np.int16


def test_should_be_empty_after_clear() -> None:
    preroll = PreRoll()
    preroll.push(_ramp(1)[0])

    preroll.clear()

    assert len(preroll.snapshot()) == 0


def test_should_honour_a_custom_length_and_chunk_sizes_other_than_a_frame() -> None:
    preroll = PreRoll(seconds=0.5)
    pcm = np.arange(20000, dtype=np.int16)

    for start in range(0, len(pcm), 512):
        preroll.push(pcm[start : start + 512])

    assert np.array_equal(preroll.snapshot(), pcm[-8000:])
