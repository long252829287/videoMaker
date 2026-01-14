"""
Duration strategy for audio-video alignment.

Implements the "Audio First" principle:
1. Generate TTS audio first
2. Get precise duration
3. Decide video handling strategy
"""

import math
from typing import Optional

from ..shared.logger import get_logger
from ..shared.models import DurationStrategy, VideoStrategy


logger = get_logger(__name__)


def _get_audio_segment():
    """Lazy import AudioSegment to avoid import errors on Python 3.13+"""
    try:
        from pydub import AudioSegment
        return AudioSegment
    except ImportError as e:
        logger.warning(f"pydub import failed: {e}. Audio processing may be limited.")
        return None


# Default configuration
DEFAULT_CONFIG = {
    "video_longer": DurationStrategy.TRUNCATE,
    "audio_longer": DurationStrategy.LOOP,
    "max_speed_factor": 1.3,
    "min_speed_factor": 0.8,
    "padding_before_ms": 200,
    "padding_after_ms": 300,
}


def process_audio_with_padding(
    audio_path: str,
    padding_before_ms: int = 200,
    padding_after_ms: int = 300,
    output_path: Optional[str] = None
) -> tuple[str, float]:
    """
    Add silence padding to audio for natural "breathing" between shots.

    Args:
        audio_path: Path to input audio file
        padding_before_ms: Silence duration before audio (ms)
        padding_after_ms: Silence duration after audio (ms)
        output_path: Output path (defaults to {input}_padded.wav)

    Returns:
        Tuple of (output_path, total_duration_seconds)
    """
    AudioSegment = _get_audio_segment()
    if not AudioSegment:
        # Fallback: return input path with estimated duration
        if output_path is None:
            base = audio_path.rsplit(".", 1)[0]
            output_path = f"{base}_padded.wav"
        import shutil
        shutil.copy(audio_path, output_path)
        return output_path, 5.0  # Default estimate

    audio = AudioSegment.from_file(audio_path)

    silence_before = AudioSegment.silent(duration=padding_before_ms)
    silence_after = AudioSegment.silent(duration=padding_after_ms)

    # Add padding
    padded_audio = silence_before + audio + silence_after

    # Determine output path
    if output_path is None:
        base = audio_path.rsplit(".", 1)[0]
        output_path = f"{base}_padded.wav"

    # Export
    padded_audio.export(output_path, format="wav")

    total_duration = len(padded_audio) / 1000.0
    logger.debug(f"Audio padded: {audio_path} -> {output_path} ({total_duration:.2f}s)")

    return output_path, total_duration


def get_audio_duration(audio_path: str) -> float:
    """Get duration of an audio file in seconds"""
    AudioSegment = _get_audio_segment()
    if not AudioSegment:
        return 5.0  # Default fallback
    audio = AudioSegment.from_file(audio_path)
    return len(audio) / 1000.0


def calculate_video_strategy(
    audio_duration: float,
    video_duration: float,
    config: dict = None
) -> VideoStrategy:
    """
    Calculate how to handle video based on audio duration.

    This is the core of the "Audio First" principle:
    - Audio is the source of truth for timing
    - Video is adjusted to match audio

    Args:
        audio_duration: Duration of audio (with padding) in seconds
        video_duration: Duration of generated video in seconds
        config: Strategy configuration

    Returns:
        VideoStrategy with handling instructions
    """
    config = {**DEFAULT_CONFIG, **(config or {})}

    if audio_duration <= video_duration:
        # Audio shorter than video
        ratio = video_duration / audio_duration

        if ratio <= config["max_speed_factor"]:
            # Speed up video to match audio
            return VideoStrategy(
                strategy=DurationStrategy.SPEED_UP,
                speed_factor=ratio,
                total_video_duration=audio_duration
            )
        else:
            # Truncate video
            return VideoStrategy(
                strategy=DurationStrategy.TRUNCATE,
                end_time=audio_duration,
                total_video_duration=audio_duration
            )
    else:
        # Audio longer than video - need to extend video
        loop_count = math.ceil(audio_duration / video_duration)

        return VideoStrategy(
            strategy=DurationStrategy.LOOP,
            loop_count=loop_count,
            total_video_duration=audio_duration
        )


def process_shot_timing(
    audio_path: str,
    video_duration: float,
    config: dict = None
) -> dict:
    """
    Complete timing processing for a single shot.

    Args:
        audio_path: Path to TTS audio
        video_duration: Duration of generated video
        config: Timing configuration

    Returns:
        Dict with all timing information
    """
    config = {**DEFAULT_CONFIG, **(config or {})}

    # Get original duration
    original_duration = get_audio_duration(audio_path)

    # Add padding
    padded_path, padded_duration = process_audio_with_padding(
        audio_path,
        padding_before_ms=config["padding_before_ms"],
        padding_after_ms=config["padding_after_ms"]
    )

    # Calculate video strategy using PADDED duration
    strategy = calculate_video_strategy(
        audio_duration=padded_duration,  # Important: use padded duration
        video_duration=video_duration,
        config=config
    )

    return {
        "original_audio": audio_path,
        "padded_audio": padded_path,
        "original_duration": original_duration,
        "padded_duration": padded_duration,
        "video_duration": video_duration,
        "strategy": strategy.model_dump()
    }
