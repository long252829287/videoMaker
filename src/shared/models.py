"""
Core data models for the video automation system.

Based on PROJECT_SPEC.md v1.3
"""

from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field
from uuid import uuid4


# ============================================================
# Enums
# ============================================================

class ShotType(str, Enum):
    """景别类型"""
    ECU = "ECU"      # 大特写 (Extreme Close-Up)
    CU = "CU"        # 特写 (Close-Up)
    MCU = "MCU"      # 中近景 (Medium Close-Up)
    MS = "MS"        # 中景 (Medium Shot)
    MLS = "MLS"      # 中远景 (Medium Long Shot)
    LS = "LS"        # 远景 (Long Shot)
    ELS = "ELS"      # 大远景 (Extreme Long Shot)
    AERIAL = "AERIAL"  # 航拍


class CameraMovement(str, Enum):
    """运镜类型"""
    STATIC = "STATIC"      # 固定
    PUSH = "PUSH"          # 推
    PULL = "PULL"          # 拉
    PAN = "PAN"            # 摇 (水平)
    TILT = "TILT"          # 俯仰 (垂直)
    DOLLY = "DOLLY"        # 移
    CRANE = "CRANE"        # 升降
    HANDHELD = "HANDHELD"  # 手持
    ZOOM = "ZOOM"          # 变焦


class SceneType(str, Enum):
    """素材类型"""
    IMAGE = "image"    # 图文模式
    VIDEO = "video"    # AI视频模式
    STOCK = "stock"    # 素材库


class Transition(str, Enum):
    """转场类型"""
    CUT = "CUT"            # 硬切
    DISSOLVE = "DISSOLVE"  # 叠化
    FADE = "FADE"          # 淡入淡出
    WIPE = "WIPE"          # 划像


class CharacterTier(str, Enum):
    """角色等级"""
    TIER1 = "tier1"  # 主角 - LoRA + IP-Adapter
    TIER2 = "tier2"  # 配角 - 仅 IP-Adapter
    TIER3 = "tier3"  # 路人 - 仅 Prompt


class DurationStrategy(str, Enum):
    """时长对齐策略"""
    STATIC = "static"       # 静态展示
    LOOP = "loop"           # 循环播放视频
    FREEZE = "freeze"       # 最后一帧定格
    SPEED_UP = "speed_up"   # 加速播放
    TRUNCATE = "truncate"   # 截断视频


# ============================================================
# World Setting Models
# ============================================================

class CharacterAppearance(BaseModel):
    """角色外貌"""
    face: str = Field(description="五官描述")
    hair: str = Field(description="发型发色")
    body: str = Field(default="", description="体型特征")
    skin: str = Field(default="", description="肤色")


class CharacterOutfit(BaseModel):
    """角色服装"""
    default: str = Field(description="默认服装描述")
    variations: list[str] = Field(default_factory=list, description="服装变体")


class VoiceProfile(BaseModel):
    """声线配置"""
    tone: str = Field(description="声线特征")
    emotion_range: list[str] = Field(
        default_factory=lambda: ["neutral", "happy", "angry", "sad"],
        description="情绪范围"
    )
    provider: str = Field(default="edge-tts", description="TTS 服务商")
    voice_id: Optional[str] = Field(default=None, description="声线 ID")
    reference_audio: Optional[str] = Field(default=None, description="参考音频路径")


class Character(BaseModel):
    """角色定义"""
    id: str = Field(default_factory=lambda: f"char_{uuid4().hex[:8]}")
    name: str
    gender: str = Field(default="", description="male | female")
    age: str = Field(default="", description="青年 | 中年 | 老年 等")
    description: str = Field(default="", description="角色描述")
    visual_description: str = Field(default="", description="视觉描述 for image generation")
    appearance: Optional[CharacterAppearance] = None
    outfit: Optional[CharacterOutfit] = None
    personality: str = Field(default="", description="性格特征")
    voice_profile: Optional[VoiceProfile] = None
    tier: CharacterTier = Field(default=CharacterTier.TIER2, description="角色等级")
    attributes: dict = Field(default_factory=dict, description="额外属性")


class Location(BaseModel):
    """场景定义"""
    id: str = Field(default_factory=lambda: f"loc_{uuid4().hex[:8]}")
    name: str
    description: str = Field(default="", description="环境描述")
    visual_description: str = Field(default="", description="视觉描述 for image generation")
    lighting: str = Field(default="neutral", description="光照条件: bright/dim/backlight/side_left/side_right")
    atmosphere: str = Field(default="", description="氛围")
    attributes: dict = Field(default_factory=dict, description="额外属性")


class Prop(BaseModel):
    """道具定义"""
    id: str = Field(default_factory=lambda: f"prop_{uuid4().hex[:8]}")
    name: str
    description: str = Field(description="外观描述")


class WorldSetting(BaseModel):
    """世界观设定集"""
    project_id: str = Field(default_factory=lambda: uuid4().hex)
    title: str = Field(default="", description="作品名称")
    style: str = Field(default="", description="视觉风格: 写实 | 动漫 | 赛博朋克 | ...")
    style_prompt: str = Field(
        default="cinematic lighting, 8k, photorealistic",
        description="全局风格 Prompt 后缀"
    )
    characters: list[Character] = Field(default_factory=list)
    locations: list[Location] = Field(default_factory=list)
    props: list[Prop] = Field(default_factory=list)

    def get_character(self, char_id: str) -> Optional[Character]:
        """Get character by ID"""
        for char in self.characters:
            if char.id == char_id:
                return char
        return None

    def get_location(self, loc_id: str) -> Optional[Location]:
        """Get location by ID"""
        for loc in self.locations:
            if loc.id == loc_id:
                return loc
        return None


# ============================================================
# Storyboard Models
# ============================================================

class Shot(BaseModel):
    """分镜镜头"""
    shot_id: int = Field(description="镜头序号")
    shot_type: ShotType = Field(default=ShotType.MS, description="景别")
    camera_movement: CameraMovement = Field(default=CameraMovement.STATIC, description="运镜")
    duration: float = Field(default=5.0, ge=0.5, le=60.0, description="时长(秒)")
    scene_type: SceneType = Field(default=SceneType.IMAGE, description="素材类型")
    location_id: Optional[str] = Field(default=None, description="场景引用")
    characters: list[str] = Field(default_factory=list, description="出场角色ID列表")
    description: str = Field(default="", description="镜头描述")
    action: str = Field(default="", description="动作描述")
    dialogue: str = Field(default="", description="台词")
    narration: str = Field(default="", description="旁白")
    emotion: str = Field(default="neutral", description="情绪氛围")
    visual_prompt: str = Field(default="", description="画面 Prompt (英文)")
    audio_cue: str = Field(default="", description="音效提示")
    transition: Transition = Field(default=Transition.CUT, description="转场")


class Storyboard(BaseModel):
    """分镜脚本"""
    project_id: str = Field(default="")
    title: str = Field(default="", description="标题")
    world_setting_ref: str = Field(default="", description="世界观设定文件路径")
    global_style: Optional[str] = Field(default=None, description="全局风格")
    total_duration: float = Field(default=0.0, description="总时长(秒)")
    shots: list[Shot] = Field(default_factory=list)
    world_setting: Optional[WorldSetting] = Field(default=None, description="内嵌世界观设定")

    def calculate_total_duration(self) -> float:
        """计算总时长"""
        self.total_duration = sum(shot.duration for shot in self.shots)
        return self.total_duration


# ============================================================
# Pipeline Models
# ============================================================

class TaskStatus(str, Enum):
    """任务状态"""
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    RETRY = "retry"


class TaskResult(BaseModel):
    """任务执行结果"""
    task_id: str = Field(default="")
    task_type: str = Field(default="")
    status: TaskStatus = Field(default=TaskStatus.PENDING)
    success: bool = Field(default=True)
    message: str = Field(default="")
    artifacts: list[str] = Field(default_factory=list, description="产出物路径")
    data: dict = Field(default_factory=dict)
    metadata: dict = Field(default_factory=dict)
    error: Optional[str] = None
    error_code: Optional[str] = None
    duration_seconds: float = Field(default=0.0)


class ProjectState(BaseModel):
    """项目状态"""
    project_id: str
    input_text: str = Field(default="", description="输入文本")
    current_stage: str = Field(default="init")
    completed_stages: list[str] = Field(default_factory=list)
    world_setting_path: Optional[str] = None
    storyboard_path: Optional[str] = None
    character_assets: dict[str, str] = Field(default_factory=dict, description="角色ID -> 资产目录")
    shot_assets: dict[int, dict] = Field(default_factory=dict, description="shot_id -> 资产信息")
    output_path: Optional[str] = None
    created_at: str = ""
    updated_at: str = ""


# ============================================================
# Asset Models
# ============================================================

class AssetInfo(BaseModel):
    """资产信息"""
    path: str
    version: int
    shot_id: int
    asset_type: str  # "images" | "audio" | "video"
    metadata: dict = Field(default_factory=dict)


class AudioInfo(BaseModel):
    """音频信息"""
    original_path: str
    padded_path: Optional[str] = None
    original_duration: float
    padded_duration: float
    padding_before_ms: int = 200
    padding_after_ms: int = 300


class VideoStrategy(BaseModel):
    """视频处理策略"""
    strategy: DurationStrategy
    loop_count: int = Field(default=1)
    speed_factor: float = Field(default=1.0)
    end_time: Optional[float] = None
    total_video_duration: float = Field(default=0.0)
