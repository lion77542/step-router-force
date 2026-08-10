# 发现过程：advisor 就是 deepseek-v4-pro

> 这是本项目最有价值的部分——**为什么"advisor 就是 pro"这个结论不是显而易见的，以及我们是怎么一步步发现并验证的**。完整证据链见 [experiments.md](experiments.md)。

## 起点：为什么路由不到 pro？

用户使用 Claude Code + StepFun Step Plan（`step-router-v1`）时发现：写了大量提示词要求"使用 DeepSeek V4 Pro"，但实际输出质量始终不像 pro。官方文档只说"自动调度"，没有公开路由规则。**提示词无效**——因为用户以为路由判定读"提示词内容"，实际上路由器读的是"请求特征 + 显式指令"。

## 线索 1：响应里出现了神秘的块

真实响应中偶尔出现：

```
[Advisor consultation #1]
[Advisor review]

<tool_call name="advisor">
  <parameter name="advice_type">starting_out</parameter>
  <parameter name="description">一句话概括</parameter>
</tool_call>

[End of advisor consultation #1]
```

普通人看到这个块会当作"格式噪音"忽略。但它暴露了两件事：
1. 路由器内部存在一个叫 **advisor** 的函数/服务
2. 存在 `starting_out` 这种**走形式**的调用模式

## 线索 2：黑盒直连，观察路由器"原形"

绕过 Claude Code，直接对 `https://api.stepfun.com/step_plan/v1/chat/completions` 发请求（模型名填 `step-router-v1`）。关键发现——**路由决策就是一次文本生成**：

```
复杂任务请求的响应:
[Advisor consultation #1] [Advisor review]
<function-call>
  <function-name>advisor</function-name>
  <function-args>{"task": "用户要用反证法严格证明根号2是无理数。
  要求: 分步骤推理, 每步说明理由, 并检查自己的推理是否有漏洞。\n\n
  我计划这样证明: 1. 假设根号2是有理数..."}</function-args>
</function-call>
```

路由器通过"生成函数调用文本"来决定是否咨询 advisor——**它是 LLM 决策器，不是规则转发器**。这就是提示词能影响它的根本原因。

## 线索 3：官方文档交叉验证

StepFun 官方文档（step-router 智能路由页 + 推理模型接入页）确认：

- step-router-v1 自动在 **deepseek-v4-pro**（复杂推理、长链路 Agent 决策）与 **step-3.7-flash / step-3.5-flash**（高频执行）之间调度
- 计费：**按实际命中的模型计费**——命中 pro 按 pro 计，命中 flash 按 flash 计
- 路由器按"消息轮数、输入 token 量、工具数量"等特征判定

结合线索 2 的函数名 `advisor` 与官方文档的引擎清单 → **advisor = deepseek-v4-pro**。

## 线索 4：验证 advisor 是否真的在"干活"

| 测试 | 结果 |
|---|---|
| 硬任务（并发 LRU 缓存）+ 强制指令 | advisor 块内含**完整专家分析**：数据结构选型、RLock 嵌套锁设计、TTL 惰性过期策略、实现要点——这是 pro 级别的输出 |
| 简单问题（2+2）+ 强制指令 | advisor 也真咨询："The answer is 4. You can respond with that directly." |
| 无指令的简单请求 | `advice_type=starting_out` 走形式模板，无实质内容 |

**结论：advisor 有两种模式——真咨询（full，任务完整交给 pro）与走形式（symbolic，象征性调用）。** 强制指令能把路由器从走形式推到真咨询。

## 线索 5：穷举"能不能 100% 锁定 pro"

| 手段 | 结果 |
|---|---|
| 直接点名 `deepseek-v4-pro` | ❌ 模型不存在（plan 通道不暴露） |
| 模型名变体 `:pro` / `-pro` / `/pro` | ❌ 全部不存在 |
| 官方参数强制路由 | ❌ 无此参数（文档确认自动调度） |
| `max_tokens` 撑到 32000（> flash 上限） | ❌ 仍走 flash |
| **双通道强制指令（system + 用户消息）** | ✅ 5/5 |

**结论：无法锁死，只能通过双通道指令把触发率推到很高。** 这是平台设计使然。

## 最后：真实环境验证

Claude Code + CC Switch 实际会话中：

1. hook 日志确认每条消息都注入了指令（`hook.log` 记录）
2. 实质任务（环境调研+报告）→ advisor 触发，且为**真咨询**——它审查了工具收集的数据，指出两个缺口（`wmic` 在 MSYS2 下失效、RAM 未查到），并给出报告组织建议
3. 闲聊消息不触发——路由器在正确省钱

## 一句话总结

**advisor = deepseek-v4-pro 不是官方文档明说的，而是通过"观察函数调用文本 → 文档交叉验证 → 内容质量检验 → 穷举锁定手段"这条证据链推断并验证的。** 这个结论 + 双通道注入方法，就是本项目存在的理由。
