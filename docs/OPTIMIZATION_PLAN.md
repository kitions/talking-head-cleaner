# 本地口播粗剪工具优化方案

目标：把当前一次性的处理结果，升级成一个可复用的本地口播粗剪工具。重点不是无限反复转写，而是用更多信号做一次更可靠的剪辑决策，并保留最多一轮复核补切。

## 推荐目标

基础版已经落地为命令行工具：

```bash
python scripts/talking_head_cleaner.py \
  --input /path/to/input_videos \
  --output /path/to/output_project \
  --mode aggressive
```

输入：一个包含 `.mp4` 的目录。  
输出：成片、转写、切点记录、验证报告。

## 推荐目录结构

```text
output_project/
├── analysis/          # 转写、VAD、音频分析
├── final/             # 最终成片
├── manifests/         # 可追溯剪辑决策
├── preview/           # 样片或预览
├── verification/      # 成片复核结果
├── waveforms/         # 切点附近波形图
└── report.md          # 人能直接看的汇总
```

## 三档模式

### safe

只删非常明确的独立语气词。

适用：不想冒任何误删风险。

规则：

- 删除独立“嗯、呃、额、唔”；
- 谨慎处理“啊”；
- 不处理“这个、就是、然后”；
- 不处理重复表达。

### aggressive

推荐默认模式。

适用：短视频口播，希望明显更干净。

规则：

- 删除独立“嗯、呃、额、唔、啊”；
- 删除句首明显 filler；
- 删除明显卡顿；
- 缩短过长停顿；
- 最多一轮复核补切；
- 不主动删除半语义口头禅。

### editor

更接近人工粗剪。

适用：愿意接受人工复核，希望进一步去掉啰嗦表达。

规则：

- 继承 aggressive；
- 标记“这个、就是、然后”滥用；
- 标记重复开头、口误重来；
- 自动删除高置信重复表达；
- 低置信片段只进入 review，不直接删。

## 核心架构

```text
InputScanner
→ AudioExtractor
→ Analyzer
   ├── WhisperAnalyzer
   ├── DisfluencyAnalyzer
   ├── VadAnalyzer
   └── AudioEnergyAnalyzer
→ DecisionEngine
→ Renderer
→ Verifier
→ ReportWriter
```

### InputScanner

职责：

- 扫描输入目录；
- 只处理 `.mp4`；
- 记录源文件 hash、大小、mtime；
- 确保不覆盖源文件。

### Analyzer

职责：

- 生成逐字稿；
- 提取词级时间戳；
- 找停顿、卡顿、语气词；
- 生成候选切点。

建议使用多信号：

- Whisper：识别文字和词级时间戳；
- `whisper-timestamped`：开启 disfluency 检测；
- VAD：判断人声和静音区域；
- 音频能量：寻找安全切点。

### DecisionEngine

职责：

- 把候选切点分级；
- 决定哪些自动删除，哪些只记录；
- 合并相邻切点；
- 给每个切点写明原因和置信度。

建议分类：

```text
A 类：必删
独立 嗯/呃/额/唔

B 类：大概率删
句首 啊/呃/嗯、明显卡顿、明显长停顿

C 类：谨慎删
这个、就是、然后、自然语气里的 啊

D 类：只记录
低置信、可能影响语义的片段
```

### Renderer

职责：

- 用 FFmpeg 同步裁剪音频和画面；
- 保持 1080x1920、30fps；
- 输出 H.264 + AAC；
- 切点前后加短淡入淡出；
- 不覆盖源文件。

优化点：

- 不直接按词时间戳硬切；
- 在词时间戳前后 100–200ms 内找音频低能量点；
- 优先切在停顿或能量谷底。

### Verifier

职责：

- 对成片重新转写；
- 检查 residual filler；
- 检查规格；
- 检查源文件 hash/mtime 是否不变。

建议策略：

```text
主剪辑 → 复核 → 明确 residual 补切一次 → 最终报告
```

不建议无限循环。超过一次补切后仍然存在的内容，应进入人工复核清单。

## Manifest 格式建议

每条视频输出一个 JSON：

```json
{
  "source": "/path/to/source.mp4",
  "output": "/path/to/output.mp4",
  "mode": "aggressive",
  "input_duration": 60.373,
  "output_duration": 54.861,
  "removed_duration": 5.512,
  "cuts": [
    {
      "start": 8.84,
      "end": 9.86,
      "reason": "filler:呃",
      "class": "A",
      "confidence": 0.91,
      "source": "whisper_timestamped+verification"
    }
  ],
  "review_only": []
}
```

## 验收标准

最低验收：

- 不修改源文件；
- 输出视频可正常播放；
- 音画同步；
- 无明显黑帧；
- 无明显爆音；
- 成片规格符合 1080x1920、30fps、H.264、AAC；
- manifest 能追溯每个切点；
- final 成片复核后，明确独立 filler 残留为 0 或进入 review 报告。

更高标准：

- 自动生成切点附近波形图；
- 输出人工复核清单；
- 每条视频有剪前/剪后时长对比；
- 输出总报告 `report.md`。

## 实施优先级

### P0：封装现有流程

状态：基础版已完成。

- 做一个可运行命令；
- 支持输入目录和输出目录；
- 支持 `aggressive`；
- 保留 manifest 和 verification。

### P1：提升剪辑质量

- 加 VAD；
- 加低能量安全切点；
- 加波形图；
- 限制最多一轮补切。

### P2：升级 editor 模式

- 加重复开头检测；
- 加“这个、就是、然后”频率分析；
- 加语义相似度判断；
- 低置信片段进入人工复核。

## 推荐下一步

先做 P0 + 一部分 P1。

原因：

- 现在流程已经证明有效；
- 最大痛点是不能一键复用；
- VAD 和低能量切点能直接提升听感；
- editor 模式涉及语义误删，应该等基础工具稳定后再做。

## 里程碑拆分

### M1：一键 aggressive 版本

状态：基础版已完成，后续可继续增强跳过逻辑和报告展示。

目标：把当前人工分阶段跑的流程封装成命令。

交付：

- `scripts/talking_head_cleaner.py`
- 支持输入目录和输出目录；
- 生成 `analysis/final/manifests/verification/report.md`；
- 默认 `aggressive`；
- 自动跳过已处理文件，避免重复覆盖。

验收：

- 对 1 条新视频能完整跑通；
- 源文件 hash/mtime 不变；
- 输出视频可播放；
- manifest 能追溯每个切点。

### M2：质量增强

目标：减少吞字和硬切。

交付：

- 音频能量分析；
- 低能量安全切点搜索；
- 切点波形图；
- 跳切密度控制；
- 长停顿保留策略。

验收：

- 切点附近无明显爆音；
- 人耳抽查无明显吞字；
- 波形图能辅助定位问题。

### M3：review 工作流

目标：把不确定片段从“自动删”变成“可复核”。

交付：

- `review_only.json`
- `report.md` 里列出人工复核片段；
- 可选 `--apply-review-manifest`，按人工修改后的 manifest 重渲染。

验收：

- 所有低置信片段都有原因；
- 用户能通过 manifest 恢复或禁用某个切点。

### M4：editor 模式

目标：接近人工粗剪。

交付：

- 重复开头检测；
- 口误重来检测；
- “这个、就是、然后”高频分析；
- 语义相似度校验；
- 更严格的 review-only 策略。

验收：

- 不误删有效句子；
- 对重复表达有明显清理效果；
- 每个语义级删除都能在 report 中解释。

## 风险与控制

| 风险 | 影响 | 控制方式 |
| --- | --- | --- |
| Whisper 漏识别 filler | 成片仍有残留 | 多模型复核、residual report |
| 时间戳不准 | 吞字或残留音头 | 安全余量 + 低能量切点 |
| 过度剪辑 | 语速太赶、情绪丢失 | mode 分级、长停顿保留、review-only |
| 背景音乐干扰 | 错识别、误切 | 提示输入限制，必要时先做人声分离 |
| 多次重编码 | 耗时、轻微画质损耗 | 限制补切轮数，统一最终渲染 |
| 语义误删 | 内容损失 | editor 模式默认人工复核 |

## 不做的事

短期不做：

- 字幕生成和包装；
- 自动加缩放、贴图、B-roll；
- 云端处理；
- 多人说话分离；
- 自动发布到平台。

这些不属于“本地口播粗剪核心链路”。先把语气词清理、切点质量和可复用命令做好。
