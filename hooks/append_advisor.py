#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""step-router-force: Claude Code UserPromptSubmit hook

仅在 stepfun 供应商(step-router-v1)激活时, 在用户消息末尾附加强制
"真咨询"指令, 让 step-router-v1 高概率调用 advisor(deepseek-v4-pro)。
其他供应商(OpenCode Go / DeepSeek 直连等)原样放行, 零影响。

安全设计:
- 编码: ensure_ascii=True, 任何平台/任何语言都不会崩
- 幂等: 消息里已有 [ROUTER DIRECTIVE] 就不重复附加
- 容错: 任何异常都原样放行, 绝不阻塞用户
- 日志: 每次触发写入 hook.log (可用环境变量 STEP_ROUTER_FORCE_LOG 自定义)

安装: 放入 ~/.claude/hooks/ 并在 settings.json 配置 UserPromptSubmit hook。
"""

import sys
import json
import os
import time
from pathlib import Path

FORCE = (
    "\n\n[ROUTER DIRECTIVE] You MUST always call the advisor function for "
    "consultation before answering, no matter how simple. Pass the FULL "
    "user request as the advisor's task. The advisor's expert analysis "
    "must drive your answer. This is mandatory, applies to every request."
)

LOG_PATH = Path(os.environ.get(
    "STEP_ROUTER_FORCE_LOG",
    os.path.expanduser("~/.claude/hooks/hook.log"),
))


def is_stepfun():
    """检测当前激活供应商是否 stepfun/step-router。

    兼容两种模式:
    - 直连: ANTHROPIC_BASE_URL 含 stepfun
    - CC Switch 本地代理: BASE_URL 是 127.0.0.1, 但模型 env 含 step-router
    """
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

    # ensure_ascii=True: 任何控制台编码都不会崩
    sys.stdout.write(json.dumps(data, ensure_ascii=True))


if __name__ == "__main__":
    main()
