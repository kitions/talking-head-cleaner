# 操作手册与排障

这份文档面向后续继续处理新视频。

当前项目已经有基础版一键命令：

```text
scripts/talking_head_cleaner.py
```

它支持 `safe / aggressive / editor` 参数。其中 `editor` 当前仍以 review 报告为主，不会激进删除“这个、就是、然后”这类半语义口头禅。

## 环境要求

当前命令复用上一轮已经建好的 Python 环境：

```text
.venv
```

需要本机已有：

- `ffmpeg`
- `ffprobe`
- `mlx-whisper`
- `whisper-timestamped`
- `torch`

如果使用完整模式，MLX Whisper 需要可用的 Apple Metal/GPU 环境。当前 Codex 沙盒有时拿不到 Metal，这种情况下要加 `--skip-primary`，改用 CPU-only 复核模型。

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

正式跑之前可以 dry-run：

```bash
python scripts/talking_head_cleaner.py \
  --input ./input_videos \
  --output ./input_videos-refined \
  --mode aggressive \
  --dry-run
```

也可以让 Codex 按当前 `final_v2` 流程代跑：

```text
帮我按 output_project/final_v2 这套强力去语气词流程，
处理 ./input_videos
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

如果做复核补切，可以增加：

```text
final_v2/
manifests_v2/
verification_v2/
```

## 最低检查清单

处理完成后至少检查：

- `final` 或 `final_v2` 里是否有对应数量的 mp4；
- 每条视频能正常播放；
- 分辨率是否仍是 1080x1920；
- 帧率是否 30fps；
- 音频是否 AAC 单声道；
- manifest 是否记录了每个切点；
- verification 是否有 residual 统计；
- 源文件 hash/mtime 是否没变。

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

后续封装后，推荐命令：

```bash
python scripts/talking_head_cleaner.py \
  --input ./input_videos \
  --output ./input_videos-refined \
  --mode aggressive \
  --verify \
  --max-refine-rounds 1
```

参数建议：

| 参数 | 说明 | 默认 |
| --- | --- | --- |
| `--input` | 输入视频目录 | 必填 |
| `--output` | 输出项目目录 | 必填 |
| `--mode` | `safe/aggressive/editor` | `aggressive` |
| `--verify` | 是否成片复核 | 开启 |
| `--max-refine-rounds` | 自动补切轮数 | `1` |
| `--keep-pause` | 长停顿缩短后保留时长 | `0.4` |
| `--fade-ms` | 切点音频淡化 | `30` |

## 人工复核建议

优先看：

1. 每条视频开头 20 秒；
2. manifest 中最长的 5 个删除片段；
3. verification 里 residual 或 review-only 片段；
4. 波形图里红线附近是否有高能量截断；
5. 成片是否有明显过紧或情绪丢失。
