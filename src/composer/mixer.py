"""
Audio-video mixer.

Combines images, audio, and subtitles into timeline clips.
Prepares assets for final render.
"""

from pathlib import Path
from typing import Optional
from dataclasses import dataclass, field

from ..shared.logger import get_logger
from ..shared.models import DurationStrategy
from .timeline import Timeline, TimelineClip


logger = get_logger(__name__)


@dataclass
class MixedClip:
    """A clip ready for rendering"""
    shot_id: int
    start_time: float
    end_time: float

    # Visual
    image_path: Optional[str] = None
    video_path: Optional[str] = None

    # Audio tracks
    narration_path: Optional[str] = None
    bgm_path: Optional[str] = None
    sfx_paths: list[str] = field(default_factory=list)

    # Audio levels (0.0 - 1.0)
    narration_volume: float = 1.0
    bgm_volume: float = 0.3
    sfx_volume: float = 0.8

    # Effects
    transition_in: Optional[str] = None
    transition_out: Optional[str] = None
    ken_burns: Optional[dict] = None

    # Subtitle
    subtitle_text: Optional[str] = None

    @property
    def duration(self) -> float:
        return self.end_time - self.start_time


@dataclass
class MixedTimeline:
    """Complete mixed timeline ready for render"""
    clips: list[MixedClip] = field(default_factory=list)
    total_duration: float = 0.0
    fps: int = 30
    width: int = 1920
    height: int = 1080

    # Global BGM
    global_bgm_path: Optional[str] = None
    global_bgm_volume: float = 0.2


class Mixer:
    """
    Audio-video mixer.

    Combines:
    - Images/video from asset generation
    - Narration audio
    - Background music
    - Sound effects
    - Subtitles

    Produces MixedTimeline for rendering.
    """

    def __init__(
        self,
        fps: int = 30,
        width: int = 1920,
        height: int = 1080
    ):
        self.fps = fps
        self.width = width
        self.height = height

    def mix(
        self,
        timeline: Timeline,
        bgm_path: Optional[str] = None,
        bgm_volume: float = 0.2
    ) -> MixedTimeline:
        """
        Mix timeline into render-ready format.

        Args:
            timeline: Source timeline with clips
            bgm_path: Optional background music
            bgm_volume: BGM volume level

        Returns:
            MixedTimeline ready for rendering
        """
        mixed = MixedTimeline(
            fps=timeline.fps,
            width=timeline.width,
            height=timeline.height,
            global_bgm_path=bgm_path,
            global_bgm_volume=bgm_volume
        )

        for clip in timeline.clips:
            mixed_clip = self._mix_clip(clip)
            mixed.clips.append(mixed_clip)

        mixed.total_duration = timeline.total_duration
        logger.info(f"Mixed {len(mixed.clips)} clips, {mixed.total_duration:.2f}s total")

        return mixed

    def _mix_clip(self, clip: TimelineClip) -> MixedClip:
        """Convert timeline clip to mixed clip"""
        mixed = MixedClip(
            shot_id=clip.shot_id,
            start_time=clip.start_time,
            end_time=clip.end_time,
            image_path=clip.image_path,
            narration_path=clip.audio_path,
            transition_in=clip.transition_in,
            transition_out=clip.transition_out
        )

        # Apply Ken Burns effect for static images
        if clip.image_path and not clip.metadata.get("is_video"):
            mixed.ken_burns = self._calculate_ken_burns(
                clip.duration,
                clip.metadata.get("camera_movement", "static")
            )

        return mixed

    def _calculate_ken_burns(
        self,
        duration: float,
        camera_movement: str
    ) -> Optional[dict]:
        """
        Calculate Ken Burns effect parameters.

        Simulates camera movement on static images.

        Args:
            duration: Clip duration
            camera_movement: Desired camera movement type (CameraMovement enum value)

        Returns:
            Ken Burns parameters dict, or None if static
        """
        # Normalize camera_movement to uppercase for enum matching
        movement = camera_movement.upper() if camera_movement else "STATIC"

        if movement == "STATIC":
            return None

        # Map CameraMovement enum values to Ken Burns effects
        effects = {
            # PUSH -> zoom in slowly
            "PUSH": {
                "start_scale": 1.0,
                "end_scale": 1.15,
                "start_x": 0.5,
                "start_y": 0.5,
                "end_x": 0.5,
                "end_y": 0.5
            },
            # PULL -> zoom out slowly
            "PULL": {
                "start_scale": 1.15,
                "end_scale": 1.0,
                "start_x": 0.5,
                "start_y": 0.5,
                "end_x": 0.5,
                "end_y": 0.5
            },
            # PAN -> horizontal movement (default: left to right)
            "PAN": {
                "start_scale": 1.15,
                "end_scale": 1.15,
                "start_x": 0.35,
                "start_y": 0.5,
                "end_x": 0.65,
                "end_y": 0.5
            },
            # TILT -> vertical movement (default: bottom to top)
            "TILT": {
                "start_scale": 1.15,
                "end_scale": 1.15,
                "start_x": 0.5,
                "start_y": 0.6,
                "end_x": 0.5,
                "end_y": 0.4
            },
            # DOLLY -> similar to push but with slight pan
            "DOLLY": {
                "start_scale": 1.0,
                "end_scale": 1.12,
                "start_x": 0.45,
                "start_y": 0.5,
                "end_x": 0.55,
                "end_y": 0.5
            },
            # CRANE -> vertical + zoom combination
            "CRANE": {
                "start_scale": 1.0,
                "end_scale": 1.1,
                "start_x": 0.5,
                "start_y": 0.6,
                "end_x": 0.5,
                "end_y": 0.4
            },
            # HANDHELD -> subtle random-like movement (slight zoom + pan)
            "HANDHELD": {
                "start_scale": 1.02,
                "end_scale": 1.05,
                "start_x": 0.48,
                "start_y": 0.52,
                "end_x": 0.52,
                "end_y": 0.48
            },
            # ZOOM -> aggressive zoom in
            "ZOOM": {
                "start_scale": 1.0,
                "end_scale": 1.25,
                "start_x": 0.5,
                "start_y": 0.5,
                "end_x": 0.5,
                "end_y": 0.5
            },
            # AERIAL -> slow pull out with slight tilt (bird's eye feeling)
            "AERIAL": {
                "start_scale": 1.15,
                "end_scale": 1.0,
                "start_x": 0.5,
                "start_y": 0.55,
                "end_x": 0.5,
                "end_y": 0.45
            },
            # Legacy lowercase mappings for backward compatibility
            "push_in": {
                "start_scale": 1.0,
                "end_scale": 1.1,
                "start_x": 0.5,
                "start_y": 0.5,
                "end_x": 0.5,
                "end_y": 0.5
            },
            "pull_out": {
                "start_scale": 1.1,
                "end_scale": 1.0,
                "start_x": 0.5,
                "start_y": 0.5,
                "end_x": 0.5,
                "end_y": 0.5
            },
            "pan_left": {
                "start_scale": 1.1,
                "end_scale": 1.1,
                "start_x": 0.6,
                "start_y": 0.5,
                "end_x": 0.4,
                "end_y": 0.5
            },
            "pan_right": {
                "start_scale": 1.1,
                "end_scale": 1.1,
                "start_x": 0.4,
                "start_y": 0.5,
                "end_x": 0.6,
                "end_y": 0.5
            },
            "tilt_up": {
                "start_scale": 1.1,
                "end_scale": 1.1,
                "start_x": 0.5,
                "start_y": 0.6,
                "end_x": 0.5,
                "end_y": 0.4
            },
            "tilt_down": {
                "start_scale": 1.1,
                "end_scale": 1.1,
                "start_x": 0.5,
                "start_y": 0.4,
                "end_x": 0.5,
                "end_y": 0.6
            }
        }

        result = effects.get(movement)
        if result:
            logger.debug(f"Ken Burns effect applied: {movement}")
        return result

    def add_sfx(
        self,
        mixed_timeline: MixedTimeline,
        shot_id: int,
        sfx_path: str,
        volume: float = 0.8
    ) -> None:
        """
        Add sound effect to a clip.

        Args:
            mixed_timeline: Timeline to modify
            shot_id: Target shot ID
            sfx_path: Path to SFX audio
            volume: Volume level
        """
        for clip in mixed_timeline.clips:
            if clip.shot_id == shot_id:
                clip.sfx_paths.append(sfx_path)
                clip.sfx_volume = volume
                logger.debug(f"Added SFX to shot {shot_id}: {sfx_path}")
                return

        logger.warning(f"Shot {shot_id} not found for SFX")

    def adjust_audio_levels(
        self,
        mixed_timeline: MixedTimeline,
        narration_volume: float = 1.0,
        bgm_volume: float = 0.2,
        sfx_volume: float = 0.8
    ) -> None:
        """
        Adjust audio levels for all clips.

        Args:
            mixed_timeline: Timeline to modify
            narration_volume: Narration volume (0-1)
            bgm_volume: BGM volume (0-1)
            sfx_volume: SFX volume (0-1)
        """
        mixed_timeline.global_bgm_volume = bgm_volume

        for clip in mixed_timeline.clips:
            clip.narration_volume = narration_volume
            clip.sfx_volume = sfx_volume

        logger.info(
            f"Audio levels adjusted: narration={narration_volume}, "
            f"bgm={bgm_volume}, sfx={sfx_volume}"
        )

    def export_project_file(
        self,
        mixed_timeline: MixedTimeline,
        output_path: str
    ) -> str:
        """
        Export mixed timeline as project JSON.

        Can be used for manual editing or render resume.

        Args:
            mixed_timeline: Timeline to export
            output_path: Output path

        Returns:
            Path to project file
        """
        import json

        data = {
            "fps": mixed_timeline.fps,
            "width": mixed_timeline.width,
            "height": mixed_timeline.height,
            "total_duration": mixed_timeline.total_duration,
            "global_bgm": {
                "path": mixed_timeline.global_bgm_path,
                "volume": mixed_timeline.global_bgm_volume
            },
            "clips": [
                {
                    "shot_id": c.shot_id,
                    "start_time": c.start_time,
                    "end_time": c.end_time,
                    "duration": c.duration,
                    "image_path": c.image_path,
                    "video_path": c.video_path,
                    "narration_path": c.narration_path,
                    "narration_volume": c.narration_volume,
                    "bgm_path": c.bgm_path,
                    "bgm_volume": c.bgm_volume,
                    "sfx_paths": c.sfx_paths,
                    "sfx_volume": c.sfx_volume,
                    "transition_in": c.transition_in,
                    "transition_out": c.transition_out,
                    "ken_burns": c.ken_burns,
                    "subtitle_text": c.subtitle_text
                }
                for c in mixed_timeline.clips
            ]
        }

        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        Path(output_path).write_text(
            json.dumps(data, indent=2, ensure_ascii=False),
            encoding="utf-8"
        )

        logger.info(f"Project file exported: {output_path}")
        return output_path
