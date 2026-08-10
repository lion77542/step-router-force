#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""step-router-force: Claude Code UserPromptSubmit hook (v6)

仅在 stepfun 供应商(step-router-v1)激活时, 在用户消息末尾附加强制
"真咨询"指令, 让 step-router-v1 高概率调用 advisor(deepseek-v4-pro)。
其他供应商(OpenCode Go / DeepSeek 直连等)原样放行, 零影响。

v6 指令 = 禁止 executor 总结/自写计划/问审批; 必须逐字传完整任务给
advisor, 并逐字采用 advisor 的完整答案 (实测纯问答输出=advisor)。

配套参数 (实测关键):
- max_tokens 必须大 (>=60000), 否则 reasoning_content 思考吃光额度
  → finish=length / content 为空 (见 docs/experiments.md 第7节)
- reasoning_effort=low 减少思考吃额度

安全设计:
- 编码: ensure_ascii=True, 任何平台/任何语言都不会崩
- 幂等: 消息里已有 [ROUTER DIRECTIVE] 就不重复附加
- 容错: 任何异常都原样放行, 绝不阻塞用户
- 日志: 每次触发写入 hook.log
"""

import sys
import json
import os
import time
from pathlib import Path

FORCE = (
    "\n\n[ROUTER DIRECTIVE] Before answering, you MUST consult the advisor. "
    "CRITICAL: pass the user's message VERBATIM as the advisor's task - do NOT "
    "summarize it, do NOT write your own plan, do NOT ask the advisor to approve "
    "your plan. The advisor must return the COMPLETE final answer text. "
    "Your reply MUST BE the advisor's complete answer, word for word. "
    "If the advisor only gives you advice, ask it again for the complete answer."
)

LOG_PATH = Path(os.environ.get(
    "STEP_ROUTER_FORCE_LOG",
    os.path.expanduser("~/.claude/hooks/hook.log"),
))


def is_stepfun():
    for key, value in os.environ.items():
        if key.startswith("ANTHROPIC") or key.startswith("CLAUDE_CODE"):
            lowered = (value or "").lower()
            if "stepfun" in lowered or "step-router" in lowered:
                return True
    return False


def _log(action):
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} [{action}]\n")
    except Exception:
        pass


def main():
    action = "passthrough"
    try:
        data = json.load(sys.stdin)
        prompt = data.get("prompt", "")
        if (
            is_stepfun()
            and isinstance(prompt, str)
            and prompt.strip()
            and "[ROUTER DIRECTIVE]" not in prompt
        ):
            data["prompt"] = prompt.rstrip() + FORCE
            action = "inject"
        elif not is_stepfun():
            action = "passthrough(not-stepfun)"
        else:
            action = "skip(already-has)"
    except Exception as exc:
        action = f"error({exc})"

    _log(action)

    sys.stdout.write(json.dumps(data, ensure_ascii=True))


if __name__ == "__main__":
    main()
