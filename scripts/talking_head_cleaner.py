#!/usr/bin/env python3
"""Local talking-head rough cut cleaner.

This tool keeps the video local:

1. Transcribe with local ASR models.
2. Convert filler words and pauses into cut decisions.
3. Render synchronized audio/video cuts with FFmpeg.
4. Optionally re-transcribe the output and do one residual-filler refine pass.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
import shutil
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable


FILLER_A = {"嗯", "呃", "额", "唔", "呣"}
FILLER_B = {"啊"}
REVIEW_TOKENS = {"这个", "就是", "然后", "然后呢", "那个", "其实", "就是说"}
PUNCTUATION_RE = re.compile(r"[，,。.!！?？、；;：:\s]+")
DEFAULT_PRIMARY_MODEL = "mlx-community/whisper-large-v3-turbo"
DEFAULT_SECONDARY_MODEL = "small"
PROMPT = (
    "以下是中文口播的原始逐字稿。请逐字记录，保留嗯、啊、呃、额、唔、这个、"
    "就是、然后等口头语，也保留口误、重复和说到一半重新开始的内容，不要润色或改写。"
)


@dataclass
class CleanerConfig:
    mode: str = "aggressive"
    pad_before: float = 0.10
    pad_after: float = 0.14
    merge_gap: float = 0.08
    fade: float = 0.03
    long_pause_threshold: float = 1.2
    keep_pause: float = 0.4
    min_confidence: float = 0.05
    max_filler_duration: float = 1.2
    copy_when_no_cuts: bool = False


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Local-only talking-head filler cleaner using Whisper + FFmpeg."
    )
    parser.add_argument("--input", type=Path, required=True, help="Directory containing mp4 files.")
    parser.add_argument("--output", type=Path, required=True, help="Output project directory.")
    parser.add_argument(
        "--mode",
        choices=["safe", "aggressive", "editor"],
        default="aggressive",
        help="Cleaning strength. editor currently behaves like aggressive plus review reporting.",
    )
    parser.add_argument("--primary-model", default=DEFAULT_PRIMARY_MODEL)
    parser.add_argument("--secondary-model", default=DEFAULT_SECONDARY_MODEL)
    parser.add_argument("--max-refine-rounds", type=int, default=1)
    parser.add_argument("--keep-pause", type=float, default=0.4)
    parser.add_argument("--fade-ms", type=float, default=30.0)
    parser.add_argument("--dry-run", action="store_true", help="Create project skeleton only.")
    parser.add_argument(
        "--write-srt",
        action="store_true",
        help="Write cut-aware SRT subtitles for final outputs.",
    )
    parser.add_argument(
        "--hash-sources",
        action="store_true",
        help="Include source sha256 in manifests. Disabled by default for fast dry-runs.",
    )
    parser.add_argument(
        "--redact-paths",
        action="store_true",
        help="Write only filenames in manifests/reports instead of absolute paths.",
    )
    parser.add_argument(
        "--copy-when-no-cuts",
        action="store_true",
        help="Copy source instead of re-encoding when no cuts are selected.",
    )
    parser.add_argument(
        "--skip-primary",
        action="store_true",
        help="Do not use MLX Whisper; useful when Metal is unavailable. Uses secondary model only.",
    )
    parser.add_argument(
        "--skip-existing",
        action="store_true",
        help="Skip files whose final output already exists.",
    )
    return parser.parse_args(argv)


def validate_args(args: argparse.Namespace) -> None:
    if args.max_refine_rounds < 0 or args.max_refine_rounds > 2:
        raise SystemExit("--max-refine-rounds must be between 0 and 2")
    if args.keep_pause < 0.05 or args.keep_pause > 2.0:
        raise SystemExit("--keep-pause must be between 0.05 and 2.0 seconds")
    if args.fade_ms < 0 or args.fade_ms > 200:
        raise SystemExit("--fade-ms must be between 0 and 200")


def clean_token(text: str) -> str:
    return PUNCTUATION_RE.sub("", str(text or "")).strip().lower()


def word_text(word: dict) -> str:
    return clean_token(word.get("word", word.get("text", "")))


def word_confidence(word: dict) -> float:
    return float(word.get("probability", word.get("confidence", 1.0)))


def classify_token(token: str, *, mode: str) -> str | None:
    token = clean_token(token)
    if token in FILLER_A:
        return "A"
    if token in FILLER_B:
        return "review" if mode == "safe" else "B"
    if token in REVIEW_TOKENS:
        return "review"
    return None


def build_project_dirs(output: Path) -> dict[str, Path]:
    dirs = {
        "analysis": output / "analysis",
        "final": output / "final",
        "manifests": output / "manifests",
        "verification": output / "verification",
        "waveforms": output / "waveforms",
        "subtitles": output / "subtitles",
        "work": output / "work",
    }
    for directory in dirs.values():
        directory.mkdir(parents=True, exist_ok=True)
    return dirs


def output_name_for(media: Path, *, mode: str) -> str:
    return f"{media.stem}_roughcut_{mode}.mp4"


def write_json(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def run(command: list[str], *, capture: bool = False) -> subprocess.CompletedProcess:
    return subprocess.run(
        command,
        check=True,
        text=True,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.PIPE if capture else None,
    )


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def redact_path(path: Path, *, redact: bool) -> str:
    return path.name if redact else str(path.resolve())


def redact_probe_paths(probe_data: dict, *, redact: bool) -> dict:
    if not redact:
        return probe_data
    redacted = copy.deepcopy(probe_data)
    filename = redacted.get("format", {}).get("filename")
    if filename:
        redacted["format"]["filename"] = Path(filename).name
    return redacted


def source_record_from_stat(
    path: Path, *, include_hash: bool = True, redact_paths: bool = False
) -> dict:
    stat = path.stat()
    record = {
        "path": redact_path(path, redact=redact_paths),
        "name": path.name,
        "size": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
    }
    if include_hash:
        record["sha256"] = sha256(path)
    return record


def probe(path: Path) -> dict:
    result = run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=filename,duration,size:stream=index,codec_type,codec_name,width,height,r_frame_rate,sample_rate,channels",
            "-of",
            "json",
            str(path),
        ],
        capture=True,
    )
    return json.loads(result.stdout)


def media_duration(path: Path) -> float:
    return float(probe(path)["format"]["duration"])


def flatten_words(transcript: dict) -> list[dict]:
    words = transcript.get("word_timestamps")
    if words:
        return list(words)
    return [word for segment in transcript.get("segments", []) for word in segment.get("words", [])]


def build_cut_candidates(
    words: Iterable[dict], *, config: CleanerConfig, source: str
) -> tuple[list[dict], list[dict]]:
    accepted: list[dict] = []
    review: list[dict] = []
    for word in words:
        token = word_text(word)
        classification = classify_token(token, mode=config.mode)
        if classification is None:
            continue
        start = float(word["start"])
        end = float(word["end"])
        confidence = word_confidence(word)
        duration = end - start

        if classification == "review":
            review.append(
                {
                    "start": round(start, 3),
                    "end": round(end, 3),
                    "text": token,
                    "reason": f"review_token:{token}",
                    "confidence": round(confidence, 4),
                    "source": source,
                }
            )
            continue

        if not (0.02 <= duration <= config.max_filler_duration):
            review.append(
                {
                    "start": round(start, 3),
                    "end": round(end, 3),
                    "text": token,
                    "reason": f"duration_out_of_range:{token}",
                    "confidence": round(confidence, 4),
                    "source": source,
                }
            )
            continue
        if confidence < config.min_confidence:
            review.append(
                {
                    "start": round(start, 3),
                    "end": round(end, 3),
                    "text": token,
                    "reason": f"low_confidence:{token}",
                    "confidence": round(confidence, 4),
                    "source": source,
                }
            )
            continue

        accepted.append(
            {
                "start": round(max(0.0, start - config.pad_before), 3),
                "end": round(end + config.pad_after, 3),
                "text": token,
                "reason": f"filler:{token}",
                "class": classification,
                "confidence": round(confidence, 4),
                "source": source,
                "word_start": round(start, 3),
                "word_end": round(end, 3),
            }
        )
    return accepted, review


def find_long_pauses(words: list[dict], *, config: CleanerConfig) -> list[dict]:
    cuts: list[dict] = []
    ordered = sorted(words, key=lambda item: float(item["start"]))
    half_keep = config.keep_pause / 2
    for previous, following in zip(ordered, ordered[1:]):
        gap_start = float(previous["end"])
        gap_end = float(following["start"])
        if gap_end - gap_start > config.long_pause_threshold:
            cuts.append(
                {
                    "start": round(gap_start + half_keep, 3),
                    "end": round(gap_end - half_keep, 3),
                    "text": "",
                    "reason": "long_pause",
                    "class": "B",
                    "confidence": 1.0,
                    "source": "pause_detector",
                }
            )
    return cuts


def merge_cuts(cuts: Iterable[dict], *, gap: float = 0.08) -> list[dict]:
    ordered = sorted(
        ({**cut, "start": float(cut["start"]), "end": float(cut["end"])} for cut in cuts),
        key=lambda item: (item["start"], item["end"]),
    )
    merged: list[dict] = []
    for cut in ordered:
        if cut["end"] <= cut["start"]:
            continue
        cut.setdefault("confidence", 1.0)
        if not merged or cut["start"] > merged[-1]["end"] + gap:
            merged.append(cut)
            continue
        current = merged[-1]
        current["end"] = max(float(current["end"]), float(cut["end"]))
        current["confidence"] = min(float(current.get("confidence", 1.0)), float(cut["confidence"]))
        reasons = sorted(set(str(current["reason"]).split("+")) | set(str(cut["reason"]).split("+")))
        current["reason"] = "+".join(reasons)
    return [
        {
            **cut,
            "start": round(float(cut["start"]), 3),
            "end": round(float(cut["end"]), 3),
            "confidence": round(float(cut.get("confidence", 1.0)), 4),
        }
        for cut in merged
    ]


def invert_cuts(cuts: Iterable[dict], *, duration: float, min_keep: float = 0.05) -> list[tuple[float, float]]:
    keep: list[tuple[float, float]] = []
    cursor = 0.0
    for cut in sorted(cuts, key=lambda item: float(item["start"])):
        start = max(0.0, min(duration, float(cut["start"])))
        end = max(start, min(duration, float(cut["end"])))
        if start - cursor >= min_keep:
            keep.append((cursor, start))
        cursor = max(cursor, end)
    if duration - cursor >= min_keep:
        keep.append((cursor, duration))
    return keep


def subtitle_text(word: dict) -> str:
    return str(word.get("text", word.get("word", ""))).strip()


def map_words_after_cuts(words: Iterable[dict], cuts: list[dict], *, duration: float) -> list[dict]:
    keep_intervals = invert_cuts(cuts, duration=duration) if cuts else [(0.0, duration)]
    mapped: list[dict] = []
    output_cursor = 0.0
    for keep_start, keep_end in keep_intervals:
        for word in words:
            text = subtitle_text(word)
            if not text:
                continue
            start = float(word["start"])
            end = float(word["end"])
            midpoint = (start + end) / 2
            if not (keep_start <= midpoint < keep_end):
                continue
            mapped_start = output_cursor + max(start, keep_start) - keep_start
            mapped_end = output_cursor + min(end, keep_end) - keep_start
            if mapped_end <= mapped_start:
                continue
            mapped.append(
                {
                    "text": text,
                    "start": round(mapped_start, 3),
                    "end": round(mapped_end, 3),
                }
            )
        output_cursor += keep_end - keep_start
    return mapped


def format_srt_time(seconds: float) -> str:
    total_ms = max(0, int(round(seconds * 1000)))
    hours, remainder = divmod(total_ms, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    secs, millis = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def srt_from_words(
    words: Iterable[dict], *, max_chars: int = 18, max_gap: float = 0.8, max_duration: float = 4.0
) -> str:
    cues: list[dict] = []
    current: dict | None = None
    for word in words:
        text = subtitle_text(word)
        if not text:
            continue
        start = float(word["start"])
        end = float(word["end"])
        if end <= start:
            continue
        if current is None:
            current = {"start": start, "end": end, "texts": [text]}
            continue
        gap = start - float(current["end"])
        joined = "".join(current["texts"] + [text])
        duration = end - float(current["start"])
        if gap > max_gap or len(joined) > max_chars or duration > max_duration:
            cues.append(current)
            current = {"start": start, "end": end, "texts": [text]}
            continue
        current["end"] = end
        current["texts"].append(text)
    if current is not None:
        cues.append(current)

    blocks = []
    for index, cue in enumerate(cues, start=1):
        text = "".join(cue["texts"])
        blocks.append(
            f"{index}\n"
            f"{format_srt_time(float(cue['start']))} --> {format_srt_time(float(cue['end']))}\n"
            f"{text}"
        )
    return "\n\n".join(blocks) + ("\n" if blocks else "")


def write_srt(path: Path, words: Iterable[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(srt_from_words(words), encoding="utf-8")


def build_filter_complex(keep_intervals: list[tuple[float, float]], *, fade: float) -> str:
    if not keep_intervals:
        raise ValueError("at least one keep interval is required")
    filters: list[str] = []
    concat_inputs: list[str] = []
    for index, (start, end) in enumerate(keep_intervals):
        duration = end - start
        fade_duration = min(fade, duration / 4)
        fade_out_start = max(0.0, duration - fade_duration)
        filters.append(
            f"[0:v]trim=start={start:.3f}:end={end:.3f},setpts=PTS-STARTPTS[v{index}]"
        )
        filters.append(
            f"[0:a]atrim=start={start:.3f}:end={end:.3f},"
            f"asetpts=PTS-STARTPTS,"
            f"afade=t=in:st=0:d={fade_duration:.3f},"
            f"afade=t=out:st={fade_out_start:.3f}:d={fade_duration:.3f}[a{index}]"
        )
        concat_inputs.append(f"[v{index}][a{index}]")
    filters.append("".join(concat_inputs) + f"concat=n={len(keep_intervals)}:v=1:a=1[vout][aout]")
    return ";".join(filters)


def render(media: Path, output: Path, cuts: list[dict], *, duration: float, config: CleanerConfig) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    if not cuts and config.copy_when_no_cuts:
        shutil.copy2(media, output)
        return
    keep = invert_cuts(cuts, duration=duration) if cuts else [(0.0, duration)]
    filter_graph = build_filter_complex(keep, fade=config.fade)
    run(
        [
            "ffmpeg",
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(media),
            "-filter_complex",
            filter_graph,
            "-map",
            "[vout]",
            "-map",
            "[aout]",
            "-c:v",
            "libx264",
            "-preset",
            "medium",
            "-crf",
            "18",
            "-pix_fmt",
            "yuv420p",
            "-r",
            "30",
            "-c:a",
            "aac",
            "-b:a",
            "160k",
            "-ac",
            "1",
            "-movflags",
            "+faststart",
            str(output),
        ]
    )


def transcribe_primary(media: Path, output: Path, *, model_name: str) -> dict:
    import mlx_whisper

    result = mlx_whisper.transcribe(
        str(media),
        path_or_hf_repo=model_name,
        language="zh",
        word_timestamps=True,
        condition_on_previous_text=False,
        initial_prompt=PROMPT,
        verbose=False,
        hallucination_silence_threshold=1.0,
    )
    write_json(output, result)
    return result


class SecondaryTranscriber:
    def __init__(self, model_name: str, *, whisper_module=None) -> None:
        self.model_name = model_name
        self._whisper = whisper_module
        self._model = None

    @property
    def whisper(self):
        if self._whisper is None:
            import whisper_timestamped as whisper

            self._whisper = whisper
        return self._whisper

    @property
    def model(self):
        if self._model is None:
            self._model = self.whisper.load_model(self.model_name, device="cpu")
        return self._model

    def transcribe(self, media: Path, output: Path) -> dict:
        audio = self.whisper.load_audio(str(media))
        result = self.whisper.transcribe(
            self.model,
            audio,
            language="zh",
            detect_disfluencies=True,
            condition_on_previous_text=False,
            initial_prompt=PROMPT,
            beam_size=5,
            best_of=5,
            temperature=0.0,
            fp16=False,
            verbose=False,
        )
        write_json(output, result)
        return result


def transcribe_secondary(media: Path, output: Path, *, model_name: str) -> dict:
    return SecondaryTranscriber(model_name).transcribe(media, output)


def find_residual_fillers(transcript: dict) -> list[dict]:
    residual: list[dict] = []
    for word in flatten_words(transcript):
        token = word_text(word)
        if token in FILLER_A or token in FILLER_B:
            residual.append(
                {
                    "token": token,
                    "start": round(float(word["start"]), 3),
                    "end": round(float(word["end"]), 3),
                    "raw": str(word.get("word", word.get("text", ""))).strip(),
                }
            )
    return residual


def plan_residual_refine_cuts(
    residual: list[dict], *, config: CleanerConfig, round_index: int
) -> tuple[list[dict], list[dict]]:
    cuts: list[dict] = []
    review: list[dict] = []
    source = f"verification_round_{round_index}"
    for item in residual:
        token = clean_token(item["token"])
        if token in FILLER_B:
            review.append(
                {
                    "start": round(float(item["start"]), 3),
                    "end": round(float(item["end"]), 3),
                    "text": token,
                    "reason": f"residual_review_token:{token}",
                    "confidence": 1.0,
                    "source": source,
                }
            )
            continue
        if token not in FILLER_A:
            continue
        cuts.append(
            {
                "word": token,
                "start": float(item["start"]),
                "end": float(item["end"]),
                "confidence": 1.0,
            }
        )
    accepted, accepted_review = build_cut_candidates(cuts, config=config, source=source)
    return merge_cuts(accepted, gap=config.merge_gap), review + accepted_review


def decide_cuts(primary: dict | None, secondary: dict, *, config: CleanerConfig) -> tuple[list[dict], list[dict]]:
    candidates: list[dict] = []
    review: list[dict] = []
    primary_words = flatten_words(primary or {})
    secondary_words = flatten_words(secondary)

    for source, words in [("primary", primary_words), ("secondary_disfluency", secondary_words)]:
        accepted, local_review = build_cut_candidates(words, config=config, source=source)
        candidates.extend(accepted)
        review.extend(local_review)

    pause_words = primary_words or secondary_words
    candidates.extend(find_long_pauses(pause_words, config=config))
    return merge_cuts(candidates, gap=config.merge_gap), review


def process_one(
    media: Path,
    *,
    dirs: dict[str, Path],
    config: CleanerConfig,
    primary_model: str,
    secondary_model: str,
    secondary_transcriber: SecondaryTranscriber,
    skip_primary: bool,
    max_refine_rounds: int,
    hash_sources: bool,
    redact_paths: bool,
    write_srt_file: bool,
) -> dict:
    stem = media.stem
    start_time = time.time()
    source_record = source_record_from_stat(
        media, include_hash=hash_sources, redact_paths=redact_paths
    )
    duration = media_duration(media)

    primary = None
    if not skip_primary:
        try:
            primary = transcribe_primary(
                media, dirs["analysis"] / f"{stem}_primary.json", model_name=primary_model
            )
        except Exception as exc:
            primary = None
            write_json(
                dirs["analysis"] / f"{stem}_primary_error.json",
                {"error": str(exc), "fallback": "secondary_only"},
            )

    secondary = secondary_transcriber.transcribe(media, dirs["analysis"] / f"{stem}_secondary_disfluency.json")
    cuts, review = decide_cuts(primary, secondary, config=config)
    subtitle_words = (
        map_words_after_cuts(flatten_words(secondary), cuts, duration=duration) if write_srt_file else []
    )

    current_input = media
    current_duration = duration
    current_cuts = cuts
    output = dirs["final"] / output_name_for(media, mode=config.mode)
    render(current_input, output, current_cuts, duration=current_duration, config=config)
    rounds: list[dict] = [
        {
            "round": 0,
            "input": redact_path(current_input, redact=redact_paths),
            "output": redact_path(output, redact=redact_paths),
            "cuts": current_cuts,
            "review_only": review,
        }
    ]

    for round_index in range(1, max_refine_rounds + 1):
        verification_path = dirs["verification"] / f"{stem}_round{round_index}_verification.json"
        verification = secondary_transcriber.transcribe(output, verification_path)
        residual = find_residual_fillers(verification)
        if not residual:
            rounds.append(
                {
                    "round": round_index,
                    "input": redact_path(output, redact=redact_paths),
                    "output": redact_path(output, redact=redact_paths),
                    "residual": [],
                    "cuts": [],
                }
            )
            break

        residual_cuts, residual_review = plan_residual_refine_cuts(
            residual, config=config, round_index=round_index
        )
        refined_output = dirs["final"] / f"{media.stem}_roughcut_{config.mode}_r{round_index}.mp4"
        current_duration = media_duration(output)
        render(output, refined_output, residual_cuts, duration=current_duration, config=config)
        if write_srt_file:
            subtitle_words = map_words_after_cuts(
                subtitle_words, residual_cuts, duration=current_duration
            )
        rounds.append(
            {
                "round": round_index,
                "input": redact_path(output, redact=redact_paths),
                "output": redact_path(refined_output, redact=redact_paths),
                "residual": residual,
                "cuts": residual_cuts,
                "review_only": residual_review,
            }
        )
        output = refined_output

    subtitle_output = None
    if write_srt_file:
        subtitle_output = dirs["subtitles"] / f"{output.stem}.srt"
        write_srt(subtitle_output, subtitle_words)

    final_probe = redact_probe_paths(probe(output), redact=redact_paths)
    output_duration = float(final_probe["format"]["duration"])
    manifest = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source": redact_path(media, redact=redact_paths),
        "final_output": redact_path(output, redact=redact_paths),
        "subtitle_output": (
            redact_path(subtitle_output, redact=redact_paths) if subtitle_output else None
        ),
        "mode": config.mode,
        "config": asdict(config),
        "primary_model": None if skip_primary else primary_model,
        "secondary_model": secondary_model,
        "input_duration": round(duration, 3),
        "output_duration": round(output_duration, 3),
        "removed_duration": round(duration - output_duration, 3),
        "source_record": source_record,
        "rounds": rounds,
        "probe": final_probe,
        "elapsed_seconds": round(time.time() - start_time, 3),
    }
    write_json(dirs["manifests"] / f"{stem}_manifest.json", manifest)
    return manifest


def scan_input(input_dir: Path) -> list[Path]:
    return sorted(
        path for path in input_dir.iterdir() if path.is_file() and path.suffix.lower() == ".mp4"
    )


def write_report(output: Path, manifests: list[dict], *, dry_run: bool = False) -> None:
    lines = [
        "# 本地口播清理报告",
        "",
        f"生成时间：{datetime.now().isoformat(timespec='seconds')}",
        f"dry_run：{dry_run}",
        "",
        "## 汇总",
        "",
        "| 文件 | 输入时长 | 输出时长 | 删除时长 | 输出 |",
        "| --- | ---: | ---: | ---: | --- |",
    ]
    for manifest in manifests:
        lines.append(
            "| {name} | {input_duration:.3f}s | {output_duration:.3f}s | {removed_duration:.3f}s | `{out}` |".format(
                name=Path(manifest["source"]).name,
                input_duration=float(manifest.get("input_duration", 0.0)),
                output_duration=float(manifest.get("output_duration", 0.0)),
                removed_duration=float(manifest.get("removed_duration", 0.0)),
                out=manifest.get("final_output", ""),
            )
        )
    lines.append("")
    lines.append("## 说明")
    lines.append("")
    lines.append("- AI 负责转写、词级时间戳和复核。")
    lines.append("- 脚本负责生成切点、调用 FFmpeg 裁剪、输出 manifest。")
    lines.append("- 低置信或半语义片段进入 review-only，不默认删除。")
    (output / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def dry_run_project(
    input_dir: Path,
    output: Path,
    dirs: dict[str, Path],
    *,
    mode: str,
    hash_sources: bool,
    redact_paths: bool,
) -> list[dict]:
    media_files = scan_input(input_dir)
    manifests = []
    for media in media_files:
        final_output = dirs["final"] / output_name_for(media, mode=mode)
        record = source_record_from_stat(
            media, include_hash=hash_sources, redact_paths=redact_paths
        )
        manifest = {
            "created_at": datetime.now(timezone.utc).isoformat(),
            "source": redact_path(media, redact=redact_paths),
            "final_output": redact_path(final_output, redact=redact_paths),
            "mode": mode,
            "input_duration": 0.0,
            "output_duration": 0.0,
            "removed_duration": 0.0,
            "source_record": record,
            "rounds": [],
            "dry_run": True,
        }
        write_json(dirs["manifests"] / f"{media.stem}_manifest.json", manifest)
        manifests.append(manifest)
    write_report(output, manifests, dry_run=True)
    return manifests


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    validate_args(args)
    if not args.input.is_dir():
        raise SystemExit(f"input directory not found: {args.input}")
    args.output.mkdir(parents=True, exist_ok=True)
    dirs = build_project_dirs(args.output)
    config = CleanerConfig(
        mode=args.mode,
        keep_pause=args.keep_pause,
        fade=args.fade_ms / 1000,
        copy_when_no_cuts=args.copy_when_no_cuts,
    )

    if args.dry_run:
        manifests = dry_run_project(
            args.input,
            args.output,
            dirs,
            mode=args.mode,
            hash_sources=args.hash_sources,
            redact_paths=args.redact_paths,
        )
        print(f"dry-run created project at {args.output} for {len(manifests)} mp4 files")
        return 0

    media_files = scan_input(args.input)
    if not media_files:
        print(f"no mp4 files found in {args.input}")
        return 0

    manifests: list[dict] = []
    secondary_transcriber = SecondaryTranscriber(args.secondary_model)
    for media in media_files:
        final_path = dirs["final"] / output_name_for(media, mode=args.mode)
        if args.skip_existing and final_path.exists():
            print(f"skip existing: {media.name}")
            continue
        print(f"processing: {media.name}")
        manifest = process_one(
            media,
            dirs=dirs,
            config=config,
            primary_model=args.primary_model,
            secondary_model=args.secondary_model,
            secondary_transcriber=secondary_transcriber,
            skip_primary=args.skip_primary,
            max_refine_rounds=args.max_refine_rounds,
            hash_sources=args.hash_sources,
            redact_paths=args.redact_paths,
        )
        manifests.append(manifest)
        print(
            f"done: {media.name} -> {Path(manifest['final_output']).name}, "
            f"removed {manifest['removed_duration']:.3f}s"
        )
    write_report(args.output, manifests, dry_run=False)
    print(f"report: {args.output / 'report.md'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
