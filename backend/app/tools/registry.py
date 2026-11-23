from collections.abc import Callable

from app.tools.base import Permission, Tool, ToolInput

REGISTRY: dict[str, Tool] = {}


def tool(
    name: str,
    description: str,
    input_model: type[ToolInput],
    *,
    permission: Permission,
    category: str,
    timeout_s: float = 20.0,
    always_confirm: bool = False,
) -> Callable:
    """Register an async function `(ctx, args) -> ToolResult` as a tool."""

    def deco(fn):
        if name in REGISTRY:
            raise ValueError(f"duplicate tool {name}")
        REGISTRY[name] = Tool(name, description, input_model, fn, permission, category, timeout_s, always_confirm)
        return fn

    return deco


def precheck(name: str) -> Callable:
    """Attach a pre-approval check to an already registered tool."""

    def deco(fn):
        REGISTRY[name].precheck = fn
        return fn

    return deco


def load_builtin_tools() -> dict[str, Tool]:
    # Importing the modules registers their tools.
    from app.core.config import get_settings
    from app.tools import builtin  # noqa: F401

    if not get_settings().desktop_tools:
        # In a container (or on a server) "open an app", "run a command" or "open a URL" would act on the server,
        # not on the user's desktop: leave those tools out entirely.
        for name in DESKTOP_TOOLS:
            REGISTRY.pop(name, None)
    return REGISTRY


DESKTOP_TOOLS = ("run_command", "open_app", "open_url", "run_workflow")
