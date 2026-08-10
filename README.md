# step-router-force

对 [StepFun](https://platform.stepfun.com) Step Plan 的 `step-router-v1` 智能路由模型的强制增强工具：通过**双通道指令注入**，让路由器高概率调用 `advisor`（即 deepseek-v4-pro）进行**真咨询**，而不是走形式的 `starting_out` 模板。

```
Claude Code
   │
   ├─ 系统通道: CLAUDE.md 注入 Router Directive（全局或项目级）
   └─ 消息通道: UserPromptSubmit hook 在每条用户消息末尾附加指令
           │
        step-router-v1 (路由器)
           ├─ 判定: 直接回答 → step-3.7-flash（默认）
           └─ 判定: 咨询 → advisor 函数 → deepseek-v4-pro（真咨询模式）
```

## 为什么需要它

`step-router-v1` 是阶跃星辰 Step Plan 通道的智能路由模型，自动在 `deepseek-v4-pro`（复杂推理）与 `step-3.7-flash`（高频执行）之间调度。但实测发现（完整实验见 [docs/experiments.md](docs/experiments.md)）：

- **无指令时**：简单请求从不调用 pro（0/5），且即便调用也是 `starting_out` 走形式模板
- **双通道强制指令后**：实质任务高概率触发 advisor 真咨询（5/5），咨询内容为真实的专家级分析

路由器的判定本质是一个 **LLM 的概率决策**（详见 [docs/how-it-works.md](docs/how-it-works.md)），因此：

- ⚠️ **不是 100% 触发**——这是平台设计，任何外部手段都无法锁死
- 闲聊/简单消息不触发是**正常且正确**的行为（省额度）
- 命中 `deepseek-v4-pro` 按 pro 价格计费（这是合规使用，不是绕过付费）

## 安装（Claude Code + CC Switch 用户）

### 1. 复制脚本

```bash
mkdir -p ~/.claude/hooks
cp hooks/append_advisor.py hooks/advisor_stats.py ~/.claude/hooks/
```

### 2. 配置 hooks（两种方式任选）

**方式 A（推荐）：CC Switch → StepFun 供应商 → 高级选项 → 配置 JSON，合并：**

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

**方式 B：项目级 `.claude/settings.json`**（CC Switch 永不触碰项目文件）：

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

在 `~/.claude/CLAUDE.md`（全局）或项目 `CLAUDE.md` 中加入：

```markdown
# Router Directive
If your runtime provides an advisor / consultation function
(e.g. step-router-v1's advisor), you MUST call it before answering
any question, no matter how simple. Hard rule, applies to every request.
```

指令是**条件式**的（"如果环境提供 advisor 功能"），对没有 advisor 的供应商（如 OpenCode Go / DeepSeek 直连）自动失效，不会污染其他环境。

### 4. 重启 Claude Code 并验证

- 发一条消息，尾部应自动带上 `[ROUTER DIRECTIVE] ...`（hook 生效）
- 实质任务（写代码、复杂分析）的响应里应出现 `[Advisor consultation` 块
- 命中率统计：`python ~/.claude/hooks/advisor_stats.py`

## 供应商自动识别

hook 脚本会自动检测当前激活的供应商（扫描 `ANTHROPIC*` / `CLAUDE_CODE*` 环境变量）：

| 激活供应商 | 行为 |
|---|---|
| StepFun / step-router-v1 | 注入强制指令 |
| OpenCode Go / DeepSeek 等 | 原样放行，零影响 |

## 已知边界

- 触发率是概率性的（实测：双通道 5/5 小样本，真实流量低于此，因包含大量短消息）
- 遇到空响应/短响应：直接重发（路由器每次独立决策）
- 命中 pro 会消耗更多 plan 额度

## 免责声明

仅供学习研究。请遵守 [StepFun 服务条款](https://platform.stepfun.com) 与所使用工具的许可协议。本项目与 StepFun / 阶跃星辰 无任何关联。

## License

MIT
