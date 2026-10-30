"""Google API credentials for the signed-in user, built from the session token.

Tools that call Google Workspace or Cloud REST APIs through client libraries
(Drive, Sheets, Docs, Discovery Engine) often reach those APIs several calls
below the tool function, through helpers that were written to build their own
client. Threading a credential through every helper would rewrite most of that
code, so the token is bound for the duration of one tool call instead and the
helpers ask for it with ``current_user_credentials()``.

The binding is a ``ContextVar`` set and reset inside the wrapper's own frame, so
it is visible to everything the tool calls synchronously or awaits, and never
outlives the call. Work handed to a thread pool does not inherit it; such work
must receive the credential explicitly.
"""

from __future__ import annotations

import functools
import inspect
from collections.abc import Callable, Mapping
from contextvars import ContextVar, Token
from typing import Any

from google.adk.tools.tool_context import ToolContext
from google.oauth2.credentials import Credentials

from .delegated import read_session_token

TOOL_CONTEXT_PARAMETER = "tool_context"

# Agent Engine pickles the agent at deploy time. A ContextVar cannot be pickled, so
# the wrapper below must never reference it directly: a closure is pickled by
# value, with every global it names. It calls _bind and _unbind instead, which,
# being module-level functions, are pickled by reference.
_CURRENT: ContextVar[Credentials | None] = ContextVar("gemini_user_credentials", default=None)


class MissingUserAuthorization(RuntimeError):
    """The session carries no token for the agent's authorization."""


def user_credentials(state: Mapping[str, Any], authorization_id: str) -> Credentials:
    """Build Google credentials from the token Gemini Enterprise put in session state."""
    token = read_session_token(state, authorization_id)
    if not token:
        raise MissingUserAuthorization(
            f"No delegated token for authorization '{authorization_id}'. Confirm the "
            "authorization is attached to the agent in Gemini Enterprise and that the "
            "user has completed consent."
        )
    return Credentials(token)


def current_user_credentials() -> Credentials:
    """Return the credentials bound for the tool call in progress."""
    credentials = _CURRENT.get()
    if credentials is None:
        raise MissingUserAuthorization(
            "No user credentials are bound. Wrap the tool with with_user_credentials()."
        )
    return credentials


def _bind(credentials: Credentials) -> Token[Credentials | None]:
    return _CURRENT.set(credentials)


def _unbind(binding: Token[Credentials | None]) -> None:
    _CURRENT.reset(binding)


def _signature_with_tool_context(func: Callable[..., Any]) -> inspect.Signature:
    """The tool's own signature, plus ``tool_context`` if it does not declare it.

    ADK builds the model-facing declaration from the signature and passes
    ``tool_context`` only to functions that name it, so the wrapper must name
    it without adding anything the model is asked to supply.
    """
    signature = inspect.signature(func)
    if TOOL_CONTEXT_PARAMETER in signature.parameters:
        return signature
    parameters = list(signature.parameters.values())
    context = inspect.Parameter(
        TOOL_CONTEXT_PARAMETER, inspect.Parameter.KEYWORD_ONLY, annotation=ToolContext
    )
    position = next(
        (i for i, p in enumerate(parameters) if p.kind is inspect.Parameter.VAR_KEYWORD),
        len(parameters),
    )
    parameters.insert(position, context)
    return signature.replace(parameters=parameters)


def with_user_credentials(
    authorization_id: str,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Bind the signed-in user's credentials while the decorated tool runs.

    The tool keeps its name, docstring and parameters, so ADK describes it to
    the model exactly as before. A missing authorization is returned to the
    model as an error rather than raised, so the agent can tell the user to
    authorize instead of the request failing.
    """

    def decorate(func: Callable[..., Any]) -> Callable[..., Any]:
        wants_context = TOOL_CONTEXT_PARAMETER in inspect.signature(func).parameters

        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            tool_context: ToolContext = kwargs[TOOL_CONTEXT_PARAMETER]
            if not wants_context:
                kwargs.pop(TOOL_CONTEXT_PARAMETER)
            try:
                credentials = user_credentials(tool_context.state, authorization_id)
            except MissingUserAuthorization as exc:
                return {"status": "error", "message": str(exc)}
            binding = _bind(credentials)
            try:
                result = func(*args, **kwargs)
                if inspect.isawaitable(result):
                    result = await result
                return result
            finally:
                _unbind(binding)

        # inspect.signature follows __wrapped__ to the original, which may not
        # name tool_context; an explicit __signature__ takes precedence.
        wrapper.__signature__ = _signature_with_tool_context(func)  # type: ignore[attr-defined]
        return wrapper

    return decorate
