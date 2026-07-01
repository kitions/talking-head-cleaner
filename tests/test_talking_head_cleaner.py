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
    merge_cuts,
    output_name_for,
    parse_args,
    source_record_from_stat,
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

    for key in ["analysis", "final", "manifests", "verification", "waveforms", "work"]:
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
