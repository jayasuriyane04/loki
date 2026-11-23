"""Development and system tools, all bounded by config/automation.json allowlists.

LOKI never runs arbitrary shell commands: the model can only pick a command/app/workflow *id*, the argv comes
from the allowlist, there is no shell, and commands always require the user's explicit approval.
"""

import asyncio
import json
import logging
import os
import platform
import shutil
import subprocess
import sys
import time
import webbrowser
from collections import deque
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlparse

import psutil
from pydantic import Field

from app.tools.base import NoInput, ToolContext, ToolError, ToolInput, ToolResult
from app.tools.registry import REGISTRY, precheck, tool

ROOT = Path(__file__).resolve().parents[4]  # the LOKI folder
CONFIG = Path(__file__).resolve().parents[3] / "config" / "automation.json"


@lru_cache
def automation() -> dict:
    try:
        return json.loads(CONFIG.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"commands": {}, "apps": {}, "workflows": {}}


def _choices(kind: str) -> str:
    return "; ".join(f"{k}: {v.get('description', '')}" for k, v in automation().get(kind, {}).items()) or "none configured"


def _argv(spec: dict) -> tuple[list[str], Path]:
    cwd = (ROOT / spec.get("cwd", ".")).resolve()
    argv = list(spec["argv"])
    if "/" in argv[0] or "\\" in argv[0]:  # relative executable → relative to the command's folder
        argv[0] = str((cwd / argv[0]).resolve())
    elif shutil.which(argv[0]):
        argv[0] = shutil.which(argv[0])
    return argv, cwd


# ---------- application log ----------
class RingBufferHandler(logging.Handler):
    """Keeps the last N log records in memory so LOKI can inspect its own logs."""

    def __init__(self, capacity: int = 1000) -> None:
        super().__init__()
        self.records: deque[logging.LogRecord] = deque(maxlen=capacity)

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


LOG_BUFFER = RingBufferHandler()


class LogsIn(ToolInput):
    lines: int = Field(40, ge=5, le=200)
    level: str = Field("WARNING", description="Minimum level: DEBUG, INFO, WARNING, ERROR")
    contains: str | None = Field(None, max_length=100)


@tool("read_app_logs", "Inspect LOKI's own recent backend logs (for debugging LOKI).", LogsIn, permission="read",
      category="development")
async def read_app_logs(ctx: ToolContext, a: LogsIn) -> ToolResult:
    min_level = logging.getLevelName(a.level.upper())
    if not isinstance(min_level, int):
        raise ToolError("level must be DEBUG, INFO, WARNING or ERROR.")
    recs = [r for r in LOG_BUFFER.records if r.levelno >= min_level
            and (not a.contains or a.contains.lower() in r.getMessage().lower())][-a.lines:]
    if not recs:
        return ToolResult(f"No log records at {a.level} or above.", "Checked LOKI's logs: nothing to report")
    lines = [f"{time.strftime('%H:%M:%S', time.localtime(r.created))} {r.levelname} {r.name}: {r.getMessage()[:300]}" for r in recs]
    return ToolResult("\n".join(lines), f"Read {len(recs)} log lines ({a.level}+)")


# ---------- system info ----------
@tool("system_info", "Basic information about this computer: OS, CPU, memory, disk, GPU, battery.", NoInput,
      permission="read", category="system")
async def system_info(ctx: ToolContext, a: NoInput) -> ToolResult:
    def collect() -> str:
        vm = psutil.virtual_memory()
        disk = psutil.disk_usage(str(ROOT.anchor))
        lines = [
            f"OS: {platform.system()} {platform.release()} ({platform.version()})",
            f"CPU: {platform.processor() or 'unknown'}, {psutil.cpu_count(logical=False)} cores / "
            f"{psutil.cpu_count()} threads, load {psutil.cpu_percent(interval=0.3)}%",
            f"Memory: {vm.used / 1e9:.1f} of {vm.total / 1e9:.1f} GB used ({vm.percent}%)",
            f"Disk {ROOT.anchor}: {disk.used / 1e9:.0f} of {disk.total / 1e9:.0f} GB used ({disk.percent}%)",
        ]
        if (bat := psutil.sensors_battery()) is not None:
            lines.append(f"Battery: {bat.percent:.0f}% {'charging' if bat.power_plugged else 'on battery'}")
        if shutil.which("nvidia-smi"):
            try:
                out = subprocess.run(
                    ["nvidia-smi", "--query-gpu=name,utilization.gpu,memory.used,memory.total,temperature.gpu",
                     "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=5, check=True,
                ).stdout.strip()
                name, util, used, total, temp = [x.strip() for x in out.split(",")]
                lines.append(f"GPU: {name}, {util}% busy, {used}/{total} MiB, {temp}°C")
            except (subprocess.SubprocessError, ValueError):
                pass
        return "\n".join(lines)

    text = await asyncio.to_thread(collect)
    return ToolResult(text, "Checked system info")


# ---------- dev commands ----------
class CommandIn(ToolInput):
    command: str = Field(description="Command id from the allowlist")


@tool("run_command", "Run one of the user's pre-approved development commands (by id) and return its output. "
      "Always asks the user first.", CommandIn, permission="confirm", category="development", timeout_s=310,
      always_confirm=True)
async def run_command(ctx: ToolContext, a: CommandIn) -> ToolResult:
    spec = automation().get("commands", {}).get(a.command)
    if spec is None:
        raise ToolError(f"Unknown command {a.command!r}. Allowed: {_choices('commands')}")
    argv, cwd = _argv(spec)
    start = time.perf_counter()
    try:
        proc = await asyncio.create_subprocess_exec(
            *argv, cwd=str(cwd), stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
            stdin=asyncio.subprocess.DEVNULL, env={**os.environ, "NO_COLOR": "1", "PYTHONIOENCODING": "utf-8"},
        )
    except (FileNotFoundError, PermissionError) as e:
        raise ToolError(f"Couldn't start {argv[0]} ({type(e).__name__}).") from e
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=float(spec.get("timeout_s", 60)))
    except TimeoutError:
        proc.kill()
        raise ToolError(f"{a.command} timed out after {spec.get('timeout_s', 60)} s.") from None
    text = out.decode("utf-8", errors="replace")
    secs = time.perf_counter() - start
    tail = text[-6000:] if len(text) > 6000 else text
    return ToolResult(f"$ {' '.join(spec['argv'])}  (exit code {proc.returncode}, {secs:.1f}s)\n{tail}",
                      f"Ran {a.command}: exit {proc.returncode}", {"exit_code": proc.returncode, "output": tail})


# ---------- desktop ----------
class OpenUrlIn(ToolInput):
    url: str = Field(max_length=2000)


@tool("open_url", "Open a website in the user's default browser on this computer.", OpenUrlIn, permission="confirm",
      category="system")
async def open_url(ctx: ToolContext, a: OpenUrlIn) -> ToolResult:
    if urlparse(a.url).scheme not in ("http", "https"):
        raise ToolError("Only http(s) links can be opened.")
    ok = await asyncio.to_thread(webbrowser.open, a.url)
    if not ok:
        raise ToolError("No browser could be opened.")
    return ToolResult(f"Opened {a.url}", f"Opened {urlparse(a.url).hostname}")


class OpenAppIn(ToolInput):
    app: str = Field(description="App id from the allowlist")


@tool("open_app", "Open one of the user's approved applications (by id).", OpenAppIn, permission="reversible",
      category="system")
async def open_app(ctx: ToolContext, a: OpenAppIn) -> ToolResult:
    spec = automation().get("apps", {}).get(a.app)
    if spec is None:
        raise ToolError(f"Unknown app {a.app!r}. Allowed: {_choices('apps')}")
    argv, cwd = _argv({**spec, "cwd": spec.get("cwd", ".")})
    flags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS if sys.platform == "win32" else 0
    try:
        await asyncio.to_thread(subprocess.Popen, argv, cwd=str(cwd), stdin=subprocess.DEVNULL,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=flags)
    except (FileNotFoundError, PermissionError, OSError) as e:
        raise ToolError(f"Couldn't open {a.app} ({type(e).__name__}).") from e
    return ToolResult(f"Opened {spec.get('description', a.app)}.", f"Opened {spec.get('description', a.app)}")


class WorkflowIn(ToolInput):
    workflow: str = Field(description="Workflow id from the allowlist")


@tool("run_workflow", "Run one of the user's predefined workflows (a fixed sequence of tool steps).", WorkflowIn,
      permission="reversible", category="system", timeout_s=400)
async def run_workflow(ctx: ToolContext, a: WorkflowIn) -> ToolResult:
    wf = automation().get("workflows", {}).get(a.workflow)
    if wf is None:
        raise ToolError(f"Unknown workflow {a.workflow!r}. Allowed: {_choices('workflows')}")
    runner = ctx.services["run_step"]  # executes a nested tool call through the normal permission/approval path
    outputs = []
    for step in wf["steps"]:
        if step["tool"] not in REGISTRY:
            outputs.append(f"## {step['tool']}\n(unknown tool, skipped)")
            continue
        result = await runner(step["tool"], step.get("args", {}))
        outputs.append(f"## {step['tool']}\n{result}")
    return ToolResult("\n\n".join(outputs), f"Ran workflow {a.workflow} ({len(wf['steps'])} steps)")


@precheck("run_command")
async def _pre_run_command(ctx: ToolContext, a: CommandIn) -> str:
    spec = automation().get("commands", {}).get(a.command)
    if spec is None:
        raise ToolError(f"Unknown command {a.command!r}. Allowed: {_choices('commands')}")
    return f"Run “{spec.get('description', a.command)}”: `{' '.join(spec['argv'])}` in {spec.get('cwd', '.')}"


@precheck("open_url")
async def _pre_open_url(ctx: ToolContext, a: OpenUrlIn) -> str:
    if urlparse(a.url).scheme not in ("http", "https"):
        raise ToolError("Only http(s) links can be opened.")
    return f"Open {a.url} in your browser"


def describe_automation() -> str:
    """For the system prompt: what the allowlists contain (nothing when the desktop tools are switched off)."""
    if "run_command" not in REGISTRY:
        return "Desktop actions (running commands, opening apps or websites) are not available in this deployment."
    return (f"Allowed commands (run_command): {_choices('commands')}.\nApps (open_app): {_choices('apps')}.\n"
            f"Workflows (run_workflow): {_choices('workflows')}.")
