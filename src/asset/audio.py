"""
Audio generation for shots.

Handles:
- TTS generation (edge-tts, GPT-SoVITS)
- Audio padding for natural rhythm
- Audio metadata extraction
"""

import asyncio
from pathlib import Path
from typing import Optional

from ..shared.logger import get_logger
from ..shared.config import get_config
from ..shared.models import Shot
from ..shared.exceptions import AudioError
from .version import get_asset_path


logger = get_logger(__name__)


def _get_audio_segment():
    """Lazy import AudioSegment to avoid import errors on Python 3.13+"""
    try:
        from pydub import AudioSegment
        return AudioSegment
    except ImportError as e:
        logger.warning(f"pydub import failed: {e}. Audio processing may be limited.")
        return None


class AudioGenerator:
    """
    TTS audio generator.

    Supports:
    - edge-tts: Free Microsoft TTS (default)
    - GPT-SoVITS: Custom voice cloning (optional)

    Implements Audio First principle:
    - Generate audio first
    - Get precise duration
    - Use for video timing
    """

    def __init__(
        self,
        project_id: str,
        output_dir: str = "storage/projects"
    ):
        self.project_id = project_id
        self.output_dir = output_dir
        self.config = get_config()
        self._edge_tts_voice = self.config.tts.voice or "zh-CN-XiaoxiaoNeural"

    def generate_shot_audio(
        self,
        shot: Shot,
        padding_before_ms: int = 200,
        padding_after_ms: int = 300
    ) -> dict:
        """
        Generate TTS audio for a shot.

        Args:
            shot: Shot with narration text
            padding_before_ms: Silence before audio
            padding_after_ms: Silence after audio

        Returns:
            Dict with audio path and duration info
        """
        if not shot.narration:
            return {
                "shot_id": shot.shot_id,
                "has_audio": False,
                "duration": shot.duration
            }

        # Get output path
        output_path = get_asset_path(
            self.project_id,
            shot.shot_id,
            "audio",
            "wav",
            base_dir=self.output_dir
        )

        # Generate TTS
        raw_path = output_path.replace(".wav", "_raw.wav")
        self._generate_tts(shot.narration, raw_path)

        # Add padding
        padded_path, duration = self._add_padding(
            raw_path,
            output_path,
            padding_before_ms,
            padding_after_ms
        )

        # Get raw duration
        AudioSegment = _get_audio_segment()
        if AudioSegment:
            raw_audio = AudioSegment.from_file(raw_path)
            raw_duration = len(raw_audio) / 1000.0
        else:
            raw_duration = duration - (padding_before_ms + padding_after_ms) / 1000.0

        return {
            "shot_id": shot.shot_id,
            "has_audio": True,
            "audio_path": padded_path,
            "raw_path": raw_path,
            "raw_duration": raw_duration,
            "padded_duration": duration,
            "padding_before_ms": padding_before_ms,
            "padding_after_ms": padding_after_ms
        }

    def generate_batch(
        self,
        shots: list[Shot],
        padding_before_ms: int = 200,
        padding_after_ms: int = 300
    ) -> list[dict]:
        """
        Generate audio for multiple shots.

        Args:
            shots: List of shots
            padding_before_ms: Silence before each audio
            padding_after_ms: Silence after each audio

        Returns:
            List of audio generation results
        """
        results = []

        for shot in shots:
            try:
                result = self.generate_shot_audio(
                    shot,
                    padding_before_ms,
                    padding_after_ms
                )
                results.append(result)

                if result["has_audio"]:
                    logger.info(
                        f"Shot {shot.shot_id} audio: {result['padded_duration']:.2f}s"
                    )

            except Exception as e:
                logger.error(f"Shot {shot.shot_id} audio failed: {e}")
                results.append({
                    "shot_id": shot.shot_id,
                    "has_audio": False,
                    "error": str(e)
                })

        return results

    def _generate_tts(self, text: str, output_path: str) -> None:
        """Generate TTS audio using edge-tts"""
        try:
            import edge_tts
        except ImportError:
            raise AudioError("edge-tts not installed. Run: pip install edge-tts")

        async def _async_tts():
            communicate = edge_tts.Communicate(text, self._edge_tts_voice)
            await communicate.save(output_path)

        # Ensure output directory exists
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)

        # Run async TTS
        asyncio.run(_async_tts())
        logger.debug(f"TTS generated: {output_path}")

    def _add_padding(
        self,
        input_path: str,
        output_path: str,
        padding_before_ms: int,
        padding_after_ms: int
    ) -> tuple[str, float]:
        """Add silence padding to audio"""
        AudioSegment = _get_audio_segment()
        if not AudioSegment:
            # Fallback: just copy the file without padding
            import shutil
            shutil.copy(input_path, output_path)
            # Estimate duration from file size (rough)
            return output_path, 5.0  # Default duration

        audio = AudioSegment.from_file(input_path)

        silence_before = AudioSegment.silent(duration=padding_before_ms)
        silence_after = AudioSegment.silent(duration=padding_after_ms)

        padded = silence_before + audio + silence_after

        # Ensure output directory exists
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        padded.export(output_path, format="wav")

        duration = len(padded) / 1000.0
        return output_path, duration

    def get_audio_duration(self, audio_path: str) -> float:
        """Get duration of an audio file in seconds"""
        AudioSegment = _get_audio_segment()
        if not AudioSegment:
            return 5.0  # Default fallback
        audio = AudioSegment.from_file(audio_path)
        return len(audio) / 1000.0

    def concatenate_audio(
        self,
        audio_paths: list[str],
        output_path: str,
        crossfade_ms: int = 0
    ) -> str:
        """
        Concatenate multiple audio files.

        Args:
            audio_paths: List of audio file paths
            output_path: Output file path
            crossfade_ms: Optional crossfade duration

        Returns:
            Path to concatenated audio
        """
        if not audio_paths:
            raise AudioError("No audio files to concatenate")

        AudioSegment = _get_audio_segment()
        if not AudioSegment:
            raise AudioError("pydub not available for audio concatenation")

        combined = AudioSegment.from_file(audio_paths[0])

        for path in audio_paths[1:]:
            next_audio = AudioSegment.from_file(path)
            if crossfade_ms > 0:
                combined = combined.append(next_audio, crossfade=crossfade_ms)
            else:
                combined = combined + next_audio

        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        combined.export(output_path, format="wav")

        logger.info(f"Concatenated audio: {output_path} ({len(combined)/1000:.2f}s)")
        return output_path


class GPTSoVITSClient:
    """
    GPT-SoVITS TTS client (optional).

    For custom voice cloning with emotion control.
    Requires GPT-SoVITS server running.
    """

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 9880
    ):
        self.base_url = f"http://{host}:{port}"

    def is_available(self) -> bool:
        """Check if GPT-SoVITS server is running"""
        try:
            from urllib.request import urlopen
            response = urlopen(f"{self.base_url}/", timeout=5)
            return response.status == 200
        except Exception:
            return False

    def generate(
        self,
        text: str,
        output_path: str,
        reference_audio: Optional[str] = None,
        emotion: Optional[str] = None
    ) -> str:
        """
        Generate TTS with GPT-SoVITS.

        Args:
            text: Text to synthesize
            output_path: Output audio path
            reference_audio: Reference audio for voice cloning
            emotion: Emotion tag (happy, sad, etc.)

        Returns:
            Path to generated audio
        """
        import json
        from urllib.request import Request, urlopen

        payload = {
            "text": text,
            "text_language": "zh"
        }

        if reference_audio:
            payload["ref_audio_path"] = reference_audio

        if emotion:
            payload["emotion"] = emotion

        req = Request(
            f"{self.base_url}/tts",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST"
        )

        response = urlopen(req, timeout=60)
        audio_data = response.read()

        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        Path(output_path).write_bytes(audio_data)

        return output_path
