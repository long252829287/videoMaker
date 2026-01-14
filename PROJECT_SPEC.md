# AI 视频全流程自动化系统 - 项目需求文档 v1.0

## 1. 项目概述

### 1.1 项目目标
构建一套模块化、可扩展的 AI 视频自动化生产系统，实现从文本内容到视频发布的全流程自动化，**重点解决角色一致性**这一 AI 视频核心痛点。

### 1.2 核心价值
- **全自动化**：最小化人工干预，从脚本到发布一键完成
- **一致性可控**：通过角色定妆 + IP-Adapter 保证角色跨场景一致
- **模块化**：各阶段独立运行，支持灵活组合与替换
- **专业级输出**：支持专业分镜语言（景别、运镜、情绪）

### 1.3 系统架构总览

```
┌───────────────────────────────────────────────────────────────────────────────────┐
│                              Orchestrator (工作流编排层)                            │
│                           Python + Celery + ComfyUI API                            │
└─────┬─────────┬─────────────┬─────────────┬─────────────┬─────────────┬───────────┘
      │         │             │             │             │             │
      ▼         ▼             ▼             ▼             ▼             ▼
┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐
│  Script  │ │Character │ │  Asset   │ │  Video   │ │  Render  │ │ Publish  │
│  Engine  │ │  Engine  │ │  Engine  │ │ Composer │ │  Engine  │ │ Gateway  │
│ 脚本引擎  │ │ 角色引擎  │ │ 素材引擎  │ │ 视频合成  │ │ 渲染引擎  │ │ 发布网关  │
└──────────┘ └──────────┘ └──────────┘ └──────────┘ └──────────┘ └──────────┘
     ↓             ↓             ↓             ↓             ↓             ↓
  分镜脚本      角色资产       图像/音频      原始视频      成品视频      多平台
```

---

## 2. 核心阶段详解

### 阶段 0：工作流编排层 (Orchestrator)
**职责**：任务调度、状态管理、ComfyUI 工作流编排、断点恢复

| 任务 | 说明 | 工具/技术 | 语言 |
|------|------|-----------|------|
| Pipeline 编排 | DAG 任务流定义与执行 | 自研 YAML DSL | Python |
| ComfyUI 集成 | 图像/视频生成工作流 | ComfyUI API | Python |
| 任务队列 | 异步任务调度 | Celery + Redis | Python |
| 状态持久化 | 任务进度、中间产物存储 | PostgreSQL + MinIO | Python |
| API Gateway | RESTful 接口 | FastAPI | Python |
| 断点恢复 | 失败任务续跑 | 自研 | Python |

#### ⚠️ ComfyUI Workflow Builder 模式

> **痛点**：ComfyUI workflow 是巨大的 JSON，直接操作极易出错
> - 节点更新时 ID 可能变化
> - 手动修改 seed/prompt/image_path 容易遗漏

**解决方案：Workflow Builder 封装**

```python
# 不要这样做 ❌
workflow_json["3"]["inputs"]["seed"] = 12345
workflow_json["6"]["inputs"]["text"] = "a beautiful girl"

# 应该这样做 ✅
class ComfyWorkflow:
    """ComfyUI Workflow 构建器"""

    def __init__(self, template_path: str):
        self.template = self._load_template(template_path)
        self._node_map = self._build_node_map()

    def set_prompt(self, positive: str, negative: str = ""):
        """设置正向/负向提示词"""
        self._set_node_input("CLIPTextEncode_positive", "text", positive)
        self._set_node_input("CLIPTextEncode_negative", "text", negative)
        return self

    def set_seed(self, seed: int):
        """设置随机种子"""
        self._set_node_input("KSampler", "seed", seed)
        return self

    def set_image(self, image_path: str):
        """设置输入图像"""
        self._set_node_input("LoadImage", "image", image_path)
        return self

    def set_lora(self, lora_name: str, strength: float = 1.0):
        """加载 LoRA"""
        self._set_node_input("LoraLoader", "lora_name", lora_name)
        self._set_node_input("LoraLoader", "strength_model", strength)
        return self

    def build(self) -> dict:
        """构建最终 workflow JSON"""
        return copy.deepcopy(self.template)

    def apply_global_style(self, style_prompt: str, style_lora: str = None):
        """
        全局风格注入 —— 避免画面"拼盘感"
        强制将风格 Prompt 拼接到所有正向 Prompt 的末尾
        """
        current_text = self._get_node_input("CLIPTextEncode_positive", "text")
        # 风格后缀，例如: ", cinematic lighting, 8k, photorealistic, dark atmosphere"
        new_text = f"{current_text}, {style_prompt}"
        self._set_node_input("CLIPTextEncode_positive", "text", new_text)

        if style_lora:
            self.set_lora(style_lora, strength=0.6)

        return self

# 使用示例
workflow = (
    ComfyWorkflow("workflows/character_gen.json")
    .set_prompt("a young man with black hair, portrait, cinematic")
    .set_seed(42)
    .set_lora("char_001.safetensors", 0.8)
    .apply_global_style("cinematic lighting, 8k, photorealistic, film grain")  # ⭐ 全局风格
    .build()
)
```

#### ⚠️ ComfyUI WebSocket 监听

> **关键问题**：ComfyUI API (POST /prompt) 只是提交任务，立即返回 prompt_id
> 不会等待生成完成，直接读文件会报错

**异步任务监听实现**：
```python
import websocket
import json
import uuid
from urllib.request import urlopen, Request

class ComfyUIClient:
    """ComfyUI API 客户端（含 WebSocket 监听）"""

    def __init__(self, host: str = "127.0.0.1", port: int = 8188):
        self.host = host
        self.port = port
        self.client_id = str(uuid.uuid4())

    def submit_and_wait(self, workflow: dict, timeout: float = 120) -> dict:
        """
        提交 workflow 并阻塞等待完成
        返回生成的文件信息
        """
        prompt_id = self._submit_prompt(workflow)
        return self._wait_for_completion(prompt_id, timeout)

    def _submit_prompt(self, workflow: dict) -> str:
        """提交 prompt，返回 prompt_id"""
        payload = {
            "prompt": workflow,
            "client_id": self.client_id
        }
        req = Request(
            f"http://{self.host}:{self.port}/prompt",
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"}
        )
        response = json.loads(urlopen(req).read())
        return response["prompt_id"]

    def _wait_for_completion(self, prompt_id: str, timeout: float) -> dict:
        """通过 WebSocket 等待任务完成"""
        ws = websocket.create_connection(
            f"ws://{self.host}:{self.port}/ws?clientId={self.client_id}",
            timeout=timeout
        )

        try:
            while True:
                msg = json.loads(ws.recv())
                msg_type = msg.get("type")

                if msg_type == "executing":
                    data = msg.get("data", {})
                    if data.get("node") is None and data.get("prompt_id") == prompt_id:
                        # 执行完成
                        break

                elif msg_type == "execution_error":
                    raise RuntimeError(f"ComfyUI execution error: {msg}")

            # 获取输出结果
            return self._get_history(prompt_id)

        finally:
            ws.close()

    def _get_history(self, prompt_id: str) -> dict:
        """获取执行历史，包含输出文件信息"""
        response = urlopen(f"http://{self.host}:{self.port}/history/{prompt_id}")
        history = json.loads(response.read())
        return history.get(prompt_id, {}).get("outputs", {})

# 使用示例
client = ComfyUIClient()
workflow = ComfyWorkflow("character_gen.json").set_prompt("...").build()

outputs = client.submit_and_wait(workflow, timeout=120)
# outputs = {"9": {"images": [{"filename": "ComfyUI_00001_.png", "subfolder": "", "type": "output"}]}}

image_filename = outputs["9"]["images"][0]["filename"]
print(f"Generated: {image_filename}")
```

**工作流模板管理**：
```
/comfyui/workflows/
├── base/
│   ├── sdxl_base.json          # SDXL 基础模板
│   └── flux_base.json          # Flux 基础模板
├── character/
│   ├── char_portrait.json      # 角色肖像
│   ├── char_fullbody.json      # 角色全身
│   └── char_expression.json    # 表情变体
├── keyframe/
│   ├── scene_empty.json        # 场景空镜
│   ├── scene_with_char.json    # 角色+场景
│   └── multi_char.json         # 多角色
└── README.md                    # 模板说明
```

**子目录**：`/orchestrator`

---

### 阶段 1：脚本引擎 (Script Engine)
**职责**：文本预处理 → 世界观构建 → 专业分镜脚本生成

#### 1.1 文本预处理与世界观构建

| 任务 | 说明 | 输入 | 输出 |
|------|------|------|------|
| **文本清洗** | 去除无关内容，提取核心叙事 | 原始文本/小说片段 | 清洗后文本 |
| **角色提取** | 识别所有登场角色及其属性 | 清洗后文本 | 角色列表 |
| **场景提取** | 识别所有场景及环境描写 | 清洗后文本 | 场景列表 |
| **道具提取** | 识别关键道具及其描述 | 清洗后文本 | 道具列表 |
| **世界观设定集** | 整合为结构化设定文档 | 上述提取结果 | `world_setting.json` |

**世界观设定集 Schema**：
```json
{
  "project_id": "uuid",
  "title": "作品名称",
  "style": "写实 | 动漫 | 赛博朋克 | ...",
  "characters": [
    {
      "id": "char_001",
      "name": "角色名",
      "gender": "male | female",
      "age": "青年 | 中年 | ...",
      "appearance": {
        "face": "五官描述",
        "hair": "发型发色",
        "body": "体型特征",
        "skin": "肤色"
      },
      "outfit": {
        "default": "默认服装描述",
        "variations": ["服装变体1", "..."]
      },
      "personality": "性格特征（影响表情、动作）",
      "voice_profile": {
        "tone": "声线特征",
        "emotion_range": ["正常", "愤怒", "悲伤", "..."]
      }
    }
  ],
  "locations": [
    {
      "id": "loc_001",
      "name": "场景名",
      "description": "环境描述",
      "lighting": "光照条件",
      "atmosphere": "氛围"
    }
  ],
  "props": [
    {
      "id": "prop_001",
      "name": "道具名",
      "description": "外观描述"
    }
  ]
}
```

#### 1.2 剧本改编 (文学语言 → 视觉语言)

| 任务 | 说明 | 示例 |
|------|------|------|
| **心理外化** | 内心描写 → 可视动作/表情 | "他很愤怒" → "他紧握双拳，太阳穴青筋暴起" |
| **抽象具象化** | 抽象概念 → 具体画面 | "时间流逝" → "墙上时钟指针快速转动" |
| **对话场景化** | 纯对话 → 带动作的对话 | 补充说话时的肢体语言、表情变化 |

#### 1.3 专业分镜脚本 (Auto-Storyboarding)

| 字段 | 类型 | 说明 | 取值范围 |
|------|------|------|----------|
| `shot_id` | int | 镜头序号 | 1, 2, 3... |
| `shot_type` | enum | 景别 | `ECU`(大特写), `CU`(特写), `MCU`(中近景), `MS`(中景), `MLS`(中远景), `LS`(远景), `ELS`(大远景), `AERIAL`(航拍) |
| `camera_movement` | enum | 运镜 | `STATIC`(固定), `PUSH`(推), `PULL`(拉), `PAN`(摇), `TILT`(俯仰), `DOLLY`(移), `CRANE`(升降), `HANDHELD`(手持), `ZOOM`(变焦) |
| `duration` | float | 时长(秒) | 1.0 - 30.0 |
| `scene_type` | enum | 素材类型 | `image`(图文), `video`(AI视频), `stock`(素材库) |
| `location_id` | str | 场景引用 | 引用 world_setting |
| `characters` | list | 出场角色 | 角色ID列表 |
| `action` | str | 动作描述 | 人物在做什么 |
| `dialogue` | str | 台词 | 角色说的话 |
| `narration` | str | 旁白 | 画外音文案 |
| `emotion` | str | 情绪氛围 | 紧张/舒缓/悲伤/欢快/... |
| `visual_prompt` | str | 画面Prompt | 英文，给绘图AI用 |
| `audio_cue` | str | 音效提示 | 需要的环境音/音效 |
| `transition` | enum | 转场 | `CUT`(硬切), `DISSOLVE`(叠化), `FADE`(淡入淡出), `WIPE`(划像) |

**完整分镜脚本 Schema**：
```json
{
  "project_id": "uuid",
  "world_setting_ref": "world_setting.json",
  "total_duration": 120.5,
  "shots": [
    {
      "shot_id": 1,
      "shot_type": "ELS",
      "camera_movement": "CRANE",
      "duration": 5.0,
      "scene_type": "video",
      "location_id": "loc_001",
      "characters": [],
      "action": "",
      "dialogue": "",
      "narration": "在那个风雨交加的夜晚...",
      "emotion": "紧张",
      "visual_prompt": "A dark stormy night, lightning strikes over an old mansion on a hill, cinematic, dramatic lighting, 4K",
      "audio_cue": "thunder, heavy rain, wind howling",
      "transition": "FADE"
    },
    {
      "shot_id": 2,
      "shot_type": "CU",
      "camera_movement": "STATIC",
      "duration": 3.0,
      "scene_type": "image",
      "location_id": "loc_002",
      "characters": ["char_001"],
      "action": "紧握双拳，面部肌肉抽搐",
      "dialogue": "我不会原谅你的。",
      "narration": "",
      "emotion": "愤怒",
      "visual_prompt": "Close-up of a young man's face, angry expression, clenched jaw, dramatic side lighting, cinematic",
      "audio_cue": "",
      "transition": "CUT"
    }
  ]
}
```

**技术实现**：
| 任务 | 工具/技术 | 语言 |
|------|-----------|------|
| 文本分析 | Claude API / GPT-4o | Python |
| 结构化输出 | LLM + JSON Schema | Python |
| Prompt 模板 | Jinja2 | Python |

**子目录**：`/script-engine`

---

### 阶段 2：角色引擎 (Character Engine) ⭐ 关键模块
**职责**：角色一致性控制——生成角色定妆照、训练 LoRA、管理角色资产

#### 2.1 角色分级策略 (Cost vs. Quality)

> **LoRA 训练成本高（时间+算力），需要分级处理**

| 等级 | 适用角色 | 一致性方案 | 成本 | 效果 |
|------|----------|------------|------|------|
| **Tier 1** | 主角、高频角色 | LoRA + IP-Adapter FaceID | 高 | 最佳 |
| **Tier 2** | 配角、次要角色 | 仅 IP-Adapter | 中 | 良好 |
| **Tier 3** | 路人、背景角色 | 仅 Prompt 描述 | 低 | 一般 |

**判断标准**：
- 出镜次数 > 10 → Tier 1
- 出镜次数 3-10 → Tier 2
- 出镜次数 < 3 → Tier 3

#### 2.2 角色定妆 (Character Sheet)

| 任务 | 说明 | 工具/技术 |
|------|------|-----------|
| **基础形象生成** | 根据世界观设定生成角色正面照 | SDXL / Flux |
| **多角度生成** | 正面/侧面/45度角/背面 | ControlNet (Pose) |
| **表情变体** | 喜/怒/哀/惊/平静 | ControlNet + Prompt |
| **服装变体** | 不同场景的服装 | Prompt 控制 |

#### 2.3 Reference Atlas (参考图集) ⭐ 关键概念

> **IP-Adapter 在不同光影条件下效果差异巨大**
> **提供对应光影的参考图，效果提升 10 倍**

**角色资产包结构**：
```
/characters/char_001/
├── reference/
│   ├── standard/                    # 标准参考图 (必须)
│   │   ├── front.png               # 正面照（锚定图）
│   │   ├── front_45.png            # 45度角
│   │   ├── side_left.png           # 左侧面
│   │   ├── side_right.png          # 右侧面
│   │   └── back.png                # 背面
│   │
│   ├── lighting/                    # 光照变体 (Tier 1 必须)
│   │   ├── bright_front.png        # 强光正面
│   │   ├── dim_front.png           # 弱光正面
│   │   ├── backlight.png           # 逆光
│   │   ├── side_light_left.png     # 左侧光
│   │   └── side_light_right.png    # 右侧光
│   │
│   ├── expressions/                 # 表情变体
│   │   ├── neutral.png
│   │   ├── happy.png
│   │   ├── angry.png
│   │   ├── sad.png
│   │   └── surprised.png
│   │
│   └── outfits/                     # 服装变体 (可选)
│       ├── casual.png
│       └── formal.png
│
├── lora/                            # Tier 1 专用
│   └── char_001.safetensors
│
├── embeddings/
│   └── char_001_face.pt            # IP-Adapter FaceID 特征
│
└── metadata.json
```

**Reference Atlas 匹配逻辑**：
```python
def select_reference_image(character_id: str, shot: Shot) -> str:
    """根据镜头的光照条件选择最合适的参考图"""

    lighting_map = {
        "bright": "lighting/bright_front.png",
        "dim": "lighting/dim_front.png",
        "backlight": "lighting/backlight.png",
        "side_left": "lighting/side_light_left.png",
        "side_right": "lighting/side_light_right.png",
    }

    # 从场景设定中提取光照条件
    location = get_location(shot.location_id)
    lighting = location.lighting  # e.g., "dim", "bright"

    # 匹配对应光照的参考图
    ref_path = f"/characters/{character_id}/reference/"
    if lighting in lighting_map:
        return ref_path + lighting_map[lighting]

    # 降级：使用标准正面照
    return ref_path + "standard/front.png"
```

#### 2.4 一致性控制技术栈

| 技术 | 作用 | 适用场景 |
|------|------|----------|
| **LoRA 训练** | 将角色"烙印"进模型 | Tier 1 角色 |
| **IP-Adapter** | 图像特征注入 | 所有角色 |
| **IP-Adapter FaceID** | 锁定面部特征 | 人物面部一致性 |
| **ControlNet Pose** | 控制人物姿势 | 动作场景 |
| **ControlNet Canny/Depth** | 控制画面结构 | 场景一致性 |
| **Reference Only** | 参考图风格迁移 | 风格统一 |

**一致性控制流程**：
```
角色描述 (世界观设定)
        │
        ▼
┌─────────────────────┐
│  基础形象生成 (SDXL) │
└─────────────────────┘
        │
        ▼
┌─────────────────────┐
│  人工审核/微调       │  ← CP3 关键检查点
└─────────────────────┘
        │
        ▼
┌───────────────────────────────────────────────────────┐
│                   Reference Atlas 生成                 │
│   标准视角 + 光照变体 + 表情变体 + 服装变体             │
└───────────────────────────────────────────────────────┘
        │
        ▼
┌─────────────────────┐      ┌─────────────────────┐
│  LoRA 训练          │  OR  │  IP-Adapter 特征提取 │
│  (Tier 1)           │      │  (Tier 2/3)         │
└─────────────────────┘      └─────────────────────┘
        │                            │
        └──────────┬─────────────────┘
                   ▼
          角色资产库 (Character Bank)
```

**技术实现**：
| 任务 | 工具/技术 | 语言 |
|------|-----------|------|
| 图像生成 | ComfyUI + SDXL/Flux | Python |
| LoRA 训练 | Kohya_ss / sd-scripts | Python |
| 特征提取 | IP-Adapter | Python |
| 资产管理 | 自研 | Python |

**子目录**：`/character-engine`

---

### 阶段 3：素材引擎 (Asset Engine)
**职责**：生成关键帧图像、视频片段、音频素材

#### 3.0 资产版本控制 (Asset Versioning) ⭐ 必须实现

> **痛点**：调试时反复重新生成同一镜头，新文件会覆盖旧文件
> 当你发现"还是第一次生成的比较好"时，已经找不回来了

**文件命名策略**：
```
/storage/projects/{project_id}/assets/
├── images/
│   ├── shot_001_v01.png      # 第1版
│   ├── shot_001_v02.png      # 第2版 (重新生成)
│   ├── shot_001_v03.png      # 第3版
│   └── shot_002_v01.png
├── audio/
│   ├── shot_001_v01.wav
│   └── shot_001_v02.wav
└── video/
    └── shot_001_v01.mp4
```

**版本管理实现**：
```python
import glob
from pathlib import Path

def get_asset_path(
    project_id: str,
    shot_id: int,
    asset_type: str,  # "images" | "audio" | "video"
    extension: str,
    version: int | None = None
) -> str:
    """
    生成资产路径，自动递增版本号
    例如: /storage/projects/p1/assets/images/shot_001_v03.png
    """
    base_dir = Path(f"storage/projects/{project_id}/assets/{asset_type}")
    base_dir.mkdir(parents=True, exist_ok=True)

    if version is None:
        # 自动查找最大版本号并 +1
        pattern = f"shot_{shot_id:03d}_v*.{extension}"
        existing = list(base_dir.glob(pattern))
        version = len(existing) + 1

    return str(base_dir / f"shot_{shot_id:03d}_v{version:02d}.{extension}")

def get_latest_asset(project_id: str, shot_id: int, asset_type: str, extension: str) -> str | None:
    """获取最新版本的资产路径"""
    base_dir = Path(f"storage/projects/{project_id}/assets/{asset_type}")
    pattern = f"shot_{shot_id:03d}_v*.{extension}"
    files = sorted(base_dir.glob(pattern))
    return str(files[-1]) if files else None

def get_selected_asset(project_id: str, shot_id: int, asset_type: str) -> str | None:
    """获取用户选定的资产路径 (从 selection.json 读取)"""
    selection_file = Path(f"storage/projects/{project_id}/selection.json")
    if selection_file.exists():
        selections = json.loads(selection_file.read_text())
        key = f"{asset_type}/shot_{shot_id:03d}"
        return selections.get(key)
    return None
```

**在 report.html 中展示所有版本**：
```html
<div class="versions">
    <h4>📁 历史版本</h4>
    <div class="version-list">
        <img src="shot_001_v01.png" onclick="selectVersion(1)">
        <img src="shot_001_v02.png" onclick="selectVersion(2)">
        <img src="shot_001_v03.png" onclick="selectVersion(3)" class="selected">
    </div>
    <button onclick="pickVersion()">选择此版本</button>
</div>
```

#### 3.1 关键帧生成 (Text-to-Image)

**生成流程**：
```
分镜脚本 (shot)
      │
      ├─→ 提取 location_id → 获取场景设定
      ├─→ 提取 characters  → 获取角色资产 (LoRA/IP-Adapter)
      ├─→ 提取 visual_prompt
      │
      ▼
┌─────────────────────────────────────────────────────┐
│                   ComfyUI 工作流                      │
│  ┌─────────┐   ┌─────────┐   ┌─────────────────┐   │
│  │  SDXL   │ + │LoRA/IP- │ + │   ControlNet    │   │
│  │  Base   │   │ Adapter │   │  (Pose/Depth)   │   │
│  └─────────┘   └─────────┘   └─────────────────┘   │
└─────────────────────────────────────────────────────┘
      │
      ▼
┌─────────────────┐
│  关键帧图像      │
│  keyframe_001.png
└─────────────────┘
```

| 任务 | 说明 | 工具/技术 |
|------|------|-----------|
| 场景空镜生成 | 无人物的背景图 | SDXL + ControlNet |
| 角色融合 | 将角色放入场景 | IP-Adapter + ControlNet Pose |
| 多角色场景 | 多人同框 | Regional Prompter / Attention Couple |
| 图像增强 | 超分、细节优化 | Real-ESRGAN / 4x-UltraSharp |

#### 3.2 视频片段生成 (Image-to-Video)

| 任务 | 说明 | 工具/技术 |
|------|------|-----------|
| **图生视频 (I2V)** | 关键帧 → 动态视频 | Kling API / Runway Gen-3 / SVD |
| **运镜控制** | 推/拉/摇/移 | Camera Motion 参数 |
| **动态幅度** | 控制运动强度 | Motion Bucket ID |
| **对口型** | 说话场景 | SadTalker / HeyGen |
| **表情驱动** | 面部表情动画 | LivePortrait |

**I2V 参数映射**：
```python
camera_movement_map = {
    "STATIC": {"pan": 0, "tilt": 0, "zoom": 0, "roll": 0},
    "PUSH": {"pan": 0, "tilt": 0, "zoom": 3, "roll": 0},
    "PULL": {"pan": 0, "tilt": 0, "zoom": -3, "roll": 0},
    "PAN": {"pan": 5, "tilt": 0, "zoom": 0, "roll": 0},
    "TILT": {"pan": 0, "tilt": 3, "zoom": 0, "roll": 0},
    # ...
}
```

#### 3.3 音频生成 (Audio Engineering)

##### 3.3.1 语音合成 (TTS)

| 任务 | 说明 | 工具/技术 |
|------|------|-----------|
| **角色配音** | 根据角色声线生成 | GPT-SoVITS (开源首选) |
| **情感控制** | 愤怒/悲伤/低语/欢快 | GPT-SoVITS 情感参数 |
| **多角色对话** | 自动切换声线 | 声线映射表 |
| **旁白** | 画外音 | ElevenLabs / Edge-TTS |

**声线配置 Schema**：
```json
{
  "char_001": {
    "voice_id": "voice_model_001",
    "provider": "gpt-sovits",
    "reference_audio": "/voices/char_001_ref.wav",
    "default_emotion": "neutral",
    "speed": 1.0,
    "pitch": 0
  }
}
```

##### 3.3.2 音效设计 (Foley & SFX)

| 任务 | 说明 | 工具/技术 |
|------|------|-----------|
| **文本音效提取** | 从脚本提取音效关键词 | LLM 分析 |
| **AI 音效生成** | 根据描述生成音效 | AudioLDM / Stable Audio |
| **音效库匹配** | 匹配预置音效 | Freesound API |
| **环境音** | 背景环境声 | AudioLDM |

##### 3.3.3 背景音乐 (BGM)

| 任务 | 说明 | 工具/技术 |
|------|------|-----------|
| **情绪曲线分析** | 分析各场景情绪 | LLM |
| **AI 音乐生成** | 根据情绪生成配乐 | Suno API / Udio |
| **音乐库匹配** | 匹配免版权音乐 | Epidemic Sound API |
| **音乐分段** | 按场景切分配乐 | pydub |

**子目录**：`/asset-engine`

---

### 阶段 4：视频合成层 (Video Composer)
**职责**：时间轴编排、转场、字幕、多轨合成

#### ⚠️ 核心原则：Audio First (音频驱动)

> **时序对齐是 AI 视频最大的隐形坑**

**问题**：
- TTS 音频时长是动态的（取决于语速、停顿）
- I2V 视频时长通常是固定的（SVD: 2-4秒，Kling: 5秒）
- 如果音频 7 秒，视频只有 4 秒 → 画面卡住/黑屏
- 如果视频 5 秒，音频只有 3 秒 → 画面还在动，声音没了

**解决方案：Audio First 流程**
```
Script (分镜)
    │
    ▼
TTS 生成 ──────────────────────────┐
    │                              │
    ▼                              ▼
获取精准时长 (Duration)      生成对应字幕时间戳
    │
    ▼
┌─────────────────────────────────────────────────────┐
│              根据时长决定视频策略                      │
├─────────────────────────────────────────────────────┤
│  音频时长 < 视频时长 (短句)                           │
│  → 视频截断 或 FFmpeg 加速播放                        │
├─────────────────────────────────────────────────────┤
│  音频时长 > 视频时长 (长句)                           │
│  → 方案 A: 视频循环 (loop_count = audio / video)     │
│  → 方案 B: Freeze Frame (最后一帧定格)               │
│  → 方案 C: 生成 Loop 素材 (雨天/火焰等背景)           │
└─────────────────────────────────────────────────────┘
    │
    ▼
时间轴编排 (按音频时长对齐)
```

**时长对齐配置**：
```python
class DurationStrategy(Enum):
    LOOP = "loop"           # 循环播放视频
    FREEZE = "freeze"       # 最后一帧定格
    SPEED_UP = "speed_up"   # 加速播放
    TRUNCATE = "truncate"   # 截断视频

# 默认策略
DEFAULT_STRATEGY = {
    "video_longer": DurationStrategy.TRUNCATE,
    "audio_longer": DurationStrategy.LOOP,
    "max_speed_factor": 1.3,  # 最大加速倍率
    "min_speed_factor": 0.8,  # 最小减速倍率
}
```

| 任务 | 说明 | 工具/技术 |
|------|------|-----------|
| **TTS 时长获取** | 先生成音频，获取精准时长 | pydub.AudioSegment |
| **音频气口处理** | 前后加静音，增加呼吸感 | pydub ⭐ |
| **时长策略计算** | 决定视频处理方式 | 自研 |
| **时间轴构建** | 按音频时长组织素材 | MoviePy / FFmpeg |
| **转场效果** | CUT/DISSOLVE/FADE/WIPE | FFmpeg xfade filter |
| **字幕轨道** | 台词 + 旁白字幕 | ASS/SRT 格式 |
| **字幕样式** | 动态字幕效果 | ASS 特效代码 |
| **音频混音** | 对白 + 音效 + BGM | pydub / FFmpeg |
| **音画同步** | 基于 TTS 时间戳对齐 | 自研 |

#### 音频气口处理 (Audio Padding) ⭐

> **问题**：如果 Shot 1 台词是"你好"，Shot 2 是"再见"
> 没有间隔听起来就是"你好再见"，像机关枪一样不自然

**实现**：
```python
# src/composer/duration.py

from pydub import AudioSegment

def process_audio_with_padding(
    audio_path: str,
    padding_before_ms: int = 200,
    padding_after_ms: int = 300
) -> tuple[AudioSegment, float]:
    """
    给音频前后加静音，让对话有"呼吸感"
    返回: (处理后的音频, 总时长秒数)
    """
    audio = AudioSegment.from_file(audio_path)

    silence_before = AudioSegment.silent(duration=padding_before_ms)
    silence_after = AudioSegment.silent(duration=padding_after_ms)

    # 前后加静音
    padded_audio = silence_before + audio + silence_after

    total_duration_sec = len(padded_audio) / 1000.0
    return padded_audio, total_duration_sec


def calculate_video_strategy(
    audio_duration: float,
    video_duration: float,
    config: dict = None
) -> dict:
    """
    根据音频时长（含气口）计算视频处理策略

    ⚠️ 注意：audio_duration 必须是加了 padding 之后的总时长
    """
    config = config or DEFAULT_STRATEGY

    if audio_duration <= video_duration:
        # 音频短于视频：截断或加速
        speed_factor = video_duration / audio_duration
        if speed_factor <= config["max_speed_factor"]:
            return {"strategy": "speed_up", "factor": speed_factor}
        else:
            return {"strategy": "truncate", "end_time": audio_duration}
    else:
        # 音频长于视频：循环或定格
        loop_count = math.ceil(audio_duration / video_duration)
        return {
            "strategy": "loop",
            "loop_count": loop_count,
            "total_video_duration": audio_duration
        }


# 完整流程示例
def process_shot_audio(shot: Shot, audio_path: str) -> dict:
    """处理单个镜头的音频，返回时长信息"""

    # 1. 加气口
    padded_audio, total_duration = process_audio_with_padding(
        audio_path,
        padding_before_ms=200,
        padding_after_ms=300
    )

    # 2. 保存处理后的音频
    padded_path = audio_path.replace(".wav", "_padded.wav")
    padded_audio.export(padded_path, format="wav")

    # 3. 计算视频策略（使用加了气口的时长）
    video_strategy = calculate_video_strategy(
        audio_duration=total_duration,  # ⭐ 关键：用 padded 后的时长
        video_duration=shot.video_duration
    )

    return {
        "original_audio": audio_path,
        "padded_audio": padded_path,
        "original_duration": len(AudioSegment.from_file(audio_path)) / 1000,
        "padded_duration": total_duration,
        "video_strategy": video_strategy
    }
```

**字幕样式配置**：
```json
{
  "dialogue": {
    "font": "思源黑体",
    "size": 48,
    "color": "#FFFFFF",
    "outline": 2,
    "position": "bottom",
    "animation": "fade"
  },
  "narration": {
    "font": "思源宋体",
    "size": 42,
    "color": "#EEEEEE",
    "outline": 1,
    "position": "bottom",
    "animation": "typewriter"
  }
}
```

**子目录**：`/video-composer`

---

### 阶段 5：渲染引擎 (Render Engine)
**职责**：编码、补帧、超分、多平台格式输出

| 任务 | 说明 | 工具/技术 |
|------|------|-----------|
| **补帧** | 24fps → 60fps | RIFE / GMFSS |
| **超分** | 720p → 4K | Real-ESRGAN / Topaz |
| **视频编码** | H.264 / H.265 / AV1 | FFmpeg |
| **硬件加速** | GPU 编码 | NVENC / VideoToolbox |
| **多规格输出** | 一次渲染多格式 | FFmpeg |
| **封面生成** | 自动截取/AI生成 | 自研 |

**平台输出规格**：
| 平台 | 分辨率 | 帧率 | 编码 | 码率 |
|------|--------|------|------|------|
| YouTube | 3840x2160 | 60fps | H.265 | 40Mbps |
| YouTube | 1920x1080 | 60fps | H.264 | 12Mbps |
| B站 | 1920x1080 | 60fps | H.264 | 10Mbps |
| 抖音/TikTok | 1080x1920 | 60fps | H.264 | 8Mbps |
| 小红书 | 1080x1440 | 30fps | H.264 | 6Mbps |

**子目录**：`/render-engine`

---

### 阶段 6：发布网关 (Publish Gateway)
**职责**：多平台自动发布、元数据生成、数据回收

| 任务 | 说明 | 工具/技术 |
|------|------|-----------|
| **元数据生成** | 标题/描述/标签/封面 | LLM |
| **自动上传** | 各平台上传 | 官方API / Selenium |
| **定时发布** | 排期发布 | APScheduler |
| **数据回收** | 播放量/互动数据 | 平台API |
| **A/B 测试** | 封面/标题测试 | 自研 |

**子目录**：`/publish-gateway`

---

## 3. 项目目录结构

```
videoMaker/                              # 总仓库
├── orchestrator/                        # 工作流编排
│   ├── src/
│   │   ├── pipeline/                   # Pipeline DAG
│   │   ├── scheduler/                  # 任务调度
│   │   ├── comfyui/                    # ComfyUI 集成
│   │   ├── state/                      # 状态管理
│   │   └── api/                        # FastAPI
│   ├── workflows/                      # ComfyUI 工作流 JSON
│   └── configs/                        # 配置文件
│
├── script-engine/                       # 脚本引擎
│   ├── src/
│   │   ├── preprocessor/               # 文本预处理
│   │   ├── extractor/                  # 角色/场景/道具提取
│   │   ├── adapter/                    # 剧本改编
│   │   ├── storyboard/                 # 分镜生成
│   │   └── prompts/                    # Prompt 模板
│   └── schemas/                        # JSON Schema
│
├── character-engine/                    # 角色引擎 ⭐
│   ├── src/
│   │   ├── generator/                  # 角色图像生成
│   │   ├── trainer/                    # LoRA 训练
│   │   ├── adapter/                    # IP-Adapter 管理
│   │   └── bank/                       # 角色资产库管理
│   ├── workflows/                      # ComfyUI 角色生成工作流
│   └── templates/                      # 角色模板
│
├── asset-engine/                        # 素材引擎
│   ├── src/
│   │   ├── image/                      # 关键帧生成
│   │   │   ├── keyframe.py
│   │   │   ├── upscale.py
│   │   │   └── providers/              # SDXL, Flux, MJ...
│   │   ├── video/                      # 视频生成
│   │   │   ├── i2v.py                  # 图生视频
│   │   │   ├── lipsync.py              # 对口型
│   │   │   └── providers/              # Kling, Runway, SVD...
│   │   └── audio/                      # 音频生成
│   │       ├── tts.py                  # 语音合成
│   │       ├── sfx.py                  # 音效
│   │       ├── bgm.py                  # 背景音乐
│   │       └── providers/              # GPT-SoVITS, ElevenLabs...
│   └── workflows/                      # ComfyUI 素材生成工作流
│
├── video-composer/                      # 视频合成
│   ├── src/
│   │   ├── timeline/                   # 时间轴
│   │   ├── transition/                 # 转场效果
│   │   ├── subtitle/                   # 字幕系统
│   │   └── mixer/                      # 音频混音
│   └── templates/                      # 字幕模板
│
├── render-engine/                       # 渲染引擎
│   ├── src/
│   │   ├── interpolate/                # 补帧 (RIFE)
│   │   ├── upscale/                    # 超分 (ESRGAN)
│   │   ├── encoder/                    # 视频编码
│   │   └── adapter/                    # 平台规格适配
│   └── presets/                        # 编码预设
│
├── publish-gateway/                     # 发布网关
│   ├── src/
│   │   ├── platforms/                  # 各平台适配器
│   │   │   ├── youtube.py
│   │   │   ├── bilibili.py
│   │   │   ├── douyin.py
│   │   │   ├── tiktok.py
│   │   │   ├── xiaohongshu.py
│   │   │   └── weixin.py
│   │   ├── metadata/                   # 元数据生成
│   │   └── analytics/                  # 数据回收
│   └── templates/                      # 发布模板
│
├── shared/                              # 共享模块
│   ├── models/                         # Pydantic 数据模型
│   ├── utils/                          # 工具函数
│   ├── providers/                      # AI 服务抽象层
│   └── config/                         # 全局配置
│
├── storage/                             # 存储目录
│   ├── projects/                       # 项目数据
│   │   └── {project_id}/
│   │       ├── world_setting.json
│   │       ├── storyboard.json
│   │       ├── characters/
│   │       ├── assets/
│   │       ├── timeline/
│   │       └── output/
│   ├── cache/                          # 缓存
│   └── models/                         # AI 模型文件
│       ├── checkpoints/
│       ├── loras/
│       └── embeddings/
│
├── comfyui/                             # ComfyUI 配置
│   ├── workflows/                      # 工作流模板
│   └── custom_nodes/                   # 自定义节点
│
├── docker/
│   ├── docker-compose.yml
│   ├── Dockerfile.orchestrator
│   ├── Dockerfile.comfyui
│   └── Dockerfile.worker
│
├── tests/                               # 测试
├── docs/                                # 文档
├── .env.example
├── pyproject.toml
└── README.md
```

---

## 4. 技术栈总览

### 4.1 核心语言
| 用途 | 语言 | 版本 |
|------|------|------|
| 全栈开发 | Python | 3.11+ |

### 4.2 核心工具链

| 类别 | 工具 | 作用 | 优先级 |
|------|------|------|--------|
| **工作流引擎** | ComfyUI | 图像/视频生成编排 | 核心 |
| **图像生成** | SDXL / Flux | 基础模型 | 核心 |
| **一致性控制** | IP-Adapter | 角色一致性 | 核心 |
| **姿势控制** | ControlNet | 人物姿势 | 核心 |
| **LoRA 训练** | Kohya_ss | 角色微调 | 核心 |
| **视频生成** | Kling API | 图生视频 | 核心 |
| **视频生成** | SVD | 图生视频 (开源备选) | 备选 |
| **对口型** | SadTalker | 说话场景 | 核心 |
| **TTS** | GPT-SoVITS | 语音合成 | 核心 (开源) |
| **TTS** | ElevenLabs | 语音合成 | 备选 (商业) |
| **音效** | AudioLDM | AI 音效 | 核心 |
| **补帧** | RIFE | 帧率提升 | 核心 |
| **超分** | Real-ESRGAN | 分辨率提升 | 核心 |
| **视频处理** | FFmpeg | 编码/转码/合成 | 核心 |
| **视频处理** | MoviePy | Python 封装 | 核心 |
| **任务队列** | Celery + Redis | 异步任务 | 核心 |
| **API 框架** | FastAPI | HTTP 接口 | 核心 |
| **数据库** | PostgreSQL | 元数据存储 | 核心 |
| **对象存储** | MinIO | 文件存储 | 核心 |
| **LLM** | Claude API | 文本处理 | 核心 |

### 4.3 AI 服务商矩阵

| 功能 | 开源首选 | 商业 API |
|------|----------|----------|
| 文本生成 | - | Claude API / GPT-4o |
| 图像生成 | SDXL + ComfyUI | Midjourney |
| 视频生成 | SVD | Kling / Runway Gen-3 |
| 语音合成 | GPT-SoVITS | ElevenLabs |
| 音效生成 | AudioLDM | - |
| 音乐生成 | - | Suno / Udio |

---

## 5. 完整数据流

```
┌─────────────────────────────────────────────────────────────────────────────────────┐
│                                  用户输入                                            │
│                        (小说片段 / 剧本 / 主题关键词)                                   │
└─────────────────────────────────────┬───────────────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────────────┐
│  Phase 1: Script Engine                                                             │
│  ┌──────────────┐   ┌──────────────┐   ┌──────────────┐   ┌──────────────────────┐ │
│  │  文本清洗     │ → │ 世界观构建    │ → │ 剧本改编     │ → │  专业分镜脚本生成     │ │
│  └──────────────┘   └──────────────┘   └──────────────┘   └──────────────────────┘ │
│                                                                           ↓         │
│                                                           world_setting.json        │
│                                                           storyboard.json           │
└─────────────────────────────────────┬───────────────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────────────┐
│  Phase 2: Character Engine ⭐                                                        │
│  ┌──────────────┐   ┌──────────────┐   ┌──────────────┐   ┌──────────────────────┐ │
│  │ 角色形象生成  │ → │ 多角度/表情   │ → │ LoRA训练     │ → │  IP-Adapter特征提取  │ │
│  └──────────────┘   └──────────────┘   └──────────────┘   └──────────────────────┘ │
│                                                                           ↓         │
│                                                            /characters/{char_id}/   │
└─────────────────────────────────────┬───────────────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────────────┐
│  Phase 3: Asset Engine                                                              │
│  ┌──────────────────────────────────────────────────────────────────────────────┐  │
│  │  Image: 场景空镜 → 角色融合 → 关键帧 → 超分                                     │  │
│  └──────────────────────────────────────────────────────────────────────────────┘  │
│  ┌──────────────────────────────────────────────────────────────────────────────┐  │
│  │  Video: 关键帧 → I2V生成 → 对口型处理                                          │  │
│  └──────────────────────────────────────────────────────────────────────────────┘  │
│  ┌──────────────────────────────────────────────────────────────────────────────┐  │
│  │  Audio: TTS(情感) → 音效(Foley) → BGM(情绪)                                    │  │
│  └──────────────────────────────────────────────────────────────────────────────┘  │
│                                                                           ↓         │
│                                                             /assets/{type}/{id}/    │
└─────────────────────────────────────┬───────────────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────────────┐
│  Phase 4: Video Composer                                                            │
│  ┌──────────────┐   ┌──────────────┐   ┌──────────────┐   ┌──────────────────────┐ │
│  │ 时间轴构建    │ → │ 转场添加     │ → │ 字幕叠加     │ → │  音频混音            │ │
│  └──────────────┘   └──────────────┘   └──────────────┘   └──────────────────────┘ │
│                                                                           ↓         │
│                                                                    draft.mp4        │
└─────────────────────────────────────┬───────────────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────────────┐
│  Phase 5: Render Engine                                                             │
│  ┌──────────────┐   ┌──────────────┐   ┌──────────────┐   ┌──────────────────────┐ │
│  │ 补帧 (RIFE)  │ → │ 超分 (ESRGAN)│ → │ 编码 (H.265) │ → │  多规格导出          │ │
│  └──────────────┘   └──────────────┘   └──────────────┘   └──────────────────────┘ │
│                                                                           ↓         │
│                                                            final_{platform}.mp4     │
└─────────────────────────────────────┬───────────────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────────────┐
│  Phase 6: Publish Gateway                                                           │
│  ┌──────────────┐   ┌──────────────┐   ┌──────────────┐   ┌──────────────────────┐ │
│  │ 元数据生成    │ → │ 封面生成     │ → │ 自动上传     │ → │  数据回收            │ │
│  └──────────────┘   └──────────────┘   └──────────────┘   └──────────────────────┘ │
│                                                                           ↓         │
│                                               YouTube / B站 / 抖音 / TikTok / ...    │
└─────────────────────────────────────────────────────────────────────────────────────┘
```

---

## 6. 关键检查点 (Human-in-the-Loop)

为保证质量，以下环节建议人工审核：

| 检查点 | 阶段 | 审核内容 | 自动化程度 |
|--------|------|----------|------------|
| **CP1** | Script | 世界观设定审核 | 可选 |
| **CP2** | Script | 分镜脚本审核 | 建议 |
| **CP3** | Character | 角色定妆照审核 | **必须** |
| **CP4** | Asset | 关键帧质量审核 | 建议 |
| **CP5** | Composer | 成片预览审核 | 建议 |
| **CP6** | Publish | 发布前终审 | 可选 |

**CP3 角色定妆照审核**是最关键的检查点，因为后续所有画面的角色一致性都依赖于此。

---

## 7. 已确认配置

| 配置项 | 选择 | 影响 |
|--------|------|------|
| 视频类型 | **混合支持** | 需支持图文模式和AI视频模式 |
| 目标平台 | **全平台** | 需适配6+平台的规格 |
| 部署架构 | **混合** | 本地编排 + 云端GPU |

---

## 8. 开发路线图 (稳定性优先)

> **当前目标**：完成稳定的视频生成流程，发布与数据分析模块延后

### 🎯 Phase 1: 核心 MVP (最小可行产品)

**目标**：跑通一条完整的视频生成流程

#### 1.1 基础设施
- [ ] 项目骨架初始化
- [ ] 数据模型定义 (Pydantic Schema)
- [ ] 简易 Pipeline 框架（顺序执行）
- [ ] 错误处理与日志系统

#### 1.2 脚本引擎 (简化版)
- [ ] 世界观设定手动输入/模板
- [ ] 分镜脚本 LLM 生成
- [ ] JSON Schema 校验

#### 1.3 角色引擎 (基础版)
- [ ] 单角色定妆照生成 (ComfyUI + SDXL)
- [ ] IP-Adapter 集成（角色一致性）
- [ ] 角色资产本地存储

#### 1.4 素材引擎 (图文模式优先)
- [ ] 关键帧生成 (ComfyUI)
- [ ] TTS 语音生成 (Edge-TTS 先行，稳定)
- [ ] 基础音频处理

#### 1.5 视频合成 (基础版)
- [ ] 时间轴编排 (MoviePy)
- [ ] 基础字幕叠加
- [ ] 音视频合成

#### 1.6 渲染输出
- [ ] 单规格视频编码 (H.264 1080p)
- [ ] 基础质量检查

**Phase 1 交付物**：能够从文本输入生成一个完整的图文解说视频

---

### 🚀 Phase 2: 能力增强

**目标**：提升质量与功能覆盖

#### 2.1 角色引擎增强
- [ ] 多角色支持
- [ ] LoRA 训练 Pipeline
- [ ] 表情/姿势变体

#### 2.2 素材引擎增强
- [ ] I2V 视频生成 (Kling/SVD)
- [ ] 对口型处理 (SadTalker)
- [ ] GPT-SoVITS 情感 TTS
- [ ] AI 音效生成 (AudioLDM)
- [ ] BGM 自动匹配

#### 2.3 合成增强
- [ ] 转场效果
- [ ] 字幕动效
- [ ] 多轨混音

#### 2.4 渲染增强
- [ ] 补帧 (RIFE)
- [ ] 超分 (Real-ESRGAN)
- [ ] 多规格输出

**Phase 2 交付物**：支持 AI 视频片段 + 高质量后期处理

---

### 📦 Phase 3: 生产化 (延后)

- [ ] Celery 异步任务队列
- [ ] 任务断点恢复
- [ ] 批量生产支持
- [ ] Web UI / API

---

### 🌐 Phase 4: 发布闭环 (延后)

- [ ] 多平台发布
- [ ] 数据回收
- [ ] 自动化运营

---

## 9. 稳定性设计原则

### 9.1 错误处理策略

| 层级 | 策略 | 说明 |
|------|------|------|
| **任务级** | 重试 3 次 | 单个任务失败自动重试 |
| **阶段级** | 检查点保存 | 每阶段完成后保存中间产物 |
| **流程级** | 断点续跑 | 从失败点继续，无需从头开始 |

> **Phase 1 原则**：LLM 输出 JSON 格式错误时，直接抛错人工改。
> 早期调试 Prompt 比写复杂的重试逻辑更重要。

### 9.2 显存管理 (VRAM Lock) ⚠️ 关键

> **AI 视频流程对显存极其敏感，并发执行会导致显存爆炸**

**风险场景**：
- 同时运行 LLM (本地) + SDXL 生成 + RIFE 补帧 → 显存溢出

**MacBook 特别警告**：
- 统一内存架构，GPU/CPU 共享内存
- 更容易触发内存压力，导致系统卡死

**Phase 1 强制规则**：
```python
# ❌ 不要这样做
async def generate_all():
    await asyncio.gather(
        generate_images(),      # GPU
        generate_tts(),         # CPU/GPU
        run_lora_inference(),   # GPU
    )

# ✅ Phase 1 严格串行化
def generate_all():
    generate_images()        # 完成后释放显存
    generate_tts()           # 开始下一步
    run_lora_inference()     # 开始下一步
```

**Phase 2+ 资源锁机制**：
```python
class VRAMLock:
    """全局显存互斥锁"""

    def __init__(self, max_vram_gb: float = 8.0):
        self.lock = threading.Lock()
        self.max_vram = max_vram_gb
        self.current_usage = 0.0

    def acquire(self, required_vram: float, timeout: float = 300):
        """获取显存锁，等待直到有足够显存"""
        start = time.time()
        while True:
            with self.lock:
                if self.current_usage + required_vram <= self.max_vram:
                    self.current_usage += required_vram
                    return True
            if time.time() - start > timeout:
                raise TimeoutError("VRAM acquire timeout")
            time.sleep(1)

    def release(self, vram: float):
        """释放显存"""
        with self.lock:
            self.current_usage = max(0, self.current_usage - vram)

# 使用示例
vram_lock = VRAMLock(max_vram_gb=8.0)

def generate_image():
    vram_lock.acquire(required_vram=4.0)  # SDXL 需要 ~4GB
    try:
        # 执行图像生成
        ...
    finally:
        vram_lock.release(4.0)
```

### 9.3 中间产物持久化

```
/storage/projects/{project_id}/
├── checkpoints/
│   ├── 01_script.json          # 脚本完成
│   ├── 02_characters.json      # 角色完成
│   ├── 03_assets.json          # 素材完成
│   ├── 04_timeline.json        # 时间轴完成
│   └── 05_render.json          # 渲染完成
├── assets/                      # 实际素材文件
└── output/                      # 最终输出
```

### 9.4 降级策略

| 模块 | 首选方案 | 降级方案 |
|------|----------|----------|
| 图像生成 | SDXL + ComfyUI | DALL-E 3 API |
| 视频生成 | Kling API | 图片 + Ken Burns |
| TTS | GPT-SoVITS | Edge-TTS (免费稳定) |
| 音效 | AudioLDM | 静音 / 预置音效库 |

### 9.5 超时与熔断

| 任务类型 | 超时时间 | 熔断条件 |
|----------|----------|----------|
| LLM 调用 | 60s | 连续 3 次超时 |
| 图像生成 | 120s | 连续 3 次失败 |
| 视频生成 | 300s | 连续 2 次失败 |
| TTS | 60s | 连续 3 次失败 |

### 9.6 质量检查门控

| 检查点 | 检查内容 | 不通过处理 |
|--------|----------|------------|
| 分镜脚本 | JSON Schema 校验 | **直接抛错，人工修改 Prompt** |
| 角色图像 | 人脸检测 | 重新生成 |
| 关键帧 | 分辨率/格式 | 重新生成 |
| TTS 音频 | 时长匹配 | 调速/重生成 |
| 最终视频 | 时长/编码 | 报错终止 |

---

## 10. 开发模式 (Phase 1)

### 10.1 CLI 优先，砍掉 Web UI

> **调试命令行比测接口快得多**

```bash
# Phase 1 入口
python main.py --input "story.txt" --output "./output"

# 或分步执行
python main.py script --input "story.txt"           # 仅生成脚本
python main.py character --project-id "xxx"         # 仅生成角色
python main.py assets --project-id "xxx"            # 仅生成素材
python main.py compose --project-id "xxx"           # 仅合成视频
python main.py render --project-id "xxx"            # 仅渲染输出

# 从检查点恢复
python main.py resume --project-id "xxx" --from-step "assets"
```

**CLI 参数设计**：
```python
@click.command()
@click.option("--input", "-i", type=click.Path(exists=True), help="输入文本文件")
@click.option("--output", "-o", type=click.Path(), default="./output", help="输出目录")
@click.option("--config", "-c", type=click.Path(), help="配置文件路径")
@click.option("--debug", is_flag=True, help="开启调试模式")
@click.option("--dry-run", is_flag=True, help="仅生成计划，不执行")
def main(input, output, config, debug, dry_run):
    ...
```

### 10.2 Debug Viewer (report.html) ⭐ 必须实现

> **全流程自动化时，你不知道 AI 在哪一步"理解歪了"**

**每跑完一步，追加到 report.html，展示**：
- 分镜描述 → 对应的 Prompt → 生成的图
- 方便快速定位问题

**report.html 结构**：
```html
<!DOCTYPE html>
<html>
<head>
    <title>Pipeline Debug Report - {project_id}</title>
    <style>
        .shot { border: 1px solid #ccc; margin: 20px; padding: 15px; }
        .shot-header { font-weight: bold; background: #f0f0f0; padding: 10px; }
        .prompt { background: #fffbe6; padding: 10px; font-family: monospace; }
        .image { max-width: 512px; }
        .error { background: #ffe6e6; color: red; }
        .success { background: #e6ffe6; }
    </style>
</head>
<body>
    <h1>Project: {project_name}</h1>
    <p>Generated: {timestamp}</p>

    <!-- Shot 1 -->
    <div class="shot">
        <div class="shot-header">Shot #1 - ELS - CRANE</div>
        <div class="section">
            <h4>📝 分镜描述</h4>
            <p>在那个风雨交加的夜晚...</p>
        </div>
        <div class="section">
            <h4>🎨 Visual Prompt</h4>
            <div class="prompt">A dark stormy night, lightning strikes over an old mansion...</div>
        </div>
        <div class="section">
            <h4>🖼️ 生成结果</h4>
            <img class="image" src="./assets/shot_001.png">
            <p class="success">✅ 生成成功 (seed: 12345, 耗时: 8.2s)</p>
        </div>
    </div>

    <!-- Shot 2 (Error Example) -->
    <div class="shot">
        <div class="shot-header">Shot #2 - CU - STATIC</div>
        <div class="section">
            <h4>📝 分镜描述</h4>
            <p>他紧握双拳，面部肌肉抽搐</p>
        </div>
        <div class="section">
            <h4>🎨 Visual Prompt</h4>
            <div class="prompt">Close-up of a young man's face, angry expression...</div>
        </div>
        <div class="section">
            <h4>🖼️ 生成结果</h4>
            <p class="error">❌ 人脸检测失败，重试中... (attempt 2/3)</p>
        </div>
    </div>

</body>
</html>
```

**Python 生成器**：
```python
class DebugReporter:
    """调试报告生成器"""

    def __init__(self, project_id: str, output_dir: str):
        self.project_id = project_id
        self.output_dir = output_dir
        self.report_path = os.path.join(output_dir, "report.html")
        self._init_report()

    def _init_report(self):
        """初始化报告 HTML"""
        ...

    def add_shot_result(
        self,
        shot: Shot,
        prompt: str,
        image_path: str | None,
        success: bool,
        error_msg: str = "",
        metadata: dict = None
    ):
        """添加一个镜头的生成结果"""
        ...

    def add_stage_summary(self, stage: str, status: str, duration: float):
        """添加阶段摘要"""
        ...

    def finalize(self):
        """完成报告"""
        ...

# 使用示例
reporter = DebugReporter(project_id, output_dir)

for shot in shots:
    prompt = generate_prompt(shot)
    try:
        image_path = generate_image(prompt)
        reporter.add_shot_result(shot, prompt, image_path, success=True)
    except Exception as e:
        reporter.add_shot_result(shot, prompt, None, success=False, error_msg=str(e))

reporter.finalize()
print(f"Debug report: {reporter.report_path}")
```

### 10.3 Prompt 模板独立化

> **Prompt 需要像代码一样迭代（Prompt Engineering）**
> **频繁调整 Prompt 不应该需要重启服务**

**不要这样做** ❌：
```python
def generate_script(text: str) -> str:
    prompt = f"""你是一个专业的编剧...
    请将以下文本改编为视频脚本：
    {text}
    输出格式：JSON
    ..."""
    return llm.generate(prompt)
```

**应该这样做** ✅：
```
/src/script/prompts/
├── world_setting.jinja2       # 世界观提取
├── storyboard.jinja2          # 分镜生成
├── visual_prompt.jinja2       # 画面 Prompt 生成
└── README.md                   # Prompt 说明文档
```

```jinja2
{# storyboard.jinja2 #}
你是一位专业的分镜师，擅长将文学作品转化为视觉语言。

## 任务
将以下剧本片段转化为专业的分镜脚本。

## 世界观设定
{{ world_setting | tojson }}

## 剧本内容
{{ script_content }}

## 输出要求
- 严格按照 JSON Schema 输出
- 每个镜头必须包含：shot_type, camera_movement, duration, visual_prompt
- visual_prompt 必须是英文，适合图像生成 AI

## JSON Schema
```json
{{ schema | tojson }}
```

请输出：
```

```python
from jinja2 import Environment, FileSystemLoader

class PromptManager:
    """Prompt 模板管理器"""

    def __init__(self, template_dir: str = "src/script/prompts"):
        self.env = Environment(
            loader=FileSystemLoader(template_dir),
            autoescape=False
        )
        self._cache = {}

    def render(self, template_name: str, **kwargs) -> str:
        """渲染 Prompt 模板"""
        template = self.env.get_template(template_name)
        return template.render(**kwargs)

    def reload(self):
        """重新加载所有模板（热更新）"""
        self.env.cache.clear()
        self._cache.clear()

# 使用示例
prompts = PromptManager()

prompt = prompts.render(
    "storyboard.jinja2",
    world_setting=world_setting,
    script_content=script_content,
    schema=STORYBOARD_SCHEMA
)
result = llm.generate(prompt)
```

---

## 11. 简化后的目录结构 (Phase 1)

```
videoMaker/
├── src/
│   ├── pipeline/                # 简易流程编排
│   │   ├── __init__.py
│   │   ├── runner.py           # Pipeline 执行器
│   │   └── checkpoint.py       # 检查点管理
│   │
│   ├── script/                  # 脚本引擎
│   │   ├── __init__.py
│   │   ├── generator.py        # 分镜生成
│   │   ├── schema.py           # 数据模型
│   │   └── prompts/            # Prompt 模板 ⭐
│   │       ├── world_setting.jinja2
│   │       ├── storyboard.jinja2
│   │       └── visual_prompt.jinja2
│   │
│   ├── character/               # 角色引擎
│   │   ├── __init__.py
│   │   ├── generator.py        # 角色图像生成
│   │   └── consistency.py      # 一致性控制
│   │
│   ├── asset/                   # 素材引擎
│   │   ├── __init__.py
│   │   ├── image.py            # 关键帧生成
│   │   ├── audio.py            # TTS + 音效
│   │   └── video.py            # 视频片段 (Phase 2)
│   │
│   ├── composer/                # 视频合成
│   │   ├── __init__.py
│   │   ├── timeline.py         # 时间轴
│   │   ├── subtitle.py         # 字幕
│   │   ├── mixer.py            # 混音
│   │   └── duration.py         # 时长策略 (Audio First) ⭐
│   │
│   ├── render/                  # 渲染输出
│   │   ├── __init__.py
│   │   └── encoder.py          # 编码器
│   │
│   ├── debug/                   # 调试工具 ⭐
│   │   ├── __init__.py
│   │   └── reporter.py         # Debug Viewer (report.html)
│   │
│   └── shared/                  # 共享模块
│       ├── __init__.py
│       ├── models.py           # Pydantic 模型
│       ├── config.py           # 配置管理
│       ├── logger.py           # 日志
│       ├── exceptions.py       # 自定义异常
│       ├── prompts.py          # PromptManager
│       └── comfyui.py          # ComfyWorkflow Builder ⭐
│
├── comfyui/
│   └── workflows/              # ComfyUI 工作流 JSON
│       ├── base/
│       ├── character/
│       └── keyframe/
│
├── storage/
│   ├── projects/               # 项目数据
│   ├── models/                 # AI 模型
│   └── cache/                  # 缓存
│
├── tests/                       # 测试
├── scripts/                     # 辅助脚本
├── main.py                      # CLI 入口 ⭐
├── .env.example
├── pyproject.toml
├── requirements.txt
└── README.md
```

---

## 12. 已确认配置

| 配置项 | 选择 | 影响 |
|--------|------|------|
| 视频类型 | **混合支持** | 需支持图文模式和AI视频模式 |
| 目标平台 | **全平台** | 需适配6+平台的规格 |
| 部署架构 | **混合** | 本地编排 + 云端GPU |
| **当前优先级** | **视频生成** | 发布/分析模块延后 |
| **设计原则** | **稳定性优先** | 完善错误处理、降级策略 |

---

## 13. 多语言支持策略 (Python + TypeScript)

> **核心原则**：Python 处理 AI Pipeline，TypeScript 处理开发者体验层

### 13.1 语言分工

| 层级 | 推荐语言 | 理由 |
|------|----------|------|
| **AI Pipeline 核心** | Python | ComfyUI/SDXL/FFmpeg 生态 |
| **CLI 工具** | Python 或 TypeScript | 都可以，看个人偏好 |
| **Debug Viewer** | TypeScript | 前端交互更自然 |
| **Web UI (Phase 3+)** | TypeScript | React/Vue 生态 |
| **配置管理工具** | TypeScript | JSON Schema 处理更顺手 |

### 13.2 推荐的 TypeScript 使用场景

#### 场景 A: Debug Viewer 增强版
```
/tools/debug-viewer/           # TypeScript 项目
├── src/
│   ├── index.ts              # 入口
│   ├── watcher.ts            # 文件监听，热更新
│   ├── server.ts             # 本地 HTTP 服务
│   └── renderer.ts           # 渲染 report.html
├── package.json
└── tsconfig.json
```

```typescript
// tools/debug-viewer/src/watcher.ts
import chokidar from 'chokidar';
import { WebSocketServer } from 'ws';

// 监听 storage/projects 变化，实时刷新浏览器
const watcher = chokidar.watch('storage/projects/**/assets/**', {
  persistent: true
});

watcher.on('add', (path) => {
  console.log(`New asset: ${path}`);
  // 通过 WebSocket 通知前端刷新
  broadcast({ type: 'asset_added', path });
});
```

#### 场景 B: 项目初始化 CLI (可选)
```bash
# 如果你更擅长 TS，可以用 TS 写 CLI
npx videomaker init --name "my-project"
npx videomaker validate --config ./project.yaml
```

#### 场景 C: JSON Schema 校验工具
```typescript
// tools/schema-validator/src/index.ts
import Ajv from 'ajv';
import { WorldSettingSchema, StoryboardSchema } from './schemas';

export function validateWorldSetting(data: unknown): ValidationResult {
  const ajv = new Ajv();
  const validate = ajv.compile(WorldSettingSchema);
  // ...
}
```

### 13.3 项目结构 (混合语言)

```
videoMaker/
├── src/                        # Python 核心
│   ├── pipeline/
│   ├── script/
│   └── ...
│
├── tools/                      # TypeScript 工具 (可选)
│   ├── debug-viewer/          # 调试查看器
│   │   ├── src/
│   │   ├── package.json
│   │   └── tsconfig.json
│   │
│   ├── schema-validator/      # Schema 校验
│   │   └── ...
│   │
│   └── project-cli/           # 项目管理 CLI (可选)
│       └── ...
│
├── main.py                     # Python CLI 入口
├── pyproject.toml
└── package.json                # 根目录 workspace (可选)
```

### 13.4 跨语言通信

如果需要 Python 和 TypeScript 协作：

**方案 A: 文件系统 (推荐 Phase 1)**
```
Python 生成 → JSON 文件 → TypeScript 读取展示
```

**方案 B: HTTP API (Phase 2+)**
```
Python FastAPI ←→ TypeScript fetch
```

**方案 C: 子进程调用**
```typescript
// TypeScript 调用 Python
import { spawn } from 'child_process';

const result = spawn('python', ['main.py', 'script', '--input', 'story.txt']);
```

### 13.5 建议

| 阶段 | 建议 |
|------|------|
| **Phase 1** | 纯 Python，快速验证核心流程 |
| **Phase 1.5** | 如果 Debug Viewer 需要交互，用 TS 写增强版 |
| **Phase 2+** | 可以引入 TS 做 Web UI / 高级工具 |

> **核心原则**：不要为了用 TS 而用 TS
> 只在 TS 明显更合适的场景（前端交互、JSON处理）才引入

---

*文档版本: v1.3*
*最后更新: 2026-01-13*
