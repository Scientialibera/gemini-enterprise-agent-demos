"""Explicit model and application construction shared by deployable entry points."""

from __future__ import annotations

import logging
from collections.abc import AsyncGenerator

import vertexai
from google import genai
from google.adk.agents import BaseAgent
from google.adk.models import Gemini, LlmRequest, LlmResponse
from google.genai import errors as genai_errors
from google.genai import types
from vertexai.agent_engines import AdkApp

from ..config.bootstrap import BootstrapSettings
from ..limits import RuntimeLimitsPlugin

LOGGER = logging.getLogger(__name__)

# Model calls back off long enough to outlast a per-minute quota window: about a
# minute in total across six attempts. The library default gives up within seconds,
# so a burst (a long workflow, several users at once) failed a whole run on a 429.
MODEL_RETRY = types.HttpRetryOptions(
    attempts=6,
    initial_delay=2.0,
    max_delay=60.0,
    exp_base=2.0,
    jitter=1.0,
    http_status_codes=[408, 429, 500, 502, 503, 504],
)
# Longest a single model call may take. The longest healthy call, the Growth
# diagnosis, writes a long report in under two minutes.
MODEL_TIMEOUT_MS = 180_000


class _ReauthenticatingGemini(Gemini):
    """Gemini that rebuilds its client and retries once when a call comes back 401.

    A long-lived runtime worker can hold an access token that the model endpoint
    no longer accepts while the credentials still report it as valid, so they are
    never refreshed and every later call fails. A fresh client loads new
    credentials. Only a call that has yielded nothing yet is retried.
    """

    async def generate_content_async(
        self, llm_request: LlmRequest, stream: bool = False
    ) -> AsyncGenerator[LlmResponse, None]:
        # Bound every call: an endpoint that accepts a request and never answers
        # otherwise hangs the run forever, since no error ever reaches the retry.
        # The client's retry policy treats the timeout as transient and retries.
        if llm_request.config.http_options is None:
            llm_request.config.http_options = types.HttpOptions(timeout=MODEL_TIMEOUT_MS)
        yielded = False
        try:
            async for response in super().generate_content_async(llm_request, stream):
                yielded = True
                yield response
            return
        except genai_errors.ClientError as exc:
            if exc.code != 401 or yielded:
                raise
            LOGGER.warning("Model call was unauthenticated; retrying with fresh credentials.")
        self.__dict__.pop("api_client", None)
        async for response in super().generate_content_async(llm_request, stream):
            yield response


def create_model(settings: BootstrapSettings) -> Gemini:
    return _ReauthenticatingGemini(
        model=settings.bootstrap_model,
        client_kwargs={"location": settings.model_location},
        retry_options=MODEL_RETRY,
    )


def create_genai_client(settings: BootstrapSettings) -> genai.Client:
    """A Vertex AI client for model calls a tool makes itself, outside ADK.

    Uses the runtime's own identity and the same model location as the agent,
    so a tool never needs an API key. Read the model name from the live
    configuration at call time rather than fixing it here.
    """
    return genai.Client(
        vertexai=True,
        project=settings.project_id,
        location=settings.model_location,
        http_options=types.HttpOptions(retry_options=MODEL_RETRY, timeout=MODEL_TIMEOUT_MS),
    )


def create_app(agent: BaseAgent, settings: BootstrapSettings) -> AdkApp:
    """Set the known project explicitly, so wrapper construction does not discover ADC."""
    vertexai.init(project=settings.project_id, location=settings.location)
    return AdkApp(agent=agent, enable_tracing=True, plugins=[RuntimeLimitsPlugin()])
