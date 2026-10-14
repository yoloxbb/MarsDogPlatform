import pytest

from tools.replay_beckoning import _parser, _should_sample_frame, _video_frame_range


def test_replay_default_positive_interval_matches_fixture_label() -> None:
    args = _parser().parse_args(["--video", "wave_hand.mp4", "--output", "report.json"])

    assert (args.positive_start_sec, args.positive_end_sec) == (12.0, 20.0)


def test_replay_time_range_uses_absolute_source_frames() -> None:
    start_frame, end_frame = _video_frame_range(
        start_sec=2.25,
        end_sec=3.19,
        fps=10.0,
        frame_count=100,
    )

    assert (start_frame, end_frame) == (23, 32)
    assert [
        frame
        for frame in range(start_frame, end_frame)
        if _should_sample_frame(frame, start_frame, stride=3)
    ] == [23, 26, 29]


def test_replay_time_range_clamps_to_video_and_rejects_invalid_windows() -> None:
    assert _video_frame_range(9.0, 12.0, fps=10.0, frame_count=100) == (90, 100)

    with pytest.raises(ValueError, match="invalid video time range"):
        _video_frame_range(3.0, 3.0, fps=10.0, frame_count=100)
