"""
Configuration management module.

Loads settings from environment variables and config files.
"""

import os
from pathlib import Path
from typing import Optional
from pydantic import BaseModel, Field
from functools import lru_cache


class ComfyUIConfig(BaseModel):
    """ComfyUI configuration"""
    host: str = Field(default="127.0.0.1")
    port: int = Field(default=8188)
    timeout: float = Field(default=120.0, description="Task timeout in seconds")

    @property
    def http_url(self) -> str:
        return f"http://{self.host}:{self.port}"

    @property
    def ws_url(self) -> str:
        return f"ws://{self.host}:{self.port}/ws"


class LLMConfig(BaseModel):
    """LLM configuration"""
    provider: str = Field(default="openai", description="anthropic | openai")
    model: str = Field(default="glm-4")
    api_key: Optional[str] = None
    base_url: Optional[str] = Field(default=None, description="Custom API base URL")
    max_tokens: int = Field(default=4096)
    temperature: float = Field(default=0.7)


class TTSConfig(BaseModel):
    """TTS configuration"""
    provider: str = Field(default="edge-tts", description="edge-tts | elevenlabs | gpt-sovits")
    default_voice: str = Field(default="zh-CN-YunxiNeural")
    api_key: Optional[str] = None

    @property
    def voice(self) -> str:
        return self.default_voice


class AudioConfig(BaseModel):
    """Audio processing configuration"""
    padding_before_ms: int = Field(default=200, description="Silence before audio")
    padding_after_ms: int = Field(default=300, description="Silence after audio")
    sample_rate: int = Field(default=44100)


class VideoConfig(BaseModel):
    """Video rendering configuration"""
    default_resolution: tuple[int, int] = Field(default=(1920, 1080))
    default_fps: int = Field(default=30)
    codec: str = Field(default="libx264")
    crf: int = Field(default=23, description="Quality factor (lower = better)")

    @property
    def width(self) -> int:
        return self.default_resolution[0]

    @property
    def height(self) -> int:
        return self.default_resolution[1]

    @property
    def fps(self) -> int:
        return self.default_fps


class PathsConfig(BaseModel):
    """Paths configuration"""
    storage_dir: str = Field(default="storage")
    projects_dir: str = Field(default="storage/projects")
    models_dir: str = Field(default="storage/models")
    cache_dir: str = Field(default="storage/cache")
    comfyui_workflows_dir: str = Field(default="comfyui/workflows")
    prompts_dir: str = Field(default="src/script/prompts")


class Config(BaseModel):
    """Main configuration"""
    debug: bool = Field(default=False)
    comfyui: ComfyUIConfig = Field(default_factory=ComfyUIConfig)
    llm: LLMConfig = Field(default_factory=LLMConfig)
    tts: TTSConfig = Field(default_factory=TTSConfig)
    audio: AudioConfig = Field(default_factory=AudioConfig)
    video: VideoConfig = Field(default_factory=VideoConfig)
    paths: PathsConfig = Field(default_factory=PathsConfig)

    @classmethod
    def from_env(cls) -> "Config":
        """Load configuration from environment variables"""
        return cls(
            debug=os.getenv("DEBUG", "false").lower() == "true",
            comfyui=ComfyUIConfig(
                host=os.getenv("COMFYUI_HOST", "127.0.0.1"),
                port=int(os.getenv("COMFYUI_PORT", "8188")),
            ),
            llm=LLMConfig(
                provider=os.getenv("LLM_PROVIDER", "openai"),
                model=os.getenv("LLM_MODEL", "glm-4"),
                api_key=os.getenv("LLM_API_KEY") or os.getenv("ANTHROPIC_API_KEY") or os.getenv("OPENAI_API_KEY"),
                base_url=os.getenv("LLM_BASE_URL"),
            ),
            tts=TTSConfig(
                provider=os.getenv("TTS_PROVIDER", "edge-tts"),
                default_voice=os.getenv("TTS_VOICE", "zh-CN-YunxiNeural"),
                api_key=os.getenv("ELEVENLABS_API_KEY"),
            ),
        )

    def ensure_directories(self) -> None:
        """Create necessary directories if they don't exist"""
        for path_attr in ["storage_dir", "projects_dir", "models_dir", "cache_dir"]:
            path = Path(getattr(self.paths, path_attr))
            path.mkdir(parents=True, exist_ok=True)


@lru_cache()
def get_config() -> Config:
    """Get cached configuration instance"""
    config = Config.from_env()
    config.ensure_directories()
    return config
