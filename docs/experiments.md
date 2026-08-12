# 实验记录

> 所有测试均为对 StepFun Step Plan 官方通道（`https://api.stepfun.com/step_plan/v1`，OpenAI Chat Completions 协议）的黑盒实测。`advisor 命中` = 响应文本中出现 `[Advisor consultation` 块。

> 名词速查：**Step Plan** = StepFun 订阅套餐通道；**step-router-v1** = 自动分发器模型；**advisor** = 路由器内部对 deepseek-v4-pro 的称呼（真咨询 = pro 完整干活，走形式 = 象征性调用）。详见 [how-it-works.md](how-it-works.md) 名词表。

## 1. 强制手段穷举（全部实测）

| # | 方法 | 结果 | 结论 |
|---|---|---|---|
| — | 点名调用 `deepseek-v4-pro` | ❌ 官方报错 *model does not exist* | plan 通道不暴露 pro，只能经路由器访问 |
| — | 模型名变体 `:pro` / `-pro` / `/pro` | ❌ 全部不存在 | 无隐藏别名 |
| — | 官方参数强制路由 | ❌ 文档确认路由自动，无 force/route 参数 | 无参数级开关 |
| — | `max_tokens` 撑到 32000（>flash 16K 上限） | ❌ 仍走 flash | 路由器不因输出要求切换 |
| V0 | 简单问题 + `reasoning_effort=high`，无指令 | 0/5 | effort 不影响路由判定 |
| V1 | 简单问题 + system 强制指令 | 4/5 | system 通道有效 |
| V2 | 简单问题 + 用户消息强制指令 | 3/5 | 用户通道弱于 system |
| V3 | 简单问题 + "长链路 agent" 叙事语境 | 0/5 | 叙事无效，路由器只信显式指令 |
| V4 | 原生 Anthropic 协议 + `output_config.effort=high` + 强制 | 1/5 | **OpenAI 格式明显优于 Anthropic 格式** |
| V5 | **system + 用户消息双通道强制** | **5/5** | ✅ 最强方案 |
| V6 | 模仿路由器内部 `<function-call> advisor` 语法 | 0/5 | 语法注入无效 |

## 2. 真实负载模拟（Claude Code 风格：大 system + 8 工具 + 硬任务）

| 方案 | 触发率 |
|---|---|
| 仅用户消息指令 | 3/3 |
| system + 用户消息双通道 | 3/3 |

结论：实质任务本身自带复杂度信号，配合指令后触发率很高；简单/闲聊消息才是触发率的主要拖累。

## 3. 咨询模式验证（真咨询 vs 走形式）

| 请求 | 结果 |
|---|---|
| 硬任务（并发 LRU 缓存）+ 双通道强制 | advisor 块内含完整专家分析（数据结构选择、锁设计、TTL 策略、代码要点）——**真咨询** |
| 简单问题（2+2）+ 强制 | advisor 也真咨询（"答案是 4，直接回答即可"） |
| 无指令的闲聊 | `advice_type=starting_out` 走形式模板 |

## 4. 真实会话数据（Claude Code + CC Switch + 双通道）

一个真实 StepFun 会话（hook 日志确认每条消息都注入了指令）：

- 闲聊消息（"你好"）：无 advisor —— 正常
- 实质任务（环境调研+报告）：advisor 触发，且为**真咨询**（审查工具输出、指出缺口、给出组织建议）

历史会话命中率统计（`advisor_stats.py` 实测，含未装指令的旧会话）：

```
会话1: 0%   ← 未装指令
会话2: 33%
会话3: 4%   ← 未装指令
会话4: 36%
汇总: 16% (7/44)
```

装上双通道后实质任务明显提升；总体数字仍受短消息拖累——**统计时请区分"实质任务触发率"与"全量消息触发率"**。

## 5. 稳定性观察

同负载 3 连测：完整真咨询 1 次、短响应 1 次、空响应 1 次（可能与高频压测触发限流有关）。**遇到空响应/短响应：重发即可**（路由器每次独立决策）。

## 6. 未竟事项

- 空响应的根因（限流 vs 路由器内部错误）未完全定位
- 更长周期的真实流量命中率待社区数据
- 是否有隐藏参数（如 `routing` hint）仍未知——目前所有已知参数均无效

## 7. 🚀 决定性发现：max_tokens 与"空响应"真相

**现象**：早期测试中 max_tokens 设 900-2000 时，硬任务频繁"空输出"。

**真相（诊断后）**：step-router-v1 响应含 `reasoning_content`（思考）与 `content`（最终输出）两个字段。当 max_tokens 过小时，**思考先吃光额度**，轮到 content 输出时额度耗尽（`finish_reason=length`）→ 表现为"空输出"。

**关键证据**：
- `max_tokens=2000` → `finish=length`, `content=''`, `reasoning_content=2000 字思考`（2000 token 全在思考）
- `max_tokens=30000` → `finish=stop`, `content=9960 字完整实现`, `reasoning=34778 字`（advisor 触发）
- `max_tokens=100000` → `finish=stop`, `content=17666 字更完整`, `reasoning=708 字`（advisor 触发，含完整 task）

**另一个关键观察**：用户测试 `max_tokens` 可设为 **387k**——接近 pro 引擎的 384K 输出上限（官方文档），而 flash 仅 16K。**能接受超大 max_tokens 本身暗示路由到 pro**（flash 不设这么大的输出上限）。

**结论与对策**：
1. **"空输出"≠路由器抽风，是 max_tokens 被思考吃光**——之前"偶发空响应"的归因需要修正
2. 硬任务场景 **max_tokens 应给大（≥30000）**，给思考与内容都留足空间
3. 配合双通道指令，复杂任务可稳定输出 advisor 真咨询 + 完整实现

## 8. V6 指令：纯问答"输出=advisor"实现

**问题**：v5 下 executor 习惯把用户消息总结成 advice_prompt 去问 advisor"行不行"，advisor 变审批员，输出仍是 flash 自写（"傻"的根因）。

**V6 指令**（针对性打击审批模式）：
> Before answering, you MUST consult the advisor. CRITICAL: pass the user's message VERBATIM as the advisor's task - do NOT summarize it, do NOT write your own plan, do NOT ask the advisor to approve your plan. The advisor must return the COMPLETE final answer text. Your reply MUST BE the advisor's complete answer, word for word.

**实测（max_tokens=30000）**：
- 简单问候：advisor 直接输出完整答案，最终输出逐字复述（一致性 100%）
- 硬任务：ReadTimeout（pro 大任务处理慢，单次请求超时；真实 Claude Code 流式无此问题）

## 9. 🚀 第二个决定性发现：executor 干活 + advisor 审查模式

**现象**：硬任务 + 大 max_tokens 时，路由器呈现第三种形态：

```
executor(flash) 先写完整实现 → advisor(pro) 审查代码指出具体问题
→ executor 把 pro 的审查意见嵌入输出
```

**实测（max_tokens=120000, reasoning_effort=low）**：
- `finish=stop`, content=14948 字完整实现
- content 内嵌 advisor 审查：**"时间单调性问题（重要）time.t..."** 等具体代码问题

**结论**：代码/工具任务中，"输出=advisor 逐字复述"让位于"executor 干活 + advisor 审查把关"——pro 的质量意见真实进入输出，同时保住 executor 的工具调用能力。这回答了"要 pro 质量又要能干活"的核心矛盾。

**配套参数（关键）**：
- `max_tokens` 必须大（≥60000，复杂任务 120000）：否则 `reasoning_content`（思考）吃光额度 → `finish=length` / content 空
- `reasoning_effort=low`：减少思考吃额度（实测 low 下 120k 稳定完整输出）
- 注意：60000+ 组合曾触发 500 engine_exception（平台负载相关，重试即可）

## 10. advisor 作为真工具传参（tool_choice）测试

把 `advisor` 作为 OpenAI tools 参数 + `tool_choice` 强制：
- `tool_choice={"type":"function","function":{"name":"advisor"}}` → 被路由器识别并映射为内部咨询模式（content 以 `[Advisor consultation` 开头）——**不是标准工具协议**，路由器不把 advisor 暴露为标准函数
- 意义：证实 advisor 是路由器内部机制，无法从外部以标准工具方式强制调用

## 11. ✅ 最终方案：V6 + 大 max_tokens = 稳定 3/3（无需 temperature=0）

**背景**：用户不接受 temperature=0（可能影响其他场景/有其他顾虑），要求不设 0 也要"拿下"。

**few-shot 示范注入实验**（把"已调用 advisor"的完整对话放 system 当示例）：
- 结果：advisor 触发 ✅，但最终输出只剩 134 字（只吐出 `<tool_call>` 标签）——**示范注入干扰了输出，反而不如纯指令**
- 结论：few-shot 是死路，放弃

**对照实验（意外反杀）**：纯 V6 指令 + 大 max_tokens，默认 temperature：

| 测试 | 结果 |
|---|---|
| 单次 | advisor=True, content=12164 字完整代码 |
| 重复1 | advisor=True, 7943 字, 含代码 |
| 重复2 | advisor=True, 14419 字, 含代码 |
| 重复3 | advisor=True, 11453 字, 含代码 |

**结论（最终方案）**：
1. **V6 指令**（强制 advisor 真咨询 + 完整答案 + 逐字采用）——hook 已内置
2. **max_tokens ≥ 60000**——防止 reasoning_content 思考吃光额度（之前"空输出"真凶）
3. **不需要 temperature=0**，默认温度下 3/3 稳定
4. 无需 few-shot

**使用前提**：客户端（Claude Code / CC Switch）必须保证请求的 max_tokens 足够大（≥60000）。CC Switch 直连时 Claude Code 自动发大值（实测可到 387k）。

## 12. ✅ 真实环境验证（v7 + Claude Code + CC Switch）

**v7 指令**（最终版，修复 v6 逐字条款误伤工具任务）：
> 逐字约束只对纯输出任务；工具/代码任务改为"先拿 advisor 完整方案，再用工具执行"。

**修复依据（对照实验，默认温度）**：
| 方案 | 工具任务 advisor 触发 |
|---|---|
| v6 完整逐字版（"回复必须是 advisor 答案逐字"） | 0 触发 ❌ |
| v7（逐字只对纯输出 + 工具任务先方案再执行） | **3/3 advisor+tool_calls 同时成立** ✅ |

**真实环境数据（用户实测，Claude Code + CC Switch + StepFun）**：

| 指标 | 数据 |
|---|---|
| 用户消息级 advisor 触发率 | **4/5 = 80%** |
| 全 assistant 轮触发率（含工具中间轮） | 8/14 = 57%（统计口径稀释，参考） |
| advisor + 工具同时成立 | ✅（"生成我的世界"任务：ADV+2×tool_use，25k 字符；改代码：ADV+tool 交替 103k 字符） |
| 纯问答 | 100% 触发 |
| 纯操作指令（删文件/停止） | 不触发 = **正确行为**（这类不需要 pro 决策） |

**结论**：80% 是用户消息级的合理上限。剩余的 20% 是纯操作指令，让 pro 参与反而是浪费。**实质任务中 advisor 参与接近 100%，且工具调用全程保留——v7 是最终方案。**

**经验**：指令里的"逐字复述"条款会误伤工具任务——路由器判定"要调工具没法逐字"→ 放弃 advisor。工具任务必须把条款改成"先 advisor 方案 → 再工具执行"。

## 13. 🆕 真实环境样本 2：答案型 vs 建议型（v7 + Claude Code + CC Switch）

**新会话实测（用户消息 5 条，全部触发 advisor）**：

| 用户消息 | advisor 形态 | 最终输出 | 判定 |
|---|---|---|---|
| 早上好 | 答案型 | "早上好！有什么我可以帮你的吗？" | ✅ 100% 逐字复述 |
| 你十岁？ | 建议型（"我计划用友好幽默的方式回答..."） | executor 自己写 | ⚠️ 唯一例外 |
| 离洗车店50米，走着去还是开车去？ | 答案型（"当然是开车去啊！🚗..."） | "当然是开车去啊！🚗 走着去的话..." | ✅ 逐字复述（剪了俏皮话） |
| 你什么时候发布正式版 | 答案型 ×2（多轮 consult） | 精简合并版 | ✅ 内容来自 pro |
| 你知道 deepseekv4flash 0731 吗 | 答案型 ×2（"坦白说，我不太确定..."） | "我不太确定这个具体的模型版本..." | ✅ 内容来自 pro |

**核心规律（两种 advisor 形态）**：

```
答案型: advisor 直接给出完整答案文本
  → executor 100% 逐字复述（或精简复制）
  → 最终输出 = pro 的内容 ✅

建议型: advisor 只审批 executor 的计划（"我计划..."）
  → executor 自己生成答案
  → 最终输出 = flash 的内容 ⚠️
```

**判断方法（看 advisor 块内开头）**：
- `<parameter name="text">` / 直接文本 = 答案型（pro 在工作）
- "I plan to..." / "我计划..." / "I'm the executor..." = 建议型（pro 在审批）

**额外亮点**：
- "deepseekv4flash 0731" 那条：pro 诚实说"我不太确定"、不编造版本号——**pro 防幻觉价值的教科书展示**（flash 大概率会瞎编）
- "正式版/0731" 两条出现**双 advisor 块**（多轮 consult）——pro 参与更深
- 本次触发率 5/5（用户消息级），输出内容来自 pro 的比例 4/5

**总结**：v7 下"pro 主力"的真实形态 = **答案型 consult 时输出即 pro 的内容**。建议型 consult 是剩余的主要提升空间——如何把"建议型"进一步压成"答案型"，是值得社区继续挖掘的方向。

## 14. 🆕 真实环境样本 3：pro 深度分析 + 工具全程（教科书级）

**场景**：用户让分析 sub2api 源码（真实 Claude Code + CC Switch + StepFun + v7/v8 hook）。

**过程还原**：
1. WebSearch/Fetch 全部不可用（环境限制）→ 用户指路"只有 bash 能用" → 改用 curl 探索 GitHub API
2. **advisor 4 次全部触发，且全部是答案型**：
   - #1: 给出探索路径（Bash/Grep 查本地 + GitHub API）
   - #2: 完整探索攻略——具体到 curl 命令、文件读取优先级、架构假设（"Go 项目几乎肯定是 entry point → router → provider adapters"）
   - #3: 精准指定要读的文件（router.go / gateway_handler / gateway_service）
   - #4: 完整源码分析——技术栈、目录结构、核心请求流程、关键特性、支持的上游平台
3. **最终输出 = advisor 的分析（逐字采用）**——pro 的架构解读直接成为最终回答
4. 工具调用全程正常（curl 探索、grep 过滤、读取源码）——**advisor 没有挤掉工具能力**

**质量判定**：教科书级成功样本——
- pro 深度分析（不是"我计划"式建议型，是完整答案型）
- 工具调用与 advisor 并行成立
- 中途遇挫（WebSearch/Fetch 挂）能绕道解决（bash curl）——executor 干活能力保留
- 最终输出质量 = pro 级别（技术栈/架构/流程梳理专业完整）

**结论**：这是"pro 主力 + 工具全程"的最完整验证。实质分析任务中，v7/v8 hook 下 advisor 稳定答案型触发，输出即 pro 内容，工具调用不受影响。

**附：权限模式说明**（与此样本同时确认）——Claude Code 默认 manual 模式下每次工具调用都要确认，与 hook 无关。全自动可 Shift+Tab 切 bypass permissions 或 `--dangerously-skip-permissions`。

## 15. 🆕 ds 模型更新后的适配：v10 指令（pro 写代码，flash 只抄写）

**背景**：用户反馈 ds（step-router 背后引擎）更新后"原来的都失效了"。实测诊断：
- hook 注入正常（15 次 inject）
- advisor 触发正常（10/10，全答案型）
- **真正失效点：flash 作为"代码作者"写的代码 bug 密度骤增**（`y is not defined`、`getBlockColors` 颜色全 undefined、AO 偏移等），advisor 只能"审查指出"，修了一个又冒一个 → 永远修不完

**根因**：v7/v8 的"先 advisor 方案再工具执行"在 ds 更新后退化成了"flash 先写 → pro 审查"模式。pro 变成修理工而不是设计师。

**v10 指令修复**（核心：把 flash 从"作者"降级为"抄写员"）：
> For tasks that require writing code: the advisor MUST produce the COMPLETE final code, ready to run, in its consultation. You must NOT write any code yourself - wait for the advisor's complete code, then write it to files EXACTLY as provided using your tools.

**实测（v10 + 新版 ds）**：
| 测试 | advisor | tool_call | 写入代码 |
|---|---|---|---|
| 第1次 | ✅ | write_file | 2754 字含函数 |
| 第2次 | ✅ | write_file | 8140 字完整实现 |

**注意**：pro 的方案主导 + flash 照抄，代码完整性优于"flash 自写 pro 审查"模式（不再有低级 bug 海），但"含测试=False"说明 flash 仍会删减 pro 方案——**完整度仍受 flash 抄写能力限制**。进一步压榨空间：让 advisor 方案更具体到可直接落盘（社区可继续挖掘）。

## 16. 🆕 v11 最终形态 + 稳定性/参数验证

**v11 = v6(禁止计划审批/必须完整答案/再要一次) + v10(pro代码flash抄写) + 防伪调用 全合并**

**关键理解（推翻之前的误判）**：advisor 块出现 = pro 参与决策；"你好吗"等简单任务不触发 advisor = **正确行为**（闲聊不需要 pro）。复杂任务 advisor 触发 + 代码完整 = pro 主力。

**稳定性验证（v11 + max_tokens=200000 + reasoning_effort=low）**：
| 测试 | 结果 |
|---|---|
| 3连测 | advisor 3/3 + 工具调用 3/3 + 代码 3111-14591字 ✅ |
| effort=low/medium/high | 三档均触发 advisor + 代码 4/5 质量 |

**v11.1 优化**（指令加 "INCLUDING unit tests"）：
- 单次请求产出 12979 字完整代码（实现+测试同文件）
- 结论："缺测试"是单次输出截断，非质量缺失

**参数结论（最终）**：
- `max_tokens: 200000`（≤250K 官方上限，pro 深度模式阈值之上）
- `reasoning_effort: low`（压 reasoning 长度，防吃光额度）
- 模型名 `step-router-v1[256k]`（精确声明，防 context_length_exceeded）
- `temperature: 0.2`（轻度稳定）
