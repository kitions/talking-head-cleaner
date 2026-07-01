import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from talking_head_cleaner import (  # noqa: E402
    CleanerConfig,
    build_cut_candidates,
    build_project_dirs,
    classify_token,
    find_residual_fillers,
    plan_residual_refine_cuts,
    render,
    merge_cuts,
    output_name_for,
    parse_args,
    scan_input,
    SecondaryTranscriber,
    source_record_from_stat,
    dry_run_project,
    format_srt_time,
    map_words_after_cuts,
    main,
    process_one,
    srt_from_words,
)


def test_classifies_fillers_by_mode():
    assert classify_token("呃", mode="safe") == "A"
    assert classify_token("嗯,", mode="aggressive") == "A"
    assert classify_token("啊", mode="safe") == "review"
    assert classify_token("啊", mode="aggressive") == "B"
    assert classify_token("这个", mode="aggressive") == "review"
    assert classify_token("医生", mode="aggressive") is None


def test_build_cut_candidates_adds_padding_and_review_only():
    words = [
        {"word": "呃,", "start": 1.0, "end": 1.2, "probability": 0.9},
        {"word": "啊", "start": 2.0, "end": 2.1, "probability": 0.8},
        {"word": "这个", "start": 3.0, "end": 3.2, "probability": 0.9},
    ]
    config = CleanerConfig(mode="aggressive", pad_before=0.1, pad_after=0.14)

    accepted, review = build_cut_candidates(words, config=config, source="unit")

    assert accepted == [
        {
            "start": 0.9,
            "end": 1.34,
            "text": "呃",
            "reason": "filler:呃",
            "class": "A",
            "confidence": 0.9,
            "source": "unit",
            "word_start": 1.0,
            "word_end": 1.2,
        },
        {
            "start": 1.9,
            "end": 2.24,
            "text": "啊",
            "reason": "filler:啊",
            "class": "B",
            "confidence": 0.8,
            "source": "unit",
            "word_start": 2.0,
            "word_end": 2.1,
        },
    ]
    assert review[0]["text"] == "这个"
    assert review[0]["reason"] == "review_token:这个"


def test_merge_cuts_combines_nearby_ranges_and_reasons():
    cuts = [
        {"start": 1.0, "end": 1.2, "reason": "filler:呃", "confidence": 0.9},
        {"start": 1.25, "end": 1.4, "reason": "long_pause", "confidence": 1.0},
        {"start": 2.0, "end": 2.1, "reason": "filler:嗯", "confidence": 0.8},
    ]

    merged = merge_cuts(cuts, gap=0.08)

    assert len(merged) == 2
    assert merged[0]["start"] == 1.0
    assert merged[0]["end"] == 1.4
    assert merged[0]["confidence"] == 0.9
    assert merged[0]["reason"] == "filler:呃+long_pause"


def test_find_residual_fillers_reads_whisper_timestamped_segments():
    transcript = {
        "segments": [
            {
                "words": [
                    {"text": "医生", "start": 0.0, "end": 0.2},
                    {"text": "呃,", "start": 0.3, "end": 0.4},
                    {"text": "[*]", "start": 0.5, "end": 0.6},
                ]
            }
        ]
    }

    residual = find_residual_fillers(transcript)

    assert residual == [{"token": "呃", "start": 0.3, "end": 0.4, "raw": "呃,"}]


def test_project_dirs_are_created(tmp_path):
    dirs = build_project_dirs(tmp_path)

    for key in [
        "analysis",
        "final",
        "manifests",
        "verification",
        "waveforms",
        "work",
        "subtitles",
    ]:
        assert dirs[key].is_dir()


def test_output_name_for_adds_mode_suffix_without_overwriting():
    assert (
        output_name_for(Path("demo.mp4"), mode="aggressive")
        == "demo_roughcut_aggressive.mp4"
    )


def test_source_record_from_stat_is_serializable(tmp_path):
    media = tmp_path / "a.mp4"
    media.write_bytes(b"abc")

    record = source_record_from_stat(media)

    assert record["name"] == "a.mp4"
    assert record["size"] == 3
    assert len(record["sha256"]) == 64
    json.dumps(record)


def test_redact_path_returns_name_only():
    from talking_head_cleaner import redact_path

    assert redact_path(Path("/private/input/a.mp4"), redact=True) == "a.mp4"
    assert redact_path(Path("/private/input/a.mp4"), redact=False).endswith(
        "/private/input/a.mp4"
    )


def test_source_record_redacts_path_when_requested(tmp_path):
    media = tmp_path / "a.mp4"
    media.write_bytes(b"abc")

    record = source_record_from_stat(media, include_hash=False, redact_paths=True)

    assert record["path"] == "a.mp4"
    assert record["name"] == "a.mp4"


def test_redact_probe_paths_updates_format_filename():
    from talking_head_cleaner import redact_probe_paths

    probe = {
        "format": {
            "filename": "/private/output/a_roughcut_aggressive.mp4",
            "duration": "10.0",
        },
        "streams": [],
    }

    redacted = redact_probe_paths(probe, redact=True)

    assert redacted["format"]["filename"] == "a_roughcut_aggressive.mp4"
    assert probe["format"]["filename"] == "/private/output/a_roughcut_aggressive.mp4"


def test_parse_args_supports_dry_run_and_refine_rounds(tmp_path):
    args = parse_args(
        [
            "--input",
            str(tmp_path),
            "--output",
            str(tmp_path / "out"),
            "--mode",
            "aggressive",
            "--dry-run",
            "--max-refine-rounds",
            "1",
        ]
    )

    assert args.input == tmp_path
    assert args.output == tmp_path / "out"
    assert args.mode == "aggressive"
    assert args.dry_run is True
    assert args.max_refine_rounds == 1


def test_parse_args_supports_redact_paths(tmp_path):
    args = parse_args(
        [
            "--input",
            str(tmp_path),
            "--output",
            str(tmp_path / "out"),
            "--redact-paths",
        ]
    )

    assert args.redact_paths is True


def test_parse_args_supports_write_srt(tmp_path):
    args = parse_args(
        [
            "--input",
            str(tmp_path),
            "--output",
            str(tmp_path / "out"),
            "--write-srt",
        ]
    )

    assert args.write_srt is True


def test_validate_args_rejects_negative_refine_rounds(tmp_path):
    from talking_head_cleaner import validate_args

    args = parse_args(
        [
            "--input",
            str(tmp_path),
            "--output",
            str(tmp_path / "out"),
            "--max-refine-rounds",
            "-1",
        ]
    )

    try:
        validate_args(args)
    except SystemExit as exc:
        assert "max-refine-rounds" in str(exc)
    else:
        raise AssertionError("expected SystemExit")


def test_validate_args_rejects_excessive_refine_rounds(tmp_path):
    from talking_head_cleaner import validate_args

    args = parse_args(
        [
            "--input",
            str(tmp_path),
            "--output",
            str(tmp_path / "out"),
            "--max-refine-rounds",
            "4",
        ]
    )

    try:
        validate_args(args)
    except SystemExit as exc:
        assert "max-refine-rounds" in str(exc)
    else:
        raise AssertionError("expected SystemExit")


def test_validate_args_rejects_out_of_range_keep_pause(tmp_path):
    from talking_head_cleaner import validate_args

    low = parse_args(
        [
            "--input",
            str(tmp_path),
            "--output",
            str(tmp_path / "out"),
            "--keep-pause",
            "0.01",
        ]
    )
    high = parse_args(
        [
            "--input",
            str(tmp_path),
            "--output",
            str(tmp_path / "out"),
            "--keep-pause",
            "2.5",
        ]
    )

    for args in [low, high]:
        try:
            validate_args(args)
        except SystemExit as exc:
            assert "keep-pause" in str(exc)
        else:
            raise AssertionError("expected SystemExit")


def test_validate_args_rejects_out_of_range_fade_ms(tmp_path):
    from talking_head_cleaner import validate_args

    low = parse_args(
        [
            "--input",
            str(tmp_path),
            "--output",
            str(tmp_path / "out"),
            "--fade-ms",
            "-1",
        ]
    )
    high = parse_args(
        [
            "--input",
            str(tmp_path),
            "--output",
            str(tmp_path / "out"),
            "--fade-ms",
            "250",
        ]
    )

    for args in [low, high]:
        try:
            validate_args(args)
        except SystemExit as exc:
            assert "fade-ms" in str(exc)
        else:
            raise AssertionError("expected SystemExit")


def test_validate_args_accepts_boundary_values(tmp_path):
    from talking_head_cleaner import validate_args

    args = parse_args(
        [
            "--input",
            str(tmp_path),
            "--output",
            str(tmp_path / "out"),
            "--max-refine-rounds",
            "2",
            "--keep-pause",
            "0.05",
            "--fade-ms",
            "200",
        ]
    )

    validate_args(args)


def test_scan_input_accepts_uppercase_mp4(tmp_path):
    lower = tmp_path / "a.mp4"
    upper = tmp_path / "b.MP4"
    ignored = tmp_path / "c.mov"
    lower.write_bytes(b"")
    upper.write_bytes(b"")
    ignored.write_bytes(b"")

    assert scan_input(tmp_path) == [lower, upper]


def test_dry_run_source_record_does_not_hash_by_default(tmp_path):
    media = tmp_path / "a.mp4"
    media.write_bytes(b"abc")

    record = source_record_from_stat(media, include_hash=False)

    assert "sha256" not in record
    assert record["size"] == 3


def test_dry_run_redacts_manifest_paths_when_requested(tmp_path):
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    media = input_dir / "a.mp4"
    media.write_bytes(b"abc")
    output = tmp_path / "out"
    dirs = build_project_dirs(output)

    manifests = dry_run_project(
        input_dir,
        output,
        dirs,
        mode="aggressive",
        hash_sources=False,
        redact_paths=True,
    )

    manifest = manifests[0]
    assert manifest["source"] == "a.mp4"
    assert manifest["final_output"] == "a_roughcut_aggressive.mp4"
    assert manifest["source_record"]["path"] == "a.mp4"


def test_main_dry_run_accepts_write_srt_flag(tmp_path):
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    (input_dir / "a.mp4").write_bytes(b"abc")
    output = tmp_path / "out"

    result = main(
        [
            "--input",
            str(input_dir),
            "--output",
            str(output),
            "--dry-run",
            "--write-srt",
            "--redact-paths",
        ]
    )

    assert result == 0
    assert (output / "manifests" / "a_manifest.json").is_file()


def test_format_srt_time_uses_millisecond_commas():
    assert format_srt_time(0) == "00:00:00,000"
    assert format_srt_time(65.4321) == "00:01:05,432"
    assert format_srt_time(3661.9996) == "01:01:02,000"


def test_map_words_after_cuts_removes_cut_words_and_shifts_time():
    words = [
        {"word": "你好", "start": 0.0, "end": 0.4},
        {"word": "嗯", "start": 1.0, "end": 1.2},
        {"word": "继续", "start": 2.0, "end": 2.4},
    ]
    cuts = [{"start": 0.8, "end": 1.5, "reason": "unit"}]

    mapped = map_words_after_cuts(words, cuts, duration=3.0)

    assert mapped == [
        {"text": "你好", "start": 0.0, "end": 0.4},
        {"text": "继续", "start": 1.3, "end": 1.7},
    ]


def test_srt_from_words_groups_words_into_cues():
    words = [
        {"text": "你好", "start": 0.0, "end": 0.5},
        {"text": "继续", "start": 0.6, "end": 1.0},
        {"text": "下一句", "start": 2.2, "end": 2.8},
    ]

    srt = srt_from_words(words, max_chars=8, max_gap=0.8)

    assert "1\n00:00:00,000 --> 00:00:01,000\n你好继续" in srt
    assert "2\n00:00:02,200 --> 00:00:02,800\n下一句" in srt


def test_process_one_writes_cut_aware_srt(tmp_path, monkeypatch):
    media = tmp_path / "input.mp4"
    media.write_bytes(b"media")
    dirs = build_project_dirs(tmp_path / "out")

    class FakeSecondaryTranscriber:
        def transcribe(self, media_path, output_path):
            return {
                "segments": [
                    {
                        "words": [
                            {"word": "你好", "start": 0.0, "end": 0.4},
                            {"word": "嗯", "start": 1.0, "end": 1.2},
                            {"word": "继续", "start": 2.0, "end": 2.4},
                        ]
                    }
                ]
            }

    def fake_render(source, output, cuts, *, duration, config):
        output.write_bytes(b"rendered")

    monkeypatch.setattr("talking_head_cleaner.media_duration", lambda path: 3.0)
    monkeypatch.setattr("talking_head_cleaner.render", fake_render)
    monkeypatch.setattr(
        "talking_head_cleaner.probe",
        lambda path: {"format": {"duration": "2.3", "filename": str(path)}, "streams": []},
    )

    manifest = process_one(
        media,
        dirs=dirs,
        config=CleanerConfig(mode="aggressive"),
        primary_model="primary",
        secondary_model="secondary",
        secondary_transcriber=FakeSecondaryTranscriber(),
        skip_primary=True,
        max_refine_rounds=0,
        hash_sources=False,
        redact_paths=True,
        write_srt_file=True,
    )

    subtitle_path = dirs["subtitles"] / "input_roughcut_aggressive.srt"
    assert manifest["subtitle_output"] == "input_roughcut_aggressive.srt"
    assert subtitle_path.read_text(encoding="utf-8") == (
        "1\n00:00:00,000 --> 00:00:00,400\n你好\n\n"
        "2\n00:00:01,560 --> 00:00:01,960\n继续\n"
    )


def test_residual_refine_keeps_ah_for_review_by_default():
    residual = [
        {"token": "呃", "start": 1.0, "end": 1.2, "raw": "呃,"},
        {"token": "啊", "start": 2.0, "end": 2.1, "raw": "啊"},
    ]
    config = CleanerConfig(mode="aggressive", pad_before=0.1, pad_after=0.14)

    cuts, review = plan_residual_refine_cuts(residual, config=config, round_index=1)

    assert [cut["text"] for cut in cuts] == ["呃"]
    assert review == [
        {
            "start": 2.0,
            "end": 2.1,
            "text": "啊",
            "reason": "residual_review_token:啊",
            "confidence": 1.0,
            "source": "verification_round_1",
        }
    ]


def test_secondary_transcriber_loads_model_once(tmp_path):
    calls = []

    class FakeWhisper:
        @staticmethod
        def load_model(model_name, device="cpu"):
            calls.append((model_name, device))
            return "model"

        @staticmethod
        def load_audio(path):
            return f"audio:{path}"

        @staticmethod
        def transcribe(model, audio, **kwargs):
            return {"model": model, "audio": audio, "segments": []}

    transcriber = SecondaryTranscriber("small", whisper_module=FakeWhisper)
    first = transcriber.transcribe(Path("a.mp4"), tmp_path / "a.json")
    second = transcriber.transcribe(Path("b.mp4"), tmp_path / "b.json")

    assert calls == [("small", "cpu")]
    assert first["model"] == "model"
    assert second["model"] == "model"


def test_render_without_cuts_uses_ffmpeg_by_default(tmp_path, monkeypatch):
    calls = []
    source = tmp_path / "input.mp4"
    output = tmp_path / "output.mp4"
    source.write_bytes(b"source")

    def fake_run(command, *, capture=False):
        calls.append(command)
        output.write_bytes(b"rendered")

    monkeypatch.setattr("talking_head_cleaner.run", fake_run)

    render(source, output, [], duration=1.0, config=CleanerConfig())

    assert calls
    assert calls[0][0] == "ffmpeg"
    assert output.read_bytes() == b"rendered"
