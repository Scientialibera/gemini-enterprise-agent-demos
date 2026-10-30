"""Talk to a deployed runtime the way Gemini Enterprise does: the user's token in session state."""

from __future__ import annotations

import json
from dataclasses import dataclass, field

import google.auth
import google.auth.transport.requests

USER_ID = "deployment-verify"


@dataclass
class Turn:
    text: str = ""
    tool_calls: list[tuple[str, dict]] = field(default_factory=list)
    tool_results: list[tuple[str, object]] = field(default_factory=list)

    def result_of(self, tool: str) -> object | None:
        """The last result of a tool, decoded when the tool returned JSON text."""
        for name, response in reversed(self.tool_results):
            if name != tool:
                continue
            if isinstance(response, dict) and set(response) == {"result"}:
                response = response["result"]
            if isinstance(response, str):
                try:
                    return json.loads(response)
                except json.JSONDecodeError:
                    return response
            return response
        return None


def user_token() -> str:
    credentials, _ = google.auth.default()
    credentials.refresh(google.auth.transport.requests.Request())
    return credentials.token


class Conversation:
    """One session on a deployed runtime; the token is never printed."""

    def __init__(self, resource: str, authorization_id: str):
        import vertexai

        project, location = resource.split("/")[1], resource.split("/")[3]
        client = vertexai.Client(project=project, location=location)
        self._engine = client.agent_engines.get(name=resource)
        session = self._engine.create_session(
            user_id=USER_ID, state={authorization_id: user_token()}
        )
        self._session_id = session["id"] if isinstance(session, dict) else session.id

    def send(self, message: str) -> Turn:
        turn = Turn()
        texts = []
        for event in self._engine.stream_query(
            user_id=USER_ID, session_id=self._session_id, message=message
        ):
            for part in (event.get("content") or {}).get("parts", []) or []:
                if part.get("function_call"):
                    call = part["function_call"]
                    turn.tool_calls.append((call.get("name"), call.get("args") or {}))
                if part.get("function_response"):
                    response = part["function_response"]
                    turn.tool_results.append((response.get("name"), response.get("response")))
                if part.get("text") and not part.get("thought"):
                    texts.append(part["text"])
        turn.text = "\n".join(texts)
        return turn

    def state(self) -> dict:
        """The session's state as the runtime last saved it (each stage's output key)."""
        session = self._engine.get_session(user_id=USER_ID, session_id=self._session_id)
        if isinstance(session, dict):
            state = session.get("state")
        else:
            state = getattr(session, "state", None)
        return dict(state or {})
