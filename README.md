# talking-head-cleaner

本地口播粗剪工具。它使用本地 Whisper 系列模型定位“嗯、呃、额、啊、唔”等语气词，再用 FFmpeg 同步裁剪画面和声音。

定位：单人口播 / 本地批量粗剪。  
不是：通用短视频包装工具、字幕工具、多人对话剪辑器。

## 能做什么

- 批量扫描输入目录里的 `.mp4`；
- 本地转写并生成词级时间戳；
- 自动删除明确独立的 filler；
- 缩短过长停顿；
- 可选做一轮成片复核补切；
- 输出成片、manifest、verification、report；
- 默认不上传云端，不覆盖源文件。

## 安装

需要 Python 3.12、FFmpeg 和 ffprobe。

macOS 可先安装 FFmpeg：

```bash
brew install ffmpeg
```

创建虚拟环境：

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -r requirements.txt
```

如果没有 `python3.12`，也可以先用系统已有的 Python 3.11+ 尝试。

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

如果当前环境没有可用 Apple Metal/GPU，MLX Whisper 可能报 `No Metal device available`。这时用 CPU-only 模式：

```bash
python scripts/talking_head_cleaner.py \
  --input ./input_videos \
  --output ./output_project \
  --mode aggressive \
  --max-refine-rounds 1 \
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
- 视频能否正常播放；
- 是否有吞字、爆音、黑帧、音画错位；
- 源文件是否未被修改。

## 文档

- `docs/RUNBOOK.md`：操作手册和排障；
- `docs/DECISION_RULES.md`：剪辑规则；
- `docs/PROCESS.md`：处理流程说明；
- `docs/OPTIMIZATION_PLAN.md`：后续优化计划。
