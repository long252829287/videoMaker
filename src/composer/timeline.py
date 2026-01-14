"""
Timeline composition.

Builds the video timeline from shots, images, and audio,
applying the Audio First principle for timing.
"""

from dataclasses import dataclass, field
from typing import Optional
from pathlib import Path

from ..shared.logger import get_logger
from ..shared.models import Shot, Storyboard, VideoStrategy, DurationStrategy


logger = get_logger(__name__)


@dataclass
class TimelineClip:
    """A single clip in the timeline"""
    shot_id: int
    start_time: float
    end_time: float
    image_path: Optional[str] = None
    audio_path: Optional[str] = None
    video_strategy: Optional[VideoStrategy] = None
    transition_in: Optional[str] = None
    transition_out: Optional[str] = None
    metadata: dict = field(default_factory=dict)

    @property
    def duration(self) -> float:
        return self.end_time - self.start_time


@dataclass
class Timeline:
    """Complete video timeline"""
    clips: list[TimelineClip] = field(default_factory=list)
    total_duration: float = 0.0
    fps: int = 30
    width: int = 1920
    height: int = 1080

    def add_clip(self, clip: TimelineClip) -> None:
        """Add a clip to the timeline"""
        self.clips.append(clip)
        self._recalculate_duration()

    def _recalculate_duration(self) -> None:
        """Recalculate total duration from clips"""
        if self.clips:
            self.total_duration = max(c.end_time for c in self.clips)

    def to_dict(self) -> dict:
        """Export timeline as dictionary"""
        return {
            "total_duration": self.total_duration,
            "fps": self.fps,
            "width": self.width,
            "height": self.height,
            "clips": [
                {
                    "shot_id": c.shot_id,
                    "start_time": c.start_time,
                    "end_time": c.end_time,
                    "duration": c.duration,
                    "image_path": c.image_path,
                    "audio_path": c.audio_path,
                    "video_strategy": c.video_strategy.model_dump() if c.video_strategy else None,
                    "transition_in": c.transition_in,
                    "transition_out": c.transition_out
                }
                for c in self.clips
            ]
        }


class TimelineBuilder:
    """
    Builds timeline from storyboard and generated assets.

    Implements Audio First principle:
    - Audio duration determines clip timing
    - Video/image is adjusted to match
    """

    def __init__(self, fps: int = 30, width: int = 1920, height: int = 1080):
        self.fps = fps
        self.width = width
        self.height = height

    def build_from_assets(
        self,
        shots: list[Shot],
        image_results: list[dict],
        audio_results: list[dict]
    ) -> Timeline:
        """
        Build timeline from generated assets.

        Args:
            shots: Original shot list
            image_results: Image generation results
            audio_results: Audio generation results

        Returns:
            Complete Timeline
        """
        timeline = Timeline(
            fps=self.fps,
            width=self.width,
            height=self.height
        )

        # Build lookup maps
        images = {r["shot_id"]: r for r in image_results if "error" not in r}
        audios = {r["shot_id"]: r for r in audio_results}

        current_time = 0.0

        for shot in shots:
            shot_id = shot.shot_id
            image_info = images.get(shot_id, {})
            audio_info = audios.get(shot_id, {})

            # Determine duration (Audio First)
            if audio_info.get("has_audio"):
                duration = audio_info["padded_duration"]
            else:
                duration = shot.duration

            # Calculate video strategy
            video_strategy = self._calculate_video_strategy(duration, shot)

            clip = TimelineClip(
                shot_id=shot_id,
                start_time=current_time,
                end_time=current_time + duration,
                image_path=image_info.get("image_path"),
                audio_path=audio_info.get("audio_path"),
                video_strategy=video_strategy,
                transition_in=shot.transition.value if shot.transition else None,
                metadata={
                    "shot_type": shot.shot_type.value,
                    "camera_movement": shot.camera_movement.value
                }
            )

            timeline.add_clip(clip)
            current_time += duration

            logger.debug(
                f"Shot {shot_id}: {clip.start_time:.2f}s - {clip.end_time:.2f}s "
                f"({duration:.2f}s)"
            )

        logger.info(f"Timeline built: {len(timeline.clips)} clips, {timeline.total_duration:.2f}s")
        return timeline

    def _calculate_video_strategy(
        self,
        target_duration: float,
        shot: Shot
    ) -> VideoStrategy:
        """
        Calculate how to handle video/image for target duration.

        For Phase 1 (image-based), determines:
        - Static display duration
        - Optional Ken Burns effect parameters
        """
        # For image-based shots, just use target duration
        return VideoStrategy(
            strategy=DurationStrategy.STATIC,
            total_video_duration=target_duration
        )

    def adjust_timing(
        self,
        timeline: Timeline,
        shot_id: int,
        new_duration: float
    ) -> Timeline:
        """
        Adjust timing for a specific shot.

        Recalculates all subsequent clip timings.

        Args:
            timeline: Current timeline
            shot_id: Shot to adjust
            new_duration: New duration for the shot

        Returns:
            Updated Timeline
        """
        # Find the clip
        clip_idx = None
        for i, clip in enumerate(timeline.clips):
            if clip.shot_id == shot_id:
                clip_idx = i
                break

        if clip_idx is None:
            logger.warning(f"Shot {shot_id} not found in timeline")
            return timeline

        # Update clip duration
        old_duration = timeline.clips[clip_idx].duration
        timeline.clips[clip_idx].end_time = (
            timeline.clips[clip_idx].start_time + new_duration
        )

        # Shift all subsequent clips
        time_diff = new_duration - old_duration
        for i in range(clip_idx + 1, len(timeline.clips)):
            timeline.clips[i].start_time += time_diff
            timeline.clips[i].end_time += time_diff

        timeline._recalculate_duration()
        return timeline

    def export_edl(self, timeline: Timeline, output_path: str) -> str:
        """
        Export timeline as EDL (Edit Decision List).

        Basic format for compatibility with video editors.

        Args:
            timeline: Timeline to export
            output_path: Output file path

        Returns:
            Path to EDL file
        """
        lines = [
            "TITLE: Generated Video",
            f"FCM: NON-DROP FRAME",
            ""
        ]

        for i, clip in enumerate(timeline.clips, 1):
            # Convert to timecode (simplified)
            start_tc = self._seconds_to_timecode(clip.start_time, timeline.fps)
            end_tc = self._seconds_to_timecode(clip.end_time, timeline.fps)

            lines.append(f"{i:03d}  AX       V     C        {start_tc} {end_tc} {start_tc} {end_tc}")

            if clip.image_path:
                lines.append(f"* FROM CLIP NAME: {Path(clip.image_path).name}")

            lines.append("")

        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        Path(output_path).write_text("\n".join(lines))

        logger.info(f"EDL exported: {output_path}")
        return output_path

    def _seconds_to_timecode(self, seconds: float, fps: int) -> str:
        """Convert seconds to SMPTE timecode"""
        total_frames = int(seconds * fps)
        frames = total_frames % fps
        total_seconds = total_frames // fps
        secs = total_seconds % 60
        mins = (total_seconds // 60) % 60
        hours = total_seconds // 3600
        return f"{hours:02d}:{mins:02d}:{secs:02d}:{frames:02d}"
