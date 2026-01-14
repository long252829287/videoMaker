"""
Custom exceptions for the video automation system.
"""


class VideoMakerError(Exception):
    """Base exception for all video maker errors"""
    pass


class PipelineError(VideoMakerError):
    """Pipeline execution error"""

    def __init__(self, stage: str, message: str, cause: Exception = None):
        self.stage = stage
        self.cause = cause
        super().__init__(f"[{stage}] {message}")


class GenerationError(VideoMakerError):
    """Asset generation error"""

    def __init__(self, asset_type: str, message: str, shot_id: int = None):
        self.asset_type = asset_type
        self.shot_id = shot_id
        prefix = f"Shot {shot_id}: " if shot_id else ""
        super().__init__(f"{prefix}[{asset_type}] {message}")


class ComfyUIError(VideoMakerError):
    """ComfyUI related error"""

    def __init__(self, message: str, prompt_id: str = None):
        self.prompt_id = prompt_id
        super().__init__(message)


class ConfigError(VideoMakerError):
    """Configuration error"""
    pass


class LLMError(VideoMakerError):
    """LLM API error"""
    pass


class AudioError(VideoMakerError):
    """Audio processing error"""
    pass


class ValidationError(VideoMakerError):
    """Data validation error"""

    def __init__(self, message: str, field: str = None):
        self.field = field
        if field:
            super().__init__(f"Validation error in '{field}': {message}")
        else:
            super().__init__(message)


class TimeoutError(VideoMakerError):
    """Operation timeout error"""

    def __init__(self, operation: str, timeout_seconds: float):
        self.operation = operation
        self.timeout_seconds = timeout_seconds
        super().__init__(f"Operation '{operation}' timed out after {timeout_seconds}s")
