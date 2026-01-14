# VideoMaker - AI 视频自动化生成系统

一套模块化的 AI 视频全流程自动化工具，从文本输入到成片输出。

## 快速开始

### 1. 环境准备

```bash
# 创建虚拟环境
python -m venv venv （后面就不用执行了）
source venv/bin/activate  # macOS/Linux
# venv\Scripts\activate   # Windows

# 安装依赖
pip install -e .
# 或
pip install -r requirements.txt
```

### 2. 配置

复制并编辑环境变量文件：

```bash
cp .env.example .env
```

编辑 `.env` 文件：

```env
# LLM 配置 (用于脚本生成)
LLM_PROVIDER=anthropic          # anthropic 或 openai
LLM_API_KEY=your_api_key_here
LLM_MODEL=claude-3-5-sonnet-20241022

# ComfyUI 配置 (用于图像生成)
COMFYUI_HOST=127.0.0.1
COMFYUI_PORT=8188

# TTS 配置
TTS_PROVIDER=edge-tts
TTS_VOICE=zh-CN-XiaoxiaoNeural  # 中文女声

# 视频输出配置
VIDEO_WIDTH=1920
VIDEO_HEIGHT=1080
VIDEO_FPS=30
```

### 3. 启动 ComfyUI

确保 ComfyUI 服务正在运行：

```bash
# 在 ComfyUI 目录下
python main.py --listen 127.0.0.1 --port 8188
```

## 使用方法

### 方式一：完整流水线（推荐）

```bash
# 从文本文件生成完整视频
python main.py --input story.txt --output ./output

# 指定项目 ID
python main.py --input story.txt --output ./output --project-id my_video_001
```

### 方式二：分步执行

#### Step 1: 生成脚本和分镜

```bash
python main.py script --input story.txt --project-id my_video
```

输出：
- `storage/projects/my_video/world_setting.json` - 世界观设定
- `storage/projects/my_video/storyboard.json` - 分镜脚本

#### Step 2: 生成角色参考图（可选）

```bash
python main.py character --project-id my_video
```

输出：
- `storage/projects/my_video/assets/characters/` - 角色参考图

#### Step 3: 生成图像和音频

```bash
python main.py assets --project-id my_video
```

输出：
- `storage/projects/my_video/assets/images/` - 分镜图片
- `storage/projects/my_video/assets/audio/` - TTS 音频

#### Step 4: 合成时间线

```bash
python main.py compose --project-id my_video
```

输出：
- `storage/projects/my_video/timeline.json` - 时间线
- `storage/projects/my_video/subtitles.srt` - 字幕文件

#### Step 5: 渲染视频

```bash
python main.py render --project-id my_video
```

输出：
- `storage/projects/my_video/output/final.mp4` - 最终视频

### 方式三：断点续传

如果流程中断，可以从指定步骤恢复：

```bash
# 从 assets 步骤继续
python main.py resume --project-id my_video --from-step assets

# 查看项目状态
python main.py status --project-id my_video
```

## 输入文件格式

### 简单文本 (story.txt)

```
从前有一个年轻的程序员叫小明，他每天都在电脑前工作到深夜。

有一天，他发现了一个神奇的 AI 工具，可以自动生成视频。

小明非常兴奋，开始尝试用它来创作自己的故事...
```

### 结构化脚本 (story.json)

```json
{
  "title": "小明的故事",
  "global_style": "anime style, soft lighting, warm colors",
  "scenes": [
    {
      "description": "小明在电脑前工作",
      "narration": "从前有一个年轻的程序员叫小明",
      "duration": 5
    },
    {
      "description": "小明发现 AI 工具",
      "narration": "有一天，他发现了一个神奇的 AI 工具",
      "duration": 4
    }
  ]
}
```

## 调试与检查

### 查看调试报告

每次运行后会生成 HTML 调试报告：

```bash
open storage/projects/my_video/report.html
```

报告包含：
- 流水线执行状态
- 每个镜头的 Prompt 和生成结果
- 错误信息和警告
- 资源版本历史

### 重新生成单个镜头

如果某个镜头效果不满意，可以单独重新生成：

```bash
# 重新生成镜头 3 的图片（会创建新版本 v02, v03...）
python main.py regenerate --project-id my_video --shot 3
```

### 选择资源版本

```bash
# 选择镜头 3 使用 v02 版本的图片
python main.py select --project-id my_video --shot 3 --version 2
```

## 目录结构

```
storage/projects/{project_id}/
├── world_setting.json      # 世界观设定
├── storyboard.json         # 分镜脚本
├── timeline.json           # 时间线
├── subtitles.srt           # 字幕文件
├── selection.json          # 资源版本选择
├── report.html             # 调试报告
├── checkpoints/            # 断点检查点
├── assets/
│   ├── images/
│   │   ├── shot_001_v01.png
│   │   ├── shot_001_v02.png  # 重新生成的版本
│   │   ├── shot_002_v01.png
│   │   └── ...
│   ├── audio/
│   │   ├── shot_001_v01.wav
│   │   ├── shot_001_v01_padded.wav
│   │   └── ...
│   └── characters/
│       ├── char_001_ref_0.png
│       └── ...
└── output/
    ├── final.mp4           # 最终视频
    └── preview.mp4         # 预览视频
```

## 配置选项

### config.yaml（可选）

```yaml
# 全局样式
global_style: "cinematic lighting, film grain, 8k quality"

# 角色一致性设置
character:
  tier1_lora_strength: 0.8      # LoRA 强度
  tier2_ip_adapter_weight: 0.7  # IP-Adapter 权重

# 音频设置
audio:
  padding_before_ms: 200        # 音频前静音
  padding_after_ms: 300         # 音频后静音
  voice: zh-CN-XiaoxiaoNeural   # TTS 声音

# 视频设置
video:
  width: 1920
  height: 1080
  fps: 30
  codec: libx264
  preset: medium
```

## 常见问题

### Q: ComfyUI 连接失败

```
ComfyUIError: ComfyUI server not available
```

**解决方案：**
1. 确保 ComfyUI 已启动
2. 检查端口是否正确（默认 8188）
3. 检查防火墙设置

### Q: LLM API 调用失败

```
LLMError: API call failed
```

**解决方案：**
1. 检查 `.env` 中的 API Key
2. 确认网络连接
3. 检查 API 配额

### Q: 生成的图像不一致

**解决方案：**
1. 为主角创建 Tier 1 角色（需要训练 LoRA）
2. 或使用 Tier 2 角色（Reference Atlas + IP-Adapter）
3. 确保 `global_style` 在所有镜头中保持一致

### Q: 视频时长与音频不匹配

系统使用 **Audio First** 原则，自动处理时长对齐：
- 音频较长：图片/视频会循环或延长
- 音频较短：图片/视频会加速或截断

### Q: 如何使用自定义 ComfyUI 工作流

1. 在 ComfyUI 中设计工作流
2. 导出为 API 格式 JSON
3. 保存到 `workflows/` 目录
4. 在配置中指定使用

## 技术架构

```
┌─────────────────────────────────────────────────────────┐
│                    CLI Entry (main.py)                  │
└─────────────────────────┬───────────────────────────────┘
                          │
┌─────────────────────────▼───────────────────────────────┐
│                  Pipeline Runner                         │
│   [script] → [character] → [assets] → [compose] → [render]
└─────────────────────────┬───────────────────────────────┘
                          │
    ┌─────────────────────┼─────────────────────┐
    ▼                     ▼                     ▼
┌────────┐          ┌──────────┐          ┌─────────┐
│ Script │          │  Asset   │          │ Compose │
│Generator│         │Generator │          │  Engine │
└────┬───┘          └────┬─────┘          └────┬────┘
     │                   │                     │
     ▼                   ▼                     ▼
  LLM API           ComfyUI API          Timeline Builder
  (Claude/GPT)      + edge-tts           + Subtitle Generator
                                         + Audio Mixer
```

## 核心设计原则

### Audio First（音频优先）

音频是时长的真理源。流程如下：
1. 先生成 TTS 音频
2. 获取精确时长
3. 根据音频时长决定视频/图片处理策略

### 资源版本管理

所有生成的资源都有版本号：
- `shot_001_v01.png` → 第一次生成
- `shot_001_v02.png` → 重新生成
- 可以自由选择任意版本用于最终渲染

### 角色一致性分层

| 层级 | 方案 | 一致性 | 成本 |
|------|------|--------|------|
| Tier 1 | LoRA + IP-Adapter | 最高 | 需训练 |
| Tier 2 | Reference Atlas + IP-Adapter | 中等 | 自动生成 |
| Tier 3 | 仅 Prompt 描述 | 较低 | 零成本 |

## License

MIT License
