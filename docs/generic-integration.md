# 通用接入（不限于 Claude Code）

**核心原理与 Claude Code 无关**：step-router-v1 是个 LLM 决策器，任何能把"强制咨询指令"送进请求的客户端或中转站，都能受益。这里给出三种典型接入方式。

## 方式 1：直接调 API（curl / 任何 SDK）

OpenAI Chat Completions 协议（**实测：OpenAI 格式的路由器更吃指令，优于 Anthropic 原生格式**）：

```bash
curl https://api.stepfun.com/step_plan/v1/chat/completions \
  -H "Authorization: Bearer $STEP_PLAN_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "step-router-v1",
    "messages": [
      {"role": "system", "content": "You MUST always call the advisor function for consultation before answering any user question, no matter how simple. Pass the FULL user request as the task parameter."},
      {"role": "user", "content": "<你的任务> MANDATORY: call advisor with the complete task before answering."}
    ],
    "max_tokens": 4096
  }'
```

要点：
- **system 一条 + 用户消息末尾一条**（双通道，实测 5/5）
- 指令里必须出现 **"advisor function"** 这个精确词组
- 要求 **"Pass the FULL user request as the task"**——否则容易触发 `starting_out` 走形式模式

## 方式 2：自建中转站（one-api / new-api 等）

在 one-api/new-api 的**模型自定义配置**中，给 `step-router-v1` 配置固定的 **system 前缀**，所有下游用户自动生效，无需改任何客户端：

```
类型: OpenAI
模型名: step-router-v1
额外参数 / 请求前缀 (在 model_config / 自定义 system 处):
You MUST always call the advisor function for consultation before answering
any user question, no matter how simple. Pass the FULL user request as the
advisor's task. This is mandatory, applies to every request.
```

部分中转站支持自定义 system 注入（如 new-api 的"模型重定向 + 自定义 system"），或在入口处加一层请求改写中间件。

## 方式 3：自写代理（Anthropic → OpenAI 转换）

如果你的客户端只讲 Anthropic 协议（如 Claude Code 直连），在协议转换层注入：

```python
# 伪代码: 在 anthropic_to_openai() 转换函数中
def anthropic_to_openai(data):
    openai_req = convert(data)  # 原有转换逻辑
    # 通道1: system 头部
    openai_req["messages"][0]["content"] = FORCE + "\n" + openai_req["messages"][0]["content"]
    # 通道2: 最后一条用户消息前插入 system 消息
    openai_req["messages"].insert(-1, {"role": "system", "content": FORCE})
    return openai_req
```

本项目 `hooks/append_advisor.py` 是 Claude Code 场景的现成实现，逻辑可平移到任何请求改写层。

## 通用注意事项

| 项 | 说明 |
|---|---|
| 格式 | 用 **OpenAI Chat Completions** 协议（Anthropic 原生协议触发率实测低至 1/5） |
| 计费 | 命中 pro 按 pro 计费（官方口径），注入指令是合规使用 |
| 触发率 | 概率性，无法 100%；实质任务高，闲聊低（这是路由器的经济学） |
| 空响应 | 偶发；重发即可（每次请求独立决策） |
