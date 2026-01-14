"""
Video encoder module.

Renders mixed timeline to final video output using moviepy.
"""

import os
from pathlib import Path
from typing import Optional

from ..shared.logger import get_logger
from ..shared.config import get_config
from ..composer.mixer import MixedTimeline, MixedClip


logger = get_logger(__name__)


class VideoEncoder:
    """
    Video encoder using moviepy.

    Features:
    - Image-to-video conversion
    - Audio mixing (narration + BGM)
    - Ken Burns effects
    - Transition effects
    - Subtitle burning
    """

    def __init__(
        self,
        fps: int = 30,
        codec: str = "libx264",
        audio_codec: str = "aac",
        preset: str = "medium"
    ):
        self.fps = fps
        self.codec = codec
        self.audio_codec = audio_codec
        self.preset = preset
        self.config = get_config()

    def render(
        self,
        mixed_timeline: MixedTimeline,
        output_path: str,
        subtitle_path: Optional[str] = None,
        progress_callback: Optional[callable] = None
    ) -> str:
        """
        Render mixed timeline to video file.

        Args:
            mixed_timeline: Timeline to render
            output_path: Output video path
            subtitle_path: Optional subtitle file (SRT/ASS)
            progress_callback: Optional callback for progress updates

        Returns:
            Path to rendered video
        """
        try:
            from moviepy.editor import (
                ImageClip, AudioFileClip, CompositeVideoClip,
                concatenate_videoclips, CompositeAudioClip
            )
        except ImportError:
            raise RuntimeError("moviepy not installed. Run: pip install moviepy")

        logger.info(f"Starting render: {len(mixed_timeline.clips)} clips")

        # Build video clips
        video_clips = []
        for i, clip in enumerate(mixed_timeline.clips):
            try:
                video_clip = self._create_video_clip(clip, mixed_timeline)
                video_clips.append(video_clip)

                if progress_callback:
                    progress_callback(i + 1, len(mixed_timeline.clips), "building")

            except Exception as e:
                logger.error(f"Failed to create clip {clip.shot_id}: {e}")
                raise

        # Concatenate clips
        logger.info("Concatenating clips...")
        final_video = concatenate_videoclips(video_clips, method="compose")

        # Add global BGM
        if mixed_timeline.global_bgm_path:
            final_video = self._add_bgm(
                final_video,
                mixed_timeline.global_bgm_path,
                mixed_timeline.global_bgm_volume
            )

        # Burn subtitles if provided
        if subtitle_path and Path(subtitle_path).exists():
            final_video = self._burn_subtitles(final_video, subtitle_path)

        # Ensure output directory exists
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)

        # Write output
        logger.info(f"Encoding to {output_path}...")
        final_video.write_videofile(
            output_path,
            fps=self.fps,
            codec=self.codec,
            audio_codec=self.audio_codec,
            preset=self.preset,
            threads=4,
            logger=None  # Suppress moviepy's verbose output
        )

        # Cleanup
        final_video.close()
        for clip in video_clips:
            clip.close()

        logger.info(f"Render complete: {output_path}")
        return output_path

    def _create_video_clip(self, clip: MixedClip, timeline: MixedTimeline):
        """Create video clip from mixed clip"""
        from moviepy.editor import ImageClip, AudioFileClip, CompositeAudioClip

        # Create base video from image
        if clip.image_path and Path(clip.image_path).exists():
            video = ImageClip(clip.image_path).set_duration(clip.duration)
            video = video.resize((timeline.width, timeline.height))
        else:
            # Fallback to black frame
            from moviepy.editor import ColorClip
            video = ColorClip(
                size=(timeline.width, timeline.height),
                color=(0, 0, 0)
            ).set_duration(clip.duration)

        # Apply Ken Burns effect
        if clip.ken_burns:
            video = self._apply_ken_burns(video, clip.ken_burns)

        # Build audio tracks
        audio_clips = []

        # Narration
        if clip.narration_path and Path(clip.narration_path).exists():
            narration = AudioFileClip(clip.narration_path)
            narration = narration.volumex(clip.narration_volume)
            audio_clips.append(narration)

        # Sound effects
        for sfx_path in clip.sfx_paths:
            if Path(sfx_path).exists():
                sfx = AudioFileClip(sfx_path)
                sfx = sfx.volumex(clip.sfx_volume)
                audio_clips.append(sfx)

        # Combine audio
        if audio_clips:
            combined_audio = CompositeAudioClip(audio_clips)
            video = video.set_audio(combined_audio)

        return video

    def _apply_ken_burns(self, clip, params: dict):
        """Apply Ken Burns (pan/zoom) effect to clip"""
        start_scale = params.get("start_scale", 1.0)
        end_scale = params.get("end_scale", 1.0)
        start_x = params.get("start_x", 0.5)
        start_y = params.get("start_y", 0.5)
        end_x = params.get("end_x", 0.5)
        end_y = params.get("end_y", 0.5)

        def make_frame(get_frame, t):
            """Apply zoom and pan at time t"""
            progress = t / clip.duration if clip.duration > 0 else 0

            # Interpolate scale and position
            scale = start_scale + (end_scale - start_scale) * progress
            center_x = start_x + (end_x - start_x) * progress
            center_y = start_y + (end_y - start_y) * progress

            # Get original frame
            frame = get_frame(t)

            # Apply transformation
            from PIL import Image
            import numpy as np

            img = Image.fromarray(frame)
            w, h = img.size

            # Calculate crop region
            new_w = int(w / scale)
            new_h = int(h / scale)
            left = int((w - new_w) * center_x)
            top = int((h - new_h) * center_y)

            # Crop and resize
            cropped = img.crop((left, top, left + new_w, top + new_h))
            resized = cropped.resize((w, h), Image.LANCZOS)

            return np.array(resized)

        return clip.fl(make_frame)

    def _add_bgm(self, video, bgm_path: str, volume: float):
        """Add background music to video"""
        from moviepy.editor import AudioFileClip, CompositeAudioClip

        bgm = AudioFileClip(bgm_path)

        # Loop BGM if shorter than video
        if bgm.duration < video.duration:
            from moviepy.editor import afx
            loops = int(video.duration / bgm.duration) + 1
            bgm = afx.audio_loop(bgm, nloops=loops)

        # Trim to video duration
        bgm = bgm.subclip(0, video.duration)
        bgm = bgm.volumex(volume)

        # Mix with existing audio
        if video.audio:
            combined = CompositeAudioClip([video.audio, bgm])
            video = video.set_audio(combined)
        else:
            video = video.set_audio(bgm)

        return video

    def _burn_subtitles(self, video, subtitle_path: str):
        """Burn subtitles into video"""
        # Use ffmpeg for subtitle burning (more reliable than moviepy)
        logger.warning("Subtitle burning not yet implemented in Python. Use ffmpeg post-process.")
        return video

    def render_preview(
        self,
        mixed_timeline: MixedTimeline,
        output_path: str,
        max_duration: float = 30.0
    ) -> str:
        """
        Render a quick preview (first N seconds).

        Args:
            mixed_timeline: Timeline to preview
            output_path: Output path
            max_duration: Maximum preview duration

        Returns:
            Path to preview video
        """
        # Create trimmed timeline
        preview_clips = []
        current_duration = 0.0

        for clip in mixed_timeline.clips:
            if current_duration >= max_duration:
                break
            preview_clips.append(clip)
            current_duration += clip.duration

        preview_timeline = MixedTimeline(
            clips=preview_clips,
            total_duration=min(current_duration, max_duration),
            fps=mixed_timeline.fps,
            width=mixed_timeline.width,
            height=mixed_timeline.height,
            global_bgm_path=mixed_timeline.global_bgm_path,
            global_bgm_volume=mixed_timeline.global_bgm_volume
        )

        return self.render(preview_timeline, output_path)


def burn_subtitles_ffmpeg(
    input_video: str,
    subtitle_path: str,
    output_path: str
) -> str:
    """
    Burn subtitles using ffmpeg (post-process).

    Args:
        input_video: Input video path
        subtitle_path: Subtitle file path (SRT/ASS)
        output_path: Output video path

    Returns:
        Path to output video
    """
    import subprocess

    cmd = [
        "ffmpeg", "-y",
        "-i", input_video,
        "-vf", f"subtitles={subtitle_path}",
        "-c:a", "copy",
        output_path
    ]

    logger.info(f"Burning subtitles: {subtitle_path}")
    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        logger.error(f"ffmpeg failed: {result.stderr}")
        raise RuntimeError(f"Subtitle burning failed: {result.stderr}")

    return output_path
