# 实际处理流程记录

这份文档说明 `talking-head-cleaner` 的处理流程，方便后续复用或排查。

## 输入与输出

通常从原始或粗剪口播视频开始处理。

输入：

```text
input_videos/*.mp4
```

输出：

```text
output_project/final/
```

推荐使用：

```text
output_project/final/
```

## 阶段 1：主转写和剪辑

脚本先对输入视频做本地转写，提取词级时间戳，再把明确 filler 和长停顿转换成候选切点。

输出：

```text
final/*_roughcut_aggressive.mp4
manifests/*_manifest.json
analysis/*_primary.json
analysis/*_secondary_disfluency.json
```

## 阶段 2：CPU Whisper 复核

如果设置 `--max-refine-rounds 1`，第一轮成片完成后，会再用 CPU 版 `whisper-timestamped small` 复核。

如果复核发现 residual filler，会生成一轮补切。

## 阶段 3：生成补切版本

根据复核结果，把明确 residual 再补切一次。

输出：

```text
final/*_roughcut_aggressive_r1.mp4
verification/*_round1_verification.json
```

## 阶段 4：最终复核

最终 manifest 会把最后一版成片写入 `final_output`。

结果：

```text
source.mp4 -> final/source_roughcut_aggressive_r1.mp4
```

规格：

```text
分辨率：1080x1920
帧率：30fps
视频编码：H.264
音频编码：AAC
音频声道：单声道
```

## 为什么不用无限循环

可以无限转写、再切、再转写，但不建议这样做。

原因：

- Whisper 的识别结果不是绝对真值，可能把自然语气误识别成 filler；
- 越往后切，剩下的片段越接近边界，误切风险越高；
- 多次重编码会增加时间成本，也可能带来轻微画质损耗；
- 成片的自然呼吸感可能被过度压缩。

推荐策略：

```text
主剪辑
→ 一次复核补切
→ 最终复核
→ 剩余低置信问题进入人工 review
```

建议保留最多一轮自动补切，超过的记录到 review 报告。
