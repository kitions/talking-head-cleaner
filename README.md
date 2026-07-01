# talking-head-cleaner

Local-first talking-head video cleaner for removing filler words and awkward pauses with Whisper timestamps and FFmpeg cuts.

本地优先的口播视频粗剪工具。它使用本地 Whisper 系列模型定位“嗯、呃、额、啊、唔”等语气词，再用 FFmpeg 同步裁剪画面和声音，适合把单人口播素材快速整理成更干净的初剪版本。

定位：单人口播 / 本地批量粗剪。  
不是：通用短视频包装工具、字幕工具、多人对话剪辑器。

## GitHub 描述建议

如果要填写 GitHub 仓库 About 描述，可以使用：

```text
Local-first talking-head video cleaner that removes filler words and awkward pauses using Whisper timestamps and FFmpeg.
```

中文描述：

```text
本地优先的口播视频粗剪工具，基于 Whisper 词级时间戳和 FFmpeg 自动清理“嗯、呃、啊”等语气词与长停顿。
```

## 项目简介

`talking-head-cleaner` 面向单人口播素材：先用本地 ASR 模型生成逐字稿和词级时间戳，再通过规则引擎识别明确的 filler、长停顿和待复核片段，最后调用 FFmpeg 同步裁剪音频与画面。所有处理默认在本机完成，源文件只读，输出包含成片、剪辑 manifest、复核结果和汇总报告。

## 能做什么

- 批量扫描输入目录里的 `.mp4`；
- 本地转写并生成词级时间戳；
- 自动删除明确独立的 filler；
- 缩短过长停顿；
- 可选做一轮成片复核补切；
- 输出成片、manifest、verification、report；
- 默认不上传云端，不覆盖源文件。
- 默认即使没有切点也会用 FFmpeg 规范化输出；如需无切点直接复制源文件，可加 `--copy-when-no-cuts`。

## 安装

需要 Python 3.12、FFmpeg 和 ffprobe。

macOS 可先安装 FFmpeg：

```bash
brew install ffmpeg
```

创建虚拟环境并安装通用 CPU 依赖：

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -r requirements.txt
```

如果没有 `python3.12`，也可以先用系统已有的 Python 3.11+ 尝试。

macOS Apple Silicon 如果想启用 MLX Whisper 主模型，再安装可选依赖：

```bash
pip install -r requirements-macos-mlx.txt
```

Windows / Linux 默认使用 CPU-only 模式，不安装 MLX。

Windows PowerShell 示例：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -U pip
pip install -r requirements.txt
```

Windows 还需要单独安装 FFmpeg，并确认下面两个命令能输出版本信息：

```powershell
ffmpeg -version
ffprobe -version
```

## 快速开始

准备输入目录：

```bash
mkdir -p ./input_videos
```

把待处理的 `.mp4` 放入 `./input_videos`。

先 dry-run，确认能扫描到文件：

```bash
python scripts/talking_head_cleaner.py \
  --input ./input_videos \
  --output ./output_project \
  --mode aggressive \
  --dry-run
```

正式处理：

```bash
python scripts/talking_head_cleaner.py \
  --input ./input_videos \
  --output ./output_project \
  --mode aggressive \
  --max-refine-rounds 1
```

如果希望 manifest 记录源文件 sha256，可加 `--hash-sources`。默认不计算 hash，避免 dry-run 或大文件扫描变慢。

如果当前环境没有可用 Apple Metal/GPU，MLX Whisper 可能报 `No Metal device available`。这时用 CPU-only 模式：

```bash
python scripts/talking_head_cleaner.py \
  --input ./input_videos \
  --output ./output_project \
  --mode aggressive \
  --max-refine-rounds 1 \
  --skip-primary
```

Windows 必须使用 CPU-only 模式：

```powershell
python scripts\talking_head_cleaner.py `
  --input .\input_videos `
  --output .\output_project `
  --mode aggressive `
  --max-refine-rounds 1 `
  --skip-primary
```

## 输出目录

```text
output_project/
├── analysis/          # 转写结果和中间分析
├── final/             # 最终成片
├── manifests/         # 每条视频的剪辑决策记录
├── verification/      # 成片复核转写
├── waveforms/         # 预留：切点波形图
├── work/              # 中间工作目录
└── report.md          # 汇总报告
```

成片示例：

```text
final/sample_01_roughcut_aggressive.mp4
final/sample_01_roughcut_aggressive_r1.mp4
```

如果 `--max-refine-rounds 1` 后发现 residual filler，会生成 `_r1` 补切版本，并把它作为 manifest 里的 `final_output`。

## 输出质量与重编码

当前工具会用 FFmpeg 重新编码输出视频；即使没有切点，默认也会重新编码以保持输出规格一致。重编码理论上会带来轻微画质损耗，但默认参数偏高质量，口播视频通常肉眼不明显。

默认输出参数：

```text
视频编码：H.264 libx264
质量控制：CRF 18
preset：medium
像素格式：yuv420p
帧率：30fps
音频编码：AAC
音频码率：160k
音频声道：单声道
```

注意：

- 如果源视频是 30fps，输出仍是 30fps。
- 如果源视频是 60fps，会被转成 30fps。
- 如果源视频是 24fps，也会被转成 30fps。
- 分辨率会按当前 filter 输出保持源画面尺寸；典型竖屏口播会保持 1080x1920。
- 码率不是固定原码率，而是由 CRF 18 按画面复杂度自动分配。
- 原音频如果是双声道，会输出为单声道；对口播通常合理，但会丢失立体声空间感。

如果没有任何切点且希望完全避免重编码，可以加：

```bash
--copy-when-no-cuts
```

但只要发生裁剪，仍需要重新编码才能稳定拼接音画。

## 模式

### safe

只删非常明确的独立语气词，适合不想冒误删风险的素材。

### aggressive

默认推荐。删除明确的“嗯、呃、额、唔、啊”，并缩短明显长停顿。

### editor

当前仍以 review 报告为主，不会激进删除“这个、就是、然后”等半语义口头禅。后续会扩展。

## 工作原理

```text
输入视频
→ 本地 ASR 转写，得到词级时间戳
→ 规则引擎识别 filler、长停顿、review-only 片段
→ 合并切点并增加安全余量
→ FFmpeg 同步裁剪音频和画面
→ 可选重新转写成片并补切 residual filler
→ 输出成片、manifest、report
```

AI 负责转写、时间戳和复核；脚本负责决策、裁剪、落盘和报告。

复核补切阶段默认只自动补切 A 类 filler（“嗯、呃、额、唔、呣”）。`啊` 会进入 review-only，避免误删自然语气。

## 适用边界

适合：

- 单人口播；
- 竖屏或横屏都可以，但默认输出保持源分辨率逻辑中的 30fps 编码；
- 背景音乐很轻或没有背景音乐；
- 目标是清理明显 filler；
- 接受成片因为裁剪而略微变短。

不适合直接套用：

- 多人对话；
- 背景音乐很大；
- 唱歌、朗诵、表演型视频；
- 需要复杂包装、字幕、贴图、B-roll 的成片剪辑。

## 检查结果

处理完成后建议检查：

- `final/` 是否有对应成片；
- `report.md` 是否生成；
- `manifests/*.json` 是否记录每个切点；
- `review_only` 里是否有需要人工判断的片段；
- 视频能否正常播放；
- 帧率、分辨率、音频声道是否符合预期；
- 是否有吞字、爆音、黑帧、音画错位；
- 源文件是否未被修改。

## 文档

- `docs/RUNBOOK.md`：操作手册和排障；
- `docs/DECISION_RULES.md`：剪辑规则；
- `docs/PROCESS.md`：处理流程说明；
- `docs/OPTIMIZATION_PLAN.md`：后续优化计划。
