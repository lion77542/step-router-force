# step-router-v1 路由原理

> 本文基于对 StepFun Step Plan 通道（`https://api.stepfun.com/step_plan/v1`）的黑盒实测反向推断，不代表官方实现细节。

## 名词表（快速入门）

| 名词 | 含义 |
|---|---|
| **StepFun（阶跃星辰）** | 中国 AI 公司，提供大模型 API 服务 |
| **Step Plan** | StepFun 的订阅套餐，通过专属通道 `api.stepfun.com/step_plan/v1` 以远低于按量计费的价格调用模型 |
| **step-router-v1** | Step Plan 通道的智能路由模型。本身不干活，按任务复杂度把请求自动分发给底层引擎（见下方两张表） |
| **deepseek-v4-pro** | 路由目标之一：复杂推理、长链路 Agent 决策引擎。1M 上下文，**生产级质量**，对应本项目的 advisor |
| **step-3.7-flash / step-3.5-flash** | 路由目标之二：高频、结构化执行引擎。快、便宜，是默认承载（绝大多数请求走它），幻觉率相对更高 |
| **advisor（顾问）** | 路由器内部对 deepseek-v4-pro 的称呼。路由器以"调用 advisor 函数"的形式咨询 pro 引擎，并在响应中留下 `[Advisor consultation]` 块 |
| **真咨询 (full)** | advisor 被完整调用，pro 的专家分析真实进入响应（有实质内容） |
| **走形式 (symbolic)** | advisor 被象征性调用，只输出 `advice_type=starting_out` 模板，pro 没真干活 |
| **双通道注入** | 本项目核心手法：在 system 与用户消息末尾各注入一条强制咨询指令，把路由器的咨询决定往 advisor 推 |
| **触发率** | 请求触发 advisor 调用的比例。概率性，无法 100% |

**一句话：Step Plan = 便宜的订阅套餐；step-router-v1 = 自动分发器；advisor = 分发器背后的 pro 引擎；本项目 = 让分发器在实质任务上把活交给 advisor。**

## 1. 路由器是一个 LLM 决策器

`step-router-v1` 不是静态转发规则，而是一个**小模型**。它每一轮请求都做同一个决策：读完整输入（system + messages + tools），然后生成下一段文本。而这"下一段文本"只有两种形态：

```
形态 A: 直接输出答案文本
        → 走 flash 通道（step-3.5/3.7-flash，省钱，默认承载）

形态 B: 输出内部函数调用
        <function-call>
          <function-name>advisor</function-name>
          <function-args>{"task": "<完整任务>"}</function-args>
        </function-call>
        → 平台收到后调用 deepseek-v4-pro（顾问），
          把 pro 的分析嵌入响应（[Advisor consultation] 块）
```

**路由决策 = 一次文本生成**。这是"提示词能影响它"的根本原因——它真的在读你的提示词。

## 2. 两种咨询模式：真咨询 vs 走形式

实测观察到 advisor 调用有两种形态：

| 模式 | 特征 | 触发条件 |
|---|---|---|
| **真咨询 (full)** | advisor 块内是完整任务 + 真实专家分析（Markdown 结构、设计要点、代码建议） | 复杂任务 + 强制指令 |
| **走形式 (symbolic)** | `advice_type=starting_out` + 一句话描述，无实质内容 | 简单任务被判定"不值得咨询"，但路由器仍象征性调用 |

**走形式模式的 advisor 块是垃圾**——它不代表 pro 干活了。真正有效的验证标准是：advisor 块内是否有实质内容。

## 3. 路由判定依据（官方文档口径）

官方文档声明：系统根据请求特征（**消息轮数、输入 token 量、工具数量**等）自动调度。实测补充：

- **显式指令 > 特征**：即使简单请求，带强制指令也可能触发咨询
- **"叙事式装复杂"无效**：在 system 里自称"我是长链路 agent 在做复杂任务"不会触发（0/5）——路由器不信叙事，只信显式指令和结构特征
- **reasoning_effort 不影响路由**：同样的请求 effort=high 与不设，触发率无差异
- **输出上限 trick 无效**：把 max_tokens 撑到 32000（超过 flash 的 16K 上限），路由器仍然走 flash——它不会因输出要求而切换引擎

## 4. 为什么双通道指令有效

路由器的训练先验是"复杂任务才调 advisor，简单任务直接答"（这是它存在的意义——省成本）。这个先验是概率性的，而显式指令与它对抗：

| 方案 | 触发率（小样本） |
|---|---|
| 无指令 + 简单问题 | 0/5 |
| 仅 system 强制指令 | 4/5 |
| 仅用户消息强制指令 | 3/5 |
| system + 用户消息双通道 | **5/5** |
| 模仿 advisor 内部函数语法 | 0/5 |

双通道（V5）的原理：

1. **重复强化**：同一指令出现两次，LLM 服从概率显著上升
2. **位置效应**：第二条指令紧贴最新用户消息——路由器"决定"就在那一瞬间，最后读到的指令权重最高
3. **失败冗余**：一条没拦住，另一条在决策点再拦一次

## 5. 协议差异（重要）

实测原生 Anthropic Messages 协议（`/v1/messages` + `output_config.effort`）触发率**远低于** OpenAI Chat Completions 协议（1/5 vs 4-5/5）。**路由器在 OpenAI 格式下更吃指令**。因此：

- 使用 CC Switch 时选 **OpenAI Chat Completions** API 格式（CC Switch 负责协议转换）
- 若自建代理（如 Anthropic→OpenAI 转换），保持转换后的 OpenAI 格式

## 6. 诚实边界

- **触发率是概率性的**：LLM 决策存在采样随机性，任何外部手段都无法做到 100%
- 真实 Claude Code 流量包含大量短消息（"继续"、"是的"），这类不触发是正常且正确的（闲聊不值得动用 pro）
- 命中 pro 按 pro 计费（官方计费口径：按实际命中模型计费）——这是合规使用，平台不会亏
