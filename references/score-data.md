# 校验 JSON

运行：`python scripts/validate_score.py path/to/score.json`。仅依赖 Python 标准库。

退出码：0 = 数据检查通过且无待核项；1 = 错误；2 = 待核警告。0 不代表源谱、配器或最终页面已被人工核对。

最小可运行示例在 `assets/example-score.json`，是为测试新写的短小示例，不是用户曲谱。

## 顶层

- `meter`: `[分子, 分母]`，小节拍数为 `分子 * 4 / 分母`。
- `voices`: 非空数组，每一项是一条独立演奏线。
- `connections`: 可选数组。`kind` 为 `tie` 或 `slur`，`start`、`end` 引用全局唯一事件 ID。连线属于一条声部；跨声部圆滑线等特殊记法需另建显式模型，而非强套此校验器。

## 声部

- `id`: 唯一字符串。
- `tonic`: 无点 1 的书写绝对音高，如 `G4`，不只是调名。
- `pitch_basis`: `written` 或 `concert`；必须显式选择。
- `monophonic`: 布尔值，默认 true；小号、长号等单独演奏线保持 true。
- `measures`: 依谱面顺序排列。各声部的小节 ID、顺序、小节长度必须一致；省略的整休止小节要在数据中展开，排版时才合并。
- 可另存 `instrument`、`transpose_semitones` 和来源信息，校验器不自动转调。
- `scale`: 可选，七个整数半音偏移，默认 `[0,2,4,5,7,9,11]`。

## 小节

- `id`: 字符串，例如 `"0"`（弱起）、`"1"`、`"53"`。
- `events`: 非空事件数组；整小节休止也必须有 rest 事件。
- `expected_beats`: 可选精确时值，仅在弱起、换拍或其他确有依据的不规则小节使用。设置时同时提供 `exception: {"kind":"pickup|meter_change|source_incomplete|other", "reason":"具体依据"}`。`source_incomplete` 始终产生待核警告。

## 事件

- `id`: 全局唯一。
- `kind`: `note`、`rest` 或 `unresolved`。未知演奏分配不能伪装成休止。
- `duration`: 以四分音符为 1 的正有理数字符串，例如 `"1"`、`"1/2"`、`"3/4"`、`"1/3"`。不使用浮点数。
- `pitches`: note 的已解析绝对音高数组。rest 必须为空或省略。unresolved 不提供确定 `pitches`，可以在 `source_pitches` 中保留未分配的原始音。
- `source`: 建议记录文件标识、页、谱表、小节、事件顺序或框选位置；用于人工逐项核对。
- `jianpu`: note 可选数组，与 pitches 一一对应。每项为 `{"degree":1,"octave":0,"alter":0}`，验证公式为 tonic + scale[degree-1] + 12*octave + alter。
- `tuplet`: 可选连音组 ID；同小节内各成员连续。小节内用 `tuplets: [{"id":"t1","count":3,"total_beats":"1"}]` 定义组，检查个数及总时值。
- `editorial`: 对实际编辑性变更记录 `{"approved":true,"reason":"用户批准的依据"}`。

绝对音高使用科学音高记法，例如 C4、F#4、Bb3，可用双升/双降。所有调号、临时记号、跨小节延音和八度记号必须在上游解析，脚本不猜测。简谱附点、横线、奏法和力度可另存字段，需由制谱程序及人工核验。

## 适用边界

此模型适合已有明确声部及顺序的转写校验。复杂嵌套连音、自由节拍、多声部交叉连线或不同步拍号需要扩展模型，不得为满足脚本强改音乐。打印顺序中的反复跳转另设演奏路径审核；本脚本不展开 D.S./Coda。
