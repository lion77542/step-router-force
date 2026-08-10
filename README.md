# step-router-force

让 StepFun Step Plan 的 `step-router-v1` 高概率调用 **advisor（deepseek-v4-pro）进行真咨询**的双通道指令注入工具集。

**核心发现：step-router-v1 的 `advisor` 函数就是 deepseek-v4-pro 引擎。** 这不是官方明说的，而是通过黑盒观察 + 文档交叉验证 + 内容质量检验一步步推断出来的——完整侦探过程见 [docs/discovery.md](docs/discovery.md)。

## 为什么值得用

`step-router-v1` 是阶跃星辰 Step Plan 的智能路由模型，自动在 `deepseek-v4-pro`（复杂推理）与 `step-3.7-flash`（高频执行）之间调度。实测发现：

- **无指令时**：简单请求从不调用 pro（0/5），且即便调用也是 `starting_out` 走形式模板
- **双通道强制指令后**：实质任务高概率触发 advisor 真咨询（5/5），咨询内容为真实的专家级分析

路由器的判定本质是 **LLM 的概率决策**（详见 [docs/how-it-works.md](docs/how-it-works.md)），因此：

- ⚠️ **不是 100% 触发**——平台设计使然，任何外部手段无法锁死
- 闲聊/简单消息不触发是**正常且正确**的（省额度）
- 命中 pro 按 pro 价格计费（合规使用，不是绕过付费）

## 快速开始（Claude Code + CC Switch）

### 1. 复制脚本

```bash
mkdir -p ~/.claude/hooks
cp hooks/append_advisor.py hooks/advisor_stats.py ~/.claude/hooks/
```

### 2. 配置 hooks

**CC Switch**（StepFun 供应商 → 高级选项 → 配置 JSON，合并）：

```json
"hooks": {
  "UserPromptSubmit": [
    {
      "hooks": [
        { "type": "command", "command": "python C:/Users/<你的用户名>/.claude/hooks/append_advisor.py", "timeout": 10 }
      ]
    }
  ]
}
```

或**项目级** `.claude/settings.json`（CC Switch 不触碰项目文件）：

```json
{
  "hooks": {
    "UserPromptSubmit": [
      {
        "hooks": [
          { "type": "command", "command": "python C:/Users/<你的用户名>/.claude/hooks/append_advisor.py", "timeout": 10 }
        ]
      }
    ]
  }
}
```

### 3. 配置 CLAUDE.md（系统通道）

在 `~/.claude/CLAUDE.md`（全局）或项目 `CLAUDE.md` 加入：

```markdown
# Router Directive
If your runtime provides an advisor / consultation function
(e.g. step-router-v1's advisor), you MUST call it before answering
any question, no matter how simple. Hard rule, applies to every request.
```

指令是**条件式**的，对没有 advisor 的供应商（OpenCode Go / DeepSeek 直连）自动失效，不污染其他环境。

### 4. 重启并验证

- 发消息，尾部应自动带 `[ROUTER DIRECTIVE] ...`（hook 生效）
- 实质任务响应里应出现 `[Advisor consultation` 块
- 命中率统计：`python ~/.claude/hooks/advisor_stats.py`

## 通用接入（不限于 Claude Code）

**原理与 Claude Code 无关**——任何能把"强制咨询指令"送进请求的客户端、中转站、代理都能用：

- **直连 API**：OpenAI Chat Completions 格式 + system/消息双通道注入（实测 OpenAI 格式优于 Anthropic 原生格式，详见 [docs/generic-integration.md](docs/generic-integration.md)）
- **中转站（one-api / new-api）**：给 `step-router-v1` 配固定 system 前缀，下游全部自动生效
- **自写代理**：在 Anthropic→OpenAI 转换层注入（本项目的 hook 逻辑可直接平移）

## 供应商自动识别

hook 扫描 `ANTHROPIC*` / `CLAUDE_CODE*` 环境变量自动判断：

| 激活供应商 | 行为 |
|---|---|
| StepFun / step-router-v1 | 注入强制指令 |
| OpenCode Go / DeepSeek 等 | 原样放行，零影响 |

## 文档

| 文档 | 内容 |
|---|---|
| [docs/discovery.md](docs/discovery.md) | **发现过程**：如何推断出 advisor = deepseek-v4-pro（项目核心价值） |
| [docs/how-it-works.md](docs/how-it-works.md) | 路由原理：LLM 决策器、两种咨询模式、为什么双通道有效 |
| [docs/experiments.md](docs/experiments.md) | 实验矩阵：V0–V6 穷举 + 真实会话数据 |
| [docs/generic-integration.md](docs/generic-integration.md) | 通用接入：直连 / 中转站 / 自写代理 |

## 已知边界

- 触发率概率性（双通道小样本 5/5；真实流量含短消息，整体低于此）
- 偶发空响应/短响应：重发即可
- 命中 pro 消耗更多 plan 额度

## 参与维护

路由器是黑盒，**社区数据**是这个项目的命脉。欢迎：

- 提交你的**触发率实测数据**（环境/方案/任务类型/命中率）
- 报告新发现：新参数、advisor 新行为、空响应根因、平台行为变化
- 其他客户端/中转站接入实现、跨平台改进、英文翻译

详见 [CONTRIBUTING.md](CONTRIBUTING.md)。

## 免责声明

仅供学习研究。请遵守 [StepFun 服务条款](https://platform.stepfun.com) 与所使用工具的许可协议。本项目与 StepFun / 阶跃星辰 无任何关联。

## License

MIT
