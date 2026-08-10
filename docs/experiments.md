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
