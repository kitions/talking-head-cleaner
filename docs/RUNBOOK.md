# 操作手册与排障

这份文档面向后续继续处理新视频。

当前项目已经有基础版一键命令：

```text
scripts/talking_head_cleaner.py
```

它支持 `safe / aggressive / editor` 参数。其中 `editor` 当前仍以 review 报告为主，不会激进删除“这个、就是、然后”这类半语义口头禅。

## 环境要求

建议在项目内创建 Python 虚拟环境并安装通用 CPU 依赖：

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -r requirements.txt
```

macOS Apple Silicon 如果想启用 MLX Whisper 主模型，再安装：

```bash
pip install -r requirements-macos-mlx.txt
```

Windows PowerShell：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -U pip
pip install -r requirements.txt
```

需要本机已有：

- `ffmpeg`
- `ffprobe`
- `whisper-timestamped`
- `torch`

macOS MLX 增强模式还需要：

- `mlx-whisper`

如果使用完整模式，MLX Whisper 需要可用的 Apple Metal/GPU 环境。远程、无头或沙盒环境有时拿不到 Metal，这种情况下要加 `--skip-primary`，改用 CPU-only 复核模型。

Windows 不支持 MLX Whisper，必须加 `--skip-primary`。

## 新视频推荐流程

准备一个输入目录：

```bash
mkdir -p ./input_videos
```

把待处理的 `.mp4` 放进去。

直接运行：

```bash
python scripts/talking_head_cleaner.py \
  --input ./input_videos \
  --output ./input_videos-refined \
  --mode aggressive \
  --max-refine-rounds 1
```

如果当前环境跑 MLX Whisper 报 `No Metal device available`，用 CPU-only 模式：

```bash
python scripts/talking_head_cleaner.py \
  --input ./input_videos \
  --output ./input_videos-refined \
  --mode aggressive \
  --max-refine-rounds 1 \
  --skip-primary
```

Windows PowerShell：

```powershell
python scripts\talking_head_cleaner.py `
  --input .\input_videos `
  --output .\input_videos-refined `
  --mode aggressive `
  --max-refine-rounds 1 `
  --skip-primary
```

正式跑之前可以 dry-run：

```bash
python scripts/talking_head_cleaner.py \
  --input ./input_videos \
  --output ./input_videos-refined \
  --mode aggressive \
  --dry-run
```

dry-run 默认不计算源文件 sha256，只记录文件大小和修改时间。如果需要完整源文件 hash：

```bash
python scripts/talking_head_cleaner.py \
  --input ./input_videos \
  --output ./input_videos-refined \
  --mode aggressive \
  --dry-run \
  --hash-sources
```

公开分享 manifest 或 `report.md` 前，建议使用路径脱敏模式，只写入文件名，不写入本机绝对路径：

```bash
python scripts/talking_head_cleaner.py \
  --input ./input_videos \
  --output ./input_videos-refined \
  --mode aggressive \
  --max-refine-rounds 1 \
  --redact-paths
```

默认情况下，即使没有任何切点，脚本也会用 FFmpeg 重新编码，以保持输出规格统一。如果希望没有切点时直接复制源文件：

```bash
python scripts/talking_head_cleaner.py \
  --input ./input_videos \
  --output ./input_videos-refined \
  --mode aggressive \
  --copy-when-no-cuts
```

也可以让 AI agent 按当前命令代跑：

```text
帮我用 talking-head-cleaner 的 aggressive 模式处理 ./input_videos，
输出到 ./input_videos-refined
```

建议输出目录：

```text
./input_videos-refined
```

## 推荐输出结构

```text
output_project/
├── analysis/
├── final/
├── manifests/
├── verification/
├── waveforms/
└── report.md
```

如果做复核补切，补切后的视频仍在 `final/`，文件名会增加 `_r1` 后缀。

## 最低检查清单

处理完成后至少检查：

- `final/` 里是否有对应数量的 mp4；
- 每条视频能正常播放；
- 分辨率是否仍是 1080x1920；
- 帧率是否 30fps；
- 音频是否 AAC 单声道；
- manifest 是否记录了每个切点；
- verification 是否有 residual 统计；
- 源文件 hash/mtime 是否没变。

## 输出质量说明

当前默认是“高质量重编码”，不是无损 copy。

默认 FFmpeg 输出：

```text
H.264 / CRF 18 / preset medium / yuv420p / 30fps
AAC / 160k / mono
```

影响：

- 源视频如果是 30fps，输出仍是 30fps；
- 源视频如果是 60fps，会转成 30fps；
- 源视频如果是 24fps，会转成 30fps；
- 码率不是固定原码率，而是 CRF 18 自动分配；
- 分辨率通常保持源尺寸；
- 音频会转成 AAC 单声道；
- 重编码理论上有轻微画质损耗，但 CRF 18 对口播通常足够高质量。

如果没有任何切点且希望避免重编码，可以使用：

```bash
--copy-when-no-cuts
```

如果发生了裁剪，仍建议重新编码，否则音画拼接稳定性和兼容性会变差。

## 常见问题

### 1. 还有“嗯/呃”残留

原因可能是：

- 第一轮 Whisper 漏识别；
- 时间戳只覆盖了声音中间；
- 置信度阈值太保守；
- “呃”和后面的字粘连，模型没有拆开。

处理：

- 用 CPU `whisper-timestamped` 再复核；
- 对明确 residual 做一次补切；
- 不建议无限循环，超过一轮后进入 review。

### 2. 有吞字

原因可能是：

- 前置余量太大；
- 后一个有效字和 filler 粘连；
- 切点没有落在低能量区域。

处理：

- 减小 `pad_before`；
- 使用音频能量低谷找切点；
- 对该切点转为 review-only。

### 3. 跳切太硬

原因可能是：

- 相邻切点太密；
- 删除了自然换气；
- 没有足够的音频淡入淡出。

处理：

- 合并近距离切点；
- 保留 200–400ms 自然停顿；
- 加 25–30ms audio fade。

### 4. 成片太赶

原因可能是：

- aggressive 策略过强；
- 长停顿保留太少；
- 删除了本来用于强调的停顿。

处理：

- 改用 `safe`；
- 长停顿从保留 0.4s 调到 0.6s；
- 情绪停顿进入 review-only。

### 5. 背景音乐影响识别

原因可能是：

- 音乐盖过人声；
- ASR 把音乐或气声误识别成词；
- VAD 判断不稳定。

处理：

- 先做人声分离；
- 降低背景音乐；
- 用更保守的 `safe`；
- 增加人工复核。

## 建议命令形态

推荐命令：

```bash
python scripts/talking_head_cleaner.py \
  --input ./input_videos \
  --output ./input_videos-refined \
  --mode aggressive \
  --max-refine-rounds 1
```

参数建议：

| 参数 | 说明 | 默认 |
| --- | --- | --- |
| `--input` | 输入视频目录 | 必填 |
| `--output` | 输出项目目录 | 必填 |
| `--mode` | `safe/aggressive/editor` | `aggressive` |
| `--max-refine-rounds` | 自动补切轮数 | `1` |
| `--keep-pause` | 长停顿缩短后保留时长 | `0.4` |
| `--fade-ms` | 切点音频淡化 | `30` |
| `--hash-sources` | manifest 记录源文件 sha256 | 关闭 |
| `--copy-when-no-cuts` | 无切点时直接复制源文件 | 关闭 |
| `--skip-primary` | 跳过 MLX Whisper，只用 CPU 模型 | 关闭 |

## 人工复核建议

优先看：

1. 每条视频开头 20 秒；
2. manifest 中最长的 5 个删除片段；
3. verification 里 residual 或 review-only 片段；
4. 波形图里红线附近是否有高能量截断；
5. 成片是否有明显过紧或情绪丢失。
