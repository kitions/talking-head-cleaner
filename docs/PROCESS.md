# 实际处理流程记录

这份文档记录本次 `talking-head-cleaner` 的实际处理方式，方便后续复用或排查。

## 输入与输出

本次不是从原始素材重新开始，而是在上一版粗剪成片基础上继续强力清理。

输入：

```text
input_videos/*_roughcut.mp4
```

输出：

```text
./final/
output_project/final_v2/
```

推荐使用：

```text
output_project/final_v2/
```

## 阶段 1：基于上一版成片补切

上一版 `roughcut` 已经删除了一批高置信语气词和长停顿，但复核转写里仍能看到残留：

```text
0958...  残留 5 个
6ced...  残留 2 个
a061...  残留 0 个
b3ae...  残留 5 个
b923...  残留 1 个
```

这些 residual 主要是“嗯、呃、啊”。第一轮 refined 就是把这些明确残留再次按时间戳裁掉。

输出：

```text
final/*_roughcut_refined.mp4
manifests/*_refine_manifest.json
verification/post_refine_summary_cpu.json
```

## 阶段 2：CPU Whisper 复核

第一轮 refined 完成后，再用 CPU 版 `whisper-timestamped small` 复核。

复核发现 `final` 里仍有 residual filler：

```text
0958...  1 个
6ced...  2 个
a061...  5 个
b3ae...  1 个
b923...  4 个
合计：13 个
```

这说明只靠 MLX Whisper 的 post-edit 结果不够，CPU disfluency 模型在部分“呃”上召回更高。

## 阶段 3：生成 final_v2

根据 CPU 复核结果，把 13 个 residual 再补切一次。

输出：

```text
final_v2/*_roughcut_refined_v2.mp4
manifests_v2/*_manifest.json
verification_v2/post_refine_v2_summary_cpu.json
```

补切统计：

| 文件 | 补切数 | 额外删除时长 |
| --- | ---: | ---: |
| `sample_01` | 1 | 0.333s |
| `sample_02` | 2 | 0.867s |
| `sample_03` | 5 | 2.581s |

## 阶段 4：最终复核

对 `final_v2` 再做 CPU Whisper 复核。

结果：

```text
0958...  residual 0
6ced...  residual 0
a061...  residual 0
b3ae...  residual 0
b923...  residual 0
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

本次为了把明显 residual 清掉，实际做到了 `final_v2`。后续封装工具时，建议保留最多一轮自动补切，超过的记录到 review 报告。
