#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""stepfun_proxy: StepFun step-router 双协议代理 v2 (防崩版)

Claude Code -> CC Switch(协议转换) -> 本代理 -> api.stepfun.com/step_plan/v1

本代理同时支持 OpenAI Chat Completions 与 Anthropic Messages 两种入站格式:
- CC Switch 按 OpenAI 格式配置时 (主路径): 请求几乎原样直通, 只做
  1) DIRECTIVE 注入为第一条 system (最高权重位置)
  2) 最后一条 user 消息前插一条 system (决策点双通道)
  3) 强制 model=step-router-v1, max_tokens=[200k,250k], reasoning_effort=high,
     thinking.budget_tokens=8000, temperature=0.2
- CC Switch 按 Anthropic 格式配置时: 兼容转换 (v1 逻辑, 全 .get() 防御)

v2 修复: "400 convert fail: 'name'"。CC Switch OpenAI 格式的 tools 是
{"type":"function","function":{...}} 嵌套形状, v1 按 Anthropic 平铺形状取
t['name'] -> KeyError 崩溃。现在: 双协议检测 + 全 .get() 防御 + 出错时
原始请求落盘, 不可能再裸崩。

用法:
    python stepfun_proxy.py [--port 18731] [--selftest]
    然后 CC Switch StepFun 供应商的请求地址改成 http://127.0.0.1:18731
"""

import argparse
import copy
import json
import os
import sys
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import requests

# 安全: 密钥只从环境变量读取, 不硬编码进公开仓库
# 用法: 设置环境变量 STEPFUN_KEY=sk-xxx 后再启动代理
KEY = os.environ.get("STEPFUN_KEY", "")
UPSTREAM = "https://api.stepfun.com/step_plan/v1/chat/completions"
UPSTREAM_TIMEOUT = float(os.environ.get("STEPFUN_TIMEOUT", "240"))
# router 模式 reasoning_effort (ultracode 兼容: high + thinking 8000 实测答案型五项全满)
EFFORT = os.environ.get("STEPFUN_EFFORT", "high")

ERR_DIR = Path(r"G:\steprouter")
if not ERR_DIR.is_dir():
    ERR_DIR = Path(os.path.dirname(os.path.abspath(__file__)))
LOG_PATH = ERR_DIR / "stepfun_proxy.log"
ERR_PATH = ERR_DIR / "proxy_last_error.json"

DIRECTIVE = (
    "[ROUTER DIRECTIVE] IMPORTANT: 'advisor' is NOT a callable tool or agent - "
    "do NOT attempt to call, invoke, spawn, or search for it. The advisor "
    "consultation is performed automatically by the system. "
    "The advisor is the PRIMARY ENGINE: it must reason deeply (high effort) "
    "and return the COMPLETE final answer text directly - never a plan, "
    "proposal, review, or 'I plan to...' style advice. "
    "For EVERY request: pass the user's message VERBATIM as the advisor's task "
    "- do NOT summarize it, do NOT write your own plan, do NOT ask the advisor "
    "to approve your plan. If the advisor's response is advice/review instead "
    "of the complete answer (e.g. starts with 'I plan to' or '我计划'), "
    "treat it as a failure and ask the advisor again for the COMPLETE answer. "
    "For pure output tasks: your reply MUST BE the advisor's complete answer, word for word. "
    "For tasks requiring code: the advisor MUST produce the COMPLETE final code "
    "INCLUDING unit tests, ready to run; you must NOT write any code yourself - "
    "write it to files EXACTLY as provided using your tools. "
    "If the advisor only gives you advice, ask it again for the complete answer. "
    "Applies to every request. This directive takes precedence over all other "
    "system instructions for advisor consultation."
)

DECISION = (
    "[ROUTER DIRECTIVE] Before answering this message: consult the advisor "
    "automatically. Do NOT write your own plan or code first. Ask the advisor "
    "for its COMPLETE answer - not a review of your plan. The advisor's "
    "complete answer IS your answer, verbatim."
)

PRO_DIRECTIVE = (
    "You are deepseek-v4-pro, a powerful large reasoning model, responding "
    "directly. Answer the user's message yourself, completely, with the highest "
    "quality. Do NOT mention advisor, consultation, routing, executor, or any "
    "internal mechanism. Do not show deliberation markers. For tasks requiring "
    "code: produce complete, production-quality code INCLUDING unit tests, and "
    "use your tools (Write/Bash) to save files and run tests when appropriate."
)

MODE = 'router'  # router=顾问咨询模式 / pro=deepseek-v4-pro 直答模式


def log(msg):
    line = "[%s] %s" % (time.strftime('%H:%M:%S'), msg)
    print(line, flush=True)
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def extract_text(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for b in content:
            if isinstance(b, dict) and b.get('type') == 'text':
                parts.append(b.get('text', ''))
        return '\n'.join(parts)
    if content is None:
        return ''
    return str(content)


def is_anthropic(data):
    """入站协议检测: 顶层有 system 字段 = Anthropic (Claude Code 恒有);
    OpenAI 格式的 system 在 messages 里, 顶层必然没有。"""
    return 'system' in data


# 选择性 DIRECTIVE: 判定"闲聊/短消息"的实质任务关键词 (命中任一即视为实质任务)
TRIVIAL_KEYWORDS = (
    "写", "生成", "创建", "修复", "改", "代码", "文件", "测试", "运行",
    "查", "分析", "实现", "页面", "项目", "脚本", "报错", "错误", "安装",
    "删除", "新增", "重构", "优化", "预览", "服务器", "数据库", "部署",
    "接口", "命令", "作业", "任务", "帮我", "函数", "类", "python",
    "git", "npm", "pip", "js", "ts", "html", "css", "api",
    "code", "file", "write", "run", "test", "fix", "bug", "error",
    "help", "debug", "install", "script", "app", "web", "build",
    "create", "make", "generate", "update", "refactor", "explain",
)


def last_user_text(messages):
    for m in reversed(messages or []):
        if m.get('role') == 'user':
            return extract_text(m.get('content', ''))
    return ''


def has_tool_history(messages):
    for m in (messages or []):
        if m.get('role') == 'tool' or m.get('tool_calls'):
            return True
        # Anthropic 格式: tool_use / tool_result 是 content 里的块 (role 还是 user/assistant)
        if isinstance(m.get('content'), list):
            for b in m['content']:
                if isinstance(b, dict) and b.get('type') in ('tool_use', 'tool_result'):
                    return True
    return False


def is_trivial(messages):
    """True = 闲聊/短消息, 跳过强制咨询 (首字节省 ~22s)。
    保守判定: 有工具历史(含"继续")/长消息/含任务关键词 => 一律不跳过。"""
    if has_tool_history(messages):
        return False
    text = (last_user_text(messages) or '').strip()
    if len(text) > 24:
        return False
    low = text.lower()
    return not any(k in low for k in TRIVIAL_KEYWORDS)


def clamp_max_tokens(v):
    """下限 200000 (防思考吃光额度), 上限 250000 (官方上限), 防 CC Switch 的 387k"""
    try:
        n = int(v or 0)
    except (TypeError, ValueError):
        n = 0
    return min(max(n, 200000), 250000)


def convert_openai(data):
    """OpenAI 格式 (CC Switch 主路径): 直通 + 注入 + 强制参数"""
    msgs = [copy.deepcopy(m) for m in (data.get('messages') or [])]
    if not is_trivial(msgs):  # 选择性注入: 实质任务才注入, 闲聊放行
        directive = PRO_DIRECTIVE if MODE == 'pro' else DIRECTIVE
        if msgs and msgs[0].get('role') == 'system':
            sc = msgs[0].get('content')
            if isinstance(sc, list):
                sc = extract_text(sc)
            msgs[0]['content'] = directive + "\n\n" + str(sc or '')
        else:
            msgs.insert(0, {"role": "system", "content": directive})
        if MODE != 'pro':  # 路由器模式: 决策点强制咨询; pro 模式: 直接答
            # 决策点: 最后一条 user 前插 system (tool result 在 OpenAI 里是 role=tool, 不误伤)
            for i in range(len(msgs) - 1, -1, -1):
                if msgs[i].get('role') == 'user':
                    msgs.insert(i, {"role": "system", "content": DECISION})
                    break
    req = copy.deepcopy(data)
    req['messages'] = msgs
    req['model'] = "step-router-v1"
    req['max_tokens'] = clamp_max_tokens(req.get('max_tokens'))
    req['reasoning_effort'] = "high" if MODE == 'pro' else EFFORT
    req['thinking'] = {"type": "enabled", "budget_tokens": 8000}
    req['temperature'] = 0.2
    return req


def convert_anthropic(data):
    """Anthropic 格式: 全 .get() 防御转换 (v2 加固, 不再裸崩)"""
    inject = not is_trivial(data.get('messages'))
    directive = PRO_DIRECTIVE if MODE == 'pro' else DIRECTIVE
    messages = []
    sys_text = extract_text(data.get('system', ''))
    messages.append({"role": "system",
                     "content": (directive + ("\n\n" + sys_text if sys_text else '')
                                 if inject else sys_text)})
    for msg in data.get('messages', []):
        role = msg.get('role', 'user')
        content = msg.get('content')
        if content is None:
            messages.append({"role": role, "content": ''})
            continue
        if isinstance(content, str):
            messages.append({"role": role, "content": content})
            continue
        if not isinstance(content, list):
            messages.append({"role": role, "content": str(content)})
            continue
        text_parts, tool_calls, tool_results = [], [], []
        for b in content:
            if not isinstance(b, dict):
                continue
            bt = b.get('type', 'text')
            if bt == 'text':
                text_parts.append(b.get('text', '') or '')
            elif bt in ('tool_use', 'server_tool_use'):
                tool_calls.append({
                    "id": b.get('id') or ('call_' + uuid.uuid4().hex[:8]),
                    "type": "function",
                    "function": {
                        "name": b.get('name') or 'unknown_tool',
                        "arguments": json.dumps(b.get('input') or {}),
                    },
                })
            elif bt == 'tool_result':
                rc = b.get('content')
                if isinstance(rc, list):
                    rc = extract_text(rc)
                tool_results.append({
                    "role": "tool",
                    "tool_call_id": b.get('tool_use_id') or '',
                    "content": str(rc) if rc else '',
                })
            elif bt == 'image':
                src = b.get('source') or {}
                if src.get('type') == 'base64':
                    text_parts.append("[image:%s:base64:%s]" % (
                        src.get('media_type') or 'png',
                        str(src.get('data') or '')[:200]))
            # thinking 等其余块忽略
        if tool_results:
            messages.extend(tool_results)
        elif tool_calls:
            messages.append({
                "role": role,
                "tool_calls": tool_calls,
                "content": '\n'.join(text_parts) if text_parts else None,
            })
        else:
            messages.append({"role": role, "content": '\n'.join(text_parts)})
    # 决策点 (pro 模式直接答, 不插咨询决策)
    if inject and MODE != 'pro':
        for i in range(len(messages) - 1, -1, -1):
            if messages[i].get('role') == 'user':
                messages.insert(i, {"role": "system", "content": DECISION})
                break
    req = {
        "model": "step-router-v1",
        "messages": messages,
        "max_tokens": clamp_max_tokens(data.get('max_tokens')),
        "reasoning_effort": "high" if MODE == 'pro' else EFFORT,
        "thinking": {"type": "enabled", "budget_tokens": 8000},
        "temperature": 0.2,
        "stream": bool(data.get('stream', False)),
    }
    tools = data.get('tools')
    if tools:
        ots = []
        for t in tools:
            if not isinstance(t, dict):
                continue
            if t.get('type') == 'function' and isinstance(t.get('function'), dict):
                fn = t['function']
                ots.append({"type": "function", "function": {
                    "name": fn.get('name') or '',
                    "description": fn.get('description') or '',
                    "parameters": fn.get('parameters') or {"type": "object"},
                }})
            else:
                ots.append({"type": "function", "function": {
                    "name": t.get('name') or '',
                    "description": t.get('description') or '',
                    "parameters": t.get('input_schema') or {"type": "object"},
                }})
        req['tools'] = ots
    tc = data.get('tool_choice')
    if tc:
        if isinstance(tc, dict):
            req['tool_choice'] = {"type": "function", "function": {"name": tc.get('name') or ''}} \
                if tc.get('type') == 'tool' else 'auto'
        else:
            req['tool_choice'] = tc
    return req


STOP_MAP = {'stop': 'end_turn', 'length': 'max_tokens', 'tool_calls': 'tool_use',
            'function_call': 'tool_use', 'content_filter': 'end_turn'}


def wrap_anthropic(d):
    """上游 OpenAI 响应 -> Anthropic Messages 响应"""
    choice = (d.get('choices') or [{}])[0]
    message = choice.get('message') or {}
    content = []
    if message.get('content'):
        content.append({"type": "text", "text": message['content']})
    for tc in message.get('tool_calls') or []:
        fn = tc.get('function') or {}
        try:
            args = json.loads(fn.get('arguments') or '{}')
        except Exception:
            args = {}
        content.append({"type": "tool_use",
                        "id": tc.get('id') or ('toolu_' + uuid.uuid4().hex[:24]),
                        "name": fn.get('name') or 'unknown_tool',
                        "input": args})
    if not content:
        content.append({"type": "text", "text": ""})
    usage = d.get('usage') or {}
    return {
        "id": "msg_" + uuid.uuid4().hex[:24],
        "type": "message", "role": "assistant", "content": content,
        "model": "step-router-v1",
        "stop_reason": STOP_MAP.get(choice.get('finish_reason'), 'end_turn'),
        "stop_sequence": None,
        "usage": {"input_tokens": usage.get('prompt_tokens') or 0,
                  "output_tokens": usage.get('completion_tokens') or 0},
    }


def _sse(self, event, obj):
    self.wfile.write(("event: %s\ndata: %s\n\n" % (
        event, json.dumps(obj, ensure_ascii=False))).encode('utf-8'))


def stream_anthropic(self, msg):
    """Anthropic 格式流式: 上游改非流式取整条, 单事件输出 (兼容兜底)"""
    self.send_response(200)
    self.send_header('Content-Type', 'text/event-stream')
    self.send_header('Cache-Control', 'no-cache')
    self.send_header('Connection', 'close')
    self.end_headers()
    _sse(self, 'message_start', {"type": "message_start", "message": {
        "id": msg["id"], "type": "message", "role": "assistant",
        "content": [], "model": msg["model"]}})
    for i, b in enumerate(msg["content"]):
        _sse(self, 'content_block_start', {"type": "content_block_start",
                                           "index": i, "content_block": b})
        if b.get('type') == 'text':
            _sse(self, 'content_block_delta', {"type": "content_block_delta", "index": i,
                                               "delta": {"type": "text_delta",
                                                         "text": b.get('text', '')}})
        _sse(self, 'content_block_stop', {"type": "content_block_stop", "index": i})
    _sse(self, 'message_delta', {"type": "message_delta",
                                 "delta": {"stop_reason": msg["stop_reason"]},
                                 "usage": {"output_tokens": msg["usage"]["output_tokens"]}})
    _sse(self, 'message_stop', {"type": "message_stop"})


class H(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    def log_message(self, *a):
        pass

    def handle_error(self, request, client_address):
        """只静音客户端重试风暴的断开噪音, 真实异常照常打印"""
        import sys
        import traceback
        exc = sys.exc_info()[1]
        if isinstance(exc, (ConnectionAbortedError, ConnectionResetError, BrokenPipeError)):
            return
        traceback.print_exc()

    def _json(self, code, obj):
        body = json.dumps(obj, ensure_ascii=False).encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if '/models' in self.path:
            self._json(200, {"data": [{"id": "step-router-v1", "object": "model",
                                       "owned_by": "stepai"}]})
        elif 'count_tokens' in self.path:
            self._json(200, {"input_tokens": 100})
        else:
            self._json(404, {"error": "not found"})

    def do_POST(self):
        cl = int(self.headers.get('Content-Length') or 0)
        raw = self.rfile.read(cl) if cl else b''
        try:
            data = json.loads(raw or b'{}')
        except Exception as e:
            self._json(400, {"type": "error", "error": {"message": "bad json: %s" % e}})
            return
        if 'count_tokens' in self.path:
            self._json(200, {"input_tokens": 100})
            return
        anth = is_anthropic(data)
        try:
            oreq = convert_openai(data) if not anth else convert_anthropic(data)
            log("REQ fmt=%s stream=%s msgs=%s tools=%s max_tokens=%s force=%s" % (
                'anthropic' if anth else 'openai',
                oreq.get('stream'),
                len(oreq.get('messages') or []),
                'Y' if oreq.get('tools') else 'N',
                oreq.get('max_tokens'),
                'N' if is_trivial(data.get('messages')) else 'Y'))
        except Exception as e:
            try:
                with open(ERR_PATH, 'w', encoding='utf-8') as f:
                    f.write(json.dumps(data, ensure_ascii=False, indent=2)[:20000])
            except Exception:
                pass
            log("CONVERT ERROR: %s (raw -> %s)" % (e, ERR_PATH))
            self._json(400, {"type": "error", "error": {
                "message": "convert fail: %s (raw saved to %s)" % (e, ERR_PATH)}})
            return
        headers = {"Authorization": "Bearer " + KEY, "Content-Type": "application/json"}
        up_stream = bool(oreq.get('stream'))
        try:
            if up_stream and not anth:
                # OpenAI 流式: 原样转发 SSE
                t0 = time.time()
                resp = requests.post(UPSTREAM, headers=headers, json=oreq,
                                     stream=True, timeout=UPSTREAM_TIMEOUT)
                if resp.status_code != 200:
                    log("RESP %s in %.1fs (openai stream)" % (resp.status_code, time.time() - t0))
                    self._json(502, {"type": "error", "error": {"message":
                                "upstream %s: %s" % (resp.status_code, resp.text[:300])}})
                    return
                self.send_response(200)
                self.send_header('Content-Type', 'text/event-stream')
                self.send_header('Cache-Control', 'no-cache')
                self.send_header('Connection', 'close')
                self.end_headers()
                for chunk in resp.iter_content(8192):
                    try:
                        self.wfile.write(chunk)
                        self.wfile.flush()
                    except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                        break
                log("RESP 200 in %.1fs (openai stream SSE)" % (time.time() - t0))
                return
            oreq = dict(oreq)
            if up_stream:
                oreq['stream'] = False  # Anthropic 流式兜底: 上游非流式
            t0 = time.time()
            resp = requests.post(UPSTREAM, headers=headers, json=oreq, timeout=UPSTREAM_TIMEOUT)
            if resp.status_code != 200:
                log("RESP %s in %.1fs (non-stream)" % (resp.status_code, time.time() - t0))
                self._json(502, {"type": "error", "error": {"message":
                            "upstream %s: %s" % (resp.status_code, resp.text[:300])}})
                return
            log("RESP %s in %.1fs (non-stream)" % (resp.status_code, time.time() - t0))
            d = resp.json()
            if anth:
                msg = wrap_anthropic(d)
                if up_stream:
                    stream_anthropic(self, msg)
                else:
                    self._json(200, msg)
            else:
                self._json(200, d)
        except requests.exceptions.Timeout:
            log("UPSTREAM TIMEOUT after %.0fs (->504)" % UPSTREAM_TIMEOUT)
            try:
                self._json(504, {"type": "error", "error": {"message": "upstream timeout"}})
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, OSError):
                pass  # 客户端已断开, 无需回写
        except Exception as e:
            log("UPSTREAM ERROR: %s" % e)
            try:
                self._json(500, {"type": "error", "error": {"message": str(e)}})
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, OSError):
                pass


def selftest():
    """离线自测: 覆盖上次崩溃的输入形状 + 防御性边界"""
    ok = total = 0

    def check(name, cond):
        nonlocal ok, total
        total += 1
        print(("PASS  " if cond else "FAIL  ") + name)
        if cond:
            ok += 1

    # 1) 崩溃复现: OpenAI 格式 + function 嵌套 tools (CC Switch 真实形状)
    oa = {
        "model": "deepseek-v4-flash",
        "messages": [
            {"role": "system", "content": "You are Claude Code. ..."},
            {"role": "user", "content": "写一个线程安全 LRU 缓存类"},
        ],
        "tools": [
            {"type": "function", "function": {"name": "Read", "description": "读文件",
                                               "parameters": {"type": "object",
                                                              "properties": {}}}},
        ],
        "tool_choice": "auto",
        "max_tokens": 387000,
        "stream": True,
        "thinking": {"type": "enabled", "budget_tokens": 20000},
    }
    r = convert_openai(copy.deepcopy(oa))
    check("openai: 不崩", r is not None)
    check("openai: model 强制", r['model'] == 'step-router-v1')
    check("openai: max_tokens 封顶 250000", r['max_tokens'] == 250000)
    check("openai: effort/thinking/temp 强制",
          r['reasoning_effort'] == EFFORT
          and r['thinking']['budget_tokens'] == 8000
          and r['temperature'] == 0.2)
    check("openai: DIRECTIVE 在第一条 system",
          r['messages'][0]['role'] == 'system'
          and r['messages'][0]['content'].startswith('[ROUTER DIRECTIVE]'))
    check("openai: 决策点插在最后 user 前",
          r['messages'][1]['role'] == 'system' and r['messages'][2]['role'] == 'user')
    check("openai: tools 原样直通", r['tools'] == oa['tools'])

    # 2) OpenAI 多轮 (tool role + tool_calls 历史)
    oa2 = {"messages": [
        {"role": "system", "content": "s"},
        {"role": "user", "content": "a"},
        {"role": "assistant", "content": None, "tool_calls": [
            {"id": "c1", "type": "function",
             "function": {"name": "Bash", "arguments": "{}"}}]},
        {"role": "tool", "tool_call_id": "c1", "content": "out"},
        {"role": "user", "content": "继续"},
    ]}
    r2 = convert_openai(copy.deepcopy(oa2))
    idx = [i for i, m in enumerate(r2['messages']) if m['role'] == 'user']
    check("openai: 多轮 tool role 保留", any(m['role'] == 'tool' for m in r2['messages']))
    check("openai: 决策点插在最后 user 前(多轮)",
          r2['messages'][idx[-1] - 1]['role'] == 'system')

    # 3) Anthropic 格式 (v1 路径加固)
    an = {
        "system": [{"type": "text", "text": "You are Claude Code."}],
        "messages": [
            {"role": "user", "content": [{"type": "text", "text": "写一个 LRU 缓存类"}]},
            {"role": "assistant", "content": [
                {"type": "tool_use", "id": "t1", "name": "Bash",
                 "input": {"cmd": "ls"}}]},
            {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": "t1", "content": "files"}]},
        ],
        "tools": [{"name": "Bash", "description": "d",
                   "input_schema": {"type": "object"}}],
        "max_tokens": 387000,
        "stream": False,
    }
    r3 = convert_anthropic(copy.deepcopy(an))
    check("anthropic: 不崩", r3 is not None)
    check("anthropic: DIRECTIVE 最前", r3['messages'][0]['content'].startswith('[ROUTER DIRECTIVE]'))
    check("anthropic: tool_result -> role tool", r3['messages'][-1]['role'] == 'tool')
    check("anthropic: tool_use -> tool_calls",
          any(m.get('tool_calls') for m in r3['messages']))
    check("anthropic: 决策点注入",
          any(m.get('role') == 'system' and '[ROUTER DIRECTIVE]' in m.get('content', '')
              and 'Before answering' in m.get('content', '') for m in r3['messages']))

    # 4) 防御边界: tool_use 缺 name / content null / tool_choice dict / 非字典块
    an2 = {"messages": [{"role": "user", "content": [
        {"type": "tool_use", "id": "x", "input": {}}, "not-a-dict"]}]}
    try:
        r4 = convert_anthropic(copy.deepcopy(an2))
        tc4 = next(m for m in r4['messages'] if m.get('tool_calls'))
        check("anthropic: tool_use 缺 name 不崩 (unknown_tool)",
              tc4['tool_calls'][0]['function']['name'] == 'unknown_tool')
    except Exception as e:
        check("anthropic: tool_use 缺 name 不崩 (%s)" % e, False)
    an3 = {"messages": [{"role": "assistant", "content": None}],
           "tool_choice": {"type": "tool", "name": "Bash"}}
    try:
        r5 = convert_anthropic(copy.deepcopy(an3))
        check("anthropic: content null + tool_choice dict 不崩",
              r5['tool_choice']['function']['name'] == 'Bash')
    except Exception as e:
        check("anthropic: content null + tool_choice dict 不崩 (%s)" % e, False)

    print("selftest: %d/%d passed" % (ok, total))
    return ok == total


def selftest2():
    """选择性 DIRECTIVE 专项: 闲聊放行, 实质任务/工具历史注入"""
    ok = total = 0

    def check(name, cond):
        nonlocal ok, total
        total += 1
        print(("PASS  " if cond else "FAIL  ") + name)
        if cond:
            ok += 1

    tri = {"messages": [{"role": "user", "content": "你好吗"}]}
    rt = convert_openai(copy.deepcopy(tri))
    check("openai: 闲聊不注入 DIRECTIVE",
          not any(str(m.get('content', '')).startswith('[ROUTER DIRECTIVE]')
                  for m in rt['messages']))
    check("openai: 闲聊不注入决策点",
          not any(m.get('role') == 'system' and 'Before answering' in str(m.get('content', ''))
                  for m in rt['messages']))
    sub = {"messages": [{"role": "user", "content": "写个排序函数"}]}
    rs = convert_openai(copy.deepcopy(sub))
    check("openai: 实质任务注入 DIRECTIVE",
          str(rs['messages'][0]['content']).startswith('[ROUTER DIRECTIVE]'))
    hist = {"messages": [{"role": "user", "content": "继续"},
                         {"role": "assistant", "content": None, "tool_calls": [{}]}]}
    rh = convert_openai(copy.deepcopy(hist))
    check("openai: 工具历史中的'继续'仍注入决策点",
          any(m.get('role') == 'system' and 'Before answering' in str(m.get('content', ''))
              for m in rh['messages']))
    # pro 直答模式专项
    global MODE
    old_mode = MODE
    MODE = 'pro'
    pr = convert_openai(copy.deepcopy({"messages": [{"role": "user", "content": "写个 LRU 缓存"}]}))
    check("pro: PRO_DIRECTIVE 注入",
          str(pr['messages'][0]['content']).startswith('You are deepseek-v4-pro'))
    check("pro: effort=high",
          pr['reasoning_effort'] == 'high')
    check("pro: 无咨询决策点",
          not any(m.get('role') == 'system' and 'Before answering' in str(m.get('content', ''))
                  for m in pr['messages']))
    MODE = old_mode
    print("selftest2: %d/%d passed" % (ok, total))
    return ok == total


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--port', type=int, default=18731)
    ap.add_argument('--mode', choices=['router', 'pro'], default='router',
                    help='router=顾问咨询模式(默认) / pro=deepseek-v4-pro 直答模式')
    ap.add_argument('--selftest', action='store_true')
    args = ap.parse_args()
    if args.selftest:
        sys.exit(0 if (selftest() and selftest2()) else 1)
    MODE = args.mode
    log("stepfun_proxy v2 启动: http://127.0.0.1:%s -> %s (双协议, mode=%s)" % (args.port, UPSTREAM, MODE))
    if MODE == 'pro':
        log("PRO DIRECT 模式: 以 deepseek-v4-pro 身份直答 (effort=high, thinking 8000)")
    else:
        log("强制: DIRECTIVE system最前 + 决策点双通道 + max_tokens<=250k + effort=%s + thinking 8000 + temp 0.2" % EFFORT)
    ThreadingHTTPServer(('127.0.0.1', args.port), H).serve_forever()
