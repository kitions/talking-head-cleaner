# talking-head-cleaner 本地口播语气词清理

这个目录保存的是一次本地自动粗剪结果，目标是清理口播视频里的独立语气词，例如“嗯、额、呃、啊、唔”，并尽量保持画面、声音和语义完整。

当前推荐使用 `final_v2` 目录里的文件。

## 目录结构

```text
talking-head-cleaner/
├── final/             # 第一轮强力清理成片
├── final_v2/          # 推荐使用：第二轮验证后补切成片
├── manifests/         # 第一轮补切记录
├── manifests_v2/      # 第二轮补切记录
├── verification/      # 第一轮成片的二次转写验证
├── verification_v2/   # final_v2 的二次转写验证
├── summary.json       # 第一轮补切汇总
└── docs/
```

## 文档导航

- `README.md`：当前结果说明和日常使用入口。
- `docs/PROCESS.md`：这次实际跑出来的处理流程，包括每一轮做了什么。
- `docs/DECISION_RULES.md`：语气词、停顿、重复表达的剪辑判断规则。
- `docs/RUNBOOK.md`：后续有新视频时的操作手册和排障清单。
- `docs/OPTIMIZATION_PLAN.md`：后续继续增强一键工具的设计方案。

## 当前成片

成片默认输出到 `final/`。如果开启复核补切，后续轮次会生成带 `_r1` 后缀的文件。

示例：

```text
final/sample_01_roughcut_aggressive.mp4
final/sample_01_roughcut_aggressive_r1.mp4
```

`final` 是上一轮结果，仍有少量残留；`final_v2` 是继续根据 CPU Whisper 复核结果补切后的版本。

## 本次处理摘要

本次输入来自上一轮 `roughcut` 成片，不再动原始视频。处理分两步：

1. `final`：基于上一轮成片的二次转写结果，追加删除明确残留的语气词。
2. `final_v2`：再用 CPU Whisper 复核 `final`，发现仍有残留后，再补切一次。

`final_v2` 相比 `final` 又额外补切了 13 处 residual filler。补切后再次复核，5 条视频的明确语气词残留为 0。

各文件 `final_v2` 补切情况：

| 文件 | v2 补切数 | v2 额外删除时长 |
| --- | ---: | ---: |
| `sample_01` | 1 | 0.333s |
| `sample_02` | 2 | 0.867s |
| `sample_03` | 5 | 2.581s |

## 当前处理原则

这版属于“强力去语气词，但不主动删语义词”。

会处理：

- 独立出现的“嗯、额、呃、啊、唔”；
- 句首或停顿后的明显 filler；
- 复核转写里再次识别出的残留 filler。

暂时不自动处理：

- “这个、就是、然后”这类半语义口头禅；
- 可能有自然语气作用的“啊”，例如“这个布啊”；
- 需要理解上下文的重复表达、口误重来。

这些可以后续进入 `editor` 模式，但不建议直接混进当前强力语气词规则里，否则误删风险会明显上升。

## 适用边界

适合：

- 竖屏口播；
- 单人说话为主；
- 背景音乐很轻或没有背景音乐；
- 目标是清理明显“嗯、呃、额”等 filler；
- 接受成片因为裁剪而略微变短。

不适合直接套用：

- 多人对话；
- 背景音乐很大；
- 唱歌、朗诵、表演型视频；
- 需要保留自然停顿和情绪语气的视频；
- 需要复杂包装、字幕、贴图、B-roll 的成片剪辑。

如果视频里有背景音乐，建议先分离人声或降低音乐干扰，否则 ASR 可能漏识别 filler，切点也更容易不自然。

## 原理

核心不是降噪，也不是只把某个声音静音，而是：

```text
视频
→ Whisper 转写，拿到词级时间戳
→ 找出独立语气词的时间段
→ FFmpeg 同步裁剪画面和声音
→ 成片再次转写
→ 根据残留结果补切
→ 输出最终成片和 manifest
```

也就是说，如果转写识别出：

```text
呃：11.48s - 11.56s
```

剪辑器会在这个时间点前后加一点安全余量，然后把这段画面和声音一起删掉。这样成片时长会变短，但音画保持同步。

## 为什么要复核

“嗯/呃”这类声音很短，容易出现三种问题：

1. 第一次 Whisper 没识别出来；
2. 识别出来但置信度低，被保守策略留下；
3. 时间戳只覆盖中间，音头或音尾还残留。

所以这次用了“成片再转写 + 补切”的流程。`final_v2` 是经过复核后生成的版本。

## 验证结果

`verification_v2/post_refine_v2_summary_cpu.json` 记录了最终验证结果。

当前 5 条 `final_v2` 成片里，CPU Whisper 复核统计：

```text
嗯 / 额 / 呃 / 啊 / 唔 残留数：0
```

规格检查结果：

```text
分辨率：1080x1920
帧率：30fps
视频编码：H.264
音频编码：AAC
音频声道：单声道
```

## 当前局限

这套流程现在是一次项目结果，不是完整的一键工具。

已完成：

- 本地处理；
- 不上传云端；
- 保留源文件；
- 输出成片；
- 输出每轮切点 manifest；
- 用二次转写验证 residual。

已补基础封装：

- `scripts/talking_head_cleaner.py`；
- 任意输入目录的一键处理命令；
- `safe / aggressive / editor` 参数；
- dry-run 项目结构检查；
- manifest、verification、report 输出。

还没完成：

- VAD 和音频低能量安全切点；
- 自动生成波形预览；
- 自动汇总所有轮次的总删除时长。

## 质量判断标准

看成片时建议重点检查：

- 开头 30 秒：是否还有明显“嗯、呃”；
- 每个跳切点：有没有吞掉后一个字；
- 语速：是否过紧、没有呼吸感；
- 情绪：是否把自然思考停顿切得太狠；
- 音频：是否有爆音、突兀断裂；
- 画面：是否出现黑帧或异常跳帧。

如果只是少量语气词残留，不一定要继续强切。越往后清理，新增收益会下降，但误切风险会上升。

## 后续如果还有新视频

现在可以直接使用基础版一键命令：

```bash
python scripts/talking_head_cleaner.py \
  --input ./input_videos \
  --output ./input_videos-refined \
  --mode aggressive \
  --max-refine-rounds 1
```

如果当前环境没有 Metal/GPU，MLX Whisper 可能报 `No Metal device available`。这时用 CPU-only 模式：

```bash
python scripts/talking_head_cleaner.py \
  --input ./input_videos \
  --output ./input_videos-refined \
  --mode aggressive \
  --max-refine-rounds 1 \
  --skip-primary
```

正式跑之前可以 dry-run，只创建项目结构、扫描输入文件和生成基础 manifest，不跑 AI、不剪视频：

```bash
python scripts/talking_head_cleaner.py \
  --input ./input_videos \
  --output ./input_videos-refined \
  --mode aggressive \
  --dry-run
```

仍然可以让 Codex 代跑：

```text
帮我按 talking-head-cleaner/final_v2 这套强力去语气词流程，
处理 ./input_videos
```

后续增强方案见：

```text
docs/OPTIMIZATION_PLAN.md
```
