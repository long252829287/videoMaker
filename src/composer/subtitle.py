"""
Subtitle generation and formatting.

Creates SRT/ASS subtitles from timeline and narration.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from ..shared.logger import get_logger
from ..shared.models import Shot
from .timeline import Timeline, TimelineClip


logger = get_logger(__name__)


@dataclass
class SubtitleEntry:
    """A single subtitle entry"""
    index: int
    start_time: float
    end_time: float
    text: str
    style: Optional[str] = None

    def to_srt(self) -> str:
        """Convert to SRT format"""
        start = self._format_srt_time(self.start_time)
        end = self._format_srt_time(self.end_time)
        return f"{self.index}\n{start} --> {end}\n{self.text}\n"

    def to_ass_dialogue(self) -> str:
        """Convert to ASS dialogue line"""
        start = self._format_ass_time(self.start_time)
        end = self._format_ass_time(self.end_time)
        style = self.style or "Default"
        return f"Dialogue: 0,{start},{end},{style},,0,0,0,,{self.text}"

    def _format_srt_time(self, seconds: float) -> str:
        """Format time as SRT timestamp (HH:MM:SS,mmm)"""
        hours = int(seconds // 3600)
        mins = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        millis = int((seconds % 1) * 1000)
        return f"{hours:02d}:{mins:02d}:{secs:02d},{millis:03d}"

    def _format_ass_time(self, seconds: float) -> str:
        """Format time as ASS timestamp (H:MM:SS.cc)"""
        hours = int(seconds // 3600)
        mins = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        centis = int((seconds % 1) * 100)
        return f"{hours}:{mins:02d}:{secs:02d}.{centis:02d}"


class SubtitleGenerator:
    """
    Subtitle generator from timeline.

    Supports:
    - SRT format (simple, universal)
    - ASS format (styled, for CJK)
    """

    # ASS header template
    ASS_HEADER = """[Script Info]
ScriptType: v4.00+
PlayResX: 1920
PlayResY: 1080
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Noto Sans CJK SC,48,&H00FFFFFF,&H000000FF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,2,1,2,20,20,30,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

    def __init__(self):
        self.entries: list[SubtitleEntry] = []

    def generate_from_timeline(
        self,
        timeline: Timeline,
        shots: list[Shot]
    ) -> list[SubtitleEntry]:
        """
        Generate subtitles from timeline and shots.

        Args:
            timeline: Video timeline
            shots: Original shots with narration

        Returns:
            List of subtitle entries
        """
        self.entries = []

        # Build shot lookup
        shot_map = {s.shot_id: s for s in shots}

        for i, clip in enumerate(timeline.clips, 1):
            shot = shot_map.get(clip.shot_id)
            if not shot or not shot.narration:
                continue

            entry = SubtitleEntry(
                index=i,
                start_time=clip.start_time,
                end_time=clip.end_time,
                text=shot.narration
            )
            self.entries.append(entry)

        logger.info(f"Generated {len(self.entries)} subtitle entries")
        return self.entries

    def generate_from_shots(
        self,
        shots: list[Shot],
        audio_results: list[dict]
    ) -> list[SubtitleEntry]:
        """
        Generate subtitles from shots and audio timing.

        Uses audio duration for precise timing.

        Args:
            shots: Shots with narration
            audio_results: Audio generation results with timing

        Returns:
            List of subtitle entries
        """
        self.entries = []

        # Build audio lookup
        audio_map = {r["shot_id"]: r for r in audio_results if r.get("has_audio")}

        current_time = 0.0
        index = 1

        for shot in shots:
            audio_info = audio_map.get(shot.shot_id)

            if audio_info:
                duration = audio_info["padded_duration"]
            else:
                duration = shot.duration

            if shot.narration:
                # Adjust for padding (subtitle should match actual speech)
                padding_before = audio_info.get("padding_before_ms", 200) / 1000 if audio_info else 0
                padding_after = audio_info.get("padding_after_ms", 300) / 1000 if audio_info else 0

                entry = SubtitleEntry(
                    index=index,
                    start_time=current_time + padding_before,
                    end_time=current_time + duration - padding_after,
                    text=shot.narration
                )
                self.entries.append(entry)
                index += 1

            current_time += duration

        return self.entries

    def export_srt(self, output_path: str) -> str:
        """
        Export subtitles as SRT file.

        Args:
            output_path: Output file path

        Returns:
            Path to SRT file
        """
        content = "\n".join(e.to_srt() for e in self.entries)

        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        Path(output_path).write_text(content, encoding="utf-8")

        logger.info(f"SRT exported: {output_path}")
        return output_path

    def export_ass(self, output_path: str, style_name: str = "Default") -> str:
        """
        Export subtitles as ASS file.

        Args:
            output_path: Output file path
            style_name: Style name to use

        Returns:
            Path to ASS file
        """
        # Update entries with style
        for entry in self.entries:
            entry.style = style_name

        dialogues = "\n".join(e.to_ass_dialogue() for e in self.entries)
        content = self.ASS_HEADER + dialogues

        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        Path(output_path).write_text(content, encoding="utf-8")

        logger.info(f"ASS exported: {output_path}")
        return output_path

    def split_long_lines(self, max_chars: int = 40) -> None:
        """
        Split long subtitle lines for better readability.

        Args:
            max_chars: Maximum characters per line
        """
        new_entries = []

        for entry in self.entries:
            if len(entry.text) <= max_chars:
                new_entries.append(entry)
                continue

            # Split by punctuation or space
            lines = self._split_text(entry.text, max_chars)
            text = "\n".join(lines)

            new_entries.append(SubtitleEntry(
                index=entry.index,
                start_time=entry.start_time,
                end_time=entry.end_time,
                text=text,
                style=entry.style
            ))

        self.entries = new_entries

    def _split_text(self, text: str, max_chars: int) -> list[str]:
        """Split text into lines of max_chars length"""
        lines = []
        current = ""

        # Split by Chinese punctuation or spaces
        import re
        parts = re.split(r'([，。！？、；：\s])', text)

        for part in parts:
            if len(current) + len(part) <= max_chars:
                current += part
            else:
                if current:
                    lines.append(current.strip())
                current = part

        if current:
            lines.append(current.strip())

        return lines
