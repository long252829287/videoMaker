"""Video composer - timeline and mixing"""

from .timeline import TimelineBuilder
from .subtitle import SubtitleGenerator
from .mixer import Mixer
from .duration import process_audio_with_padding, get_audio_duration, calculate_video_strategy
from ..shared.models import DurationStrategy

__all__ = [
    "TimelineBuilder",
    "SubtitleGenerator",
    "Mixer",
    "DurationStrategy",
    "process_audio_with_padding",
    "get_audio_duration",
    "calculate_video_strategy"
]
