"""LangChain Azure OpenAI adapter for strict Phase 4 structured output."""

from collections.abc import Awaitable, Callable
from time import perf_counter
from typing import Protocol, cast
from urllib.parse import urlsplit

from azure.identity.aio import DefaultAzureCredential
from langchain_core.callbacks import get_usage_metadata_callback
from langchain_openai import AzureChatOpenAI, ChatOpenAI

from recruitment_agent.application.errors import ExtractionInvocationError
from recruitment_agent.config.settings import AzureOpenAISettings
from recruitment_agent.extraction.models import (
    ExtractionUsage,
    RecruitmentExtraction,
    RecruitmentExtractionRequest,
)
from recruitment_agent.extraction.prompt import RECRUITMENT_EXTRACTION_PROMPT_V2
from recruitment_agent.extraction.usage import record_extraction_usage

_AZURE_OPENAI_CLASSIC_SCOPE = "https://cognitiveservices.azure.com/.default"
_FOUNDRY_SCOPE = "https://ai.azure.com/.default"
_FOUNDRY_V1_PATH = "/openai/v1"


def _reject_synchronous_model_call() -> str:
    """Satisfy client construction while enforcing the async-only application port."""
    raise RuntimeError("synchronous model invocation is not supported")


class StructuredExtractionRunnable(Protocol):
    """Small async boundary implemented by a composed LangChain runnable."""

    def ainvoke(self, value: dict[str, object]) -> Awaitable[object]: ...


def sum_usage_tokens(metadata: object, field: str) -> int | None:
    """Sum a LangChain usage field without assuming provider key shapes."""
    if not isinstance(metadata, dict) or not metadata:
        return None
    total = 0
    saw_value = False
    for entry in metadata.values():
        if not isinstance(entry, dict):
            continue
        value = entry.get(field)
        if isinstance(value, int) and value >= 0:
            total += value
            saw_value = True
    return total if saw_value else None


def _uses_foundry_v1(endpoint: str) -> bool:
    """Return whether an endpoint targets the stable Foundry OpenAI v1 route."""
    return urlsplit(endpoint).path.rstrip("/").lower().endswith(_FOUNDRY_V1_PATH)


def _create_langchain_chat_model(
    *,
    endpoint: str,
    deployment: str,
    api_version: str,
    token_provider: Callable[[], Awaitable[str]],
    timeout: float,
    max_retries: int,
) -> ChatOpenAI | AzureChatOpenAI:
    """Create the correct LangChain client without embedding provider configuration."""
    normalized_endpoint = endpoint.rstrip("/")
    common_config: dict[str, object] = {
        "temperature": 0,
        "timeout": timeout,
        "max_retries": max_retries,
    }
    if _uses_foundry_v1(normalized_endpoint):
        return ChatOpenAI.model_validate(
            {
                **common_config,
                "base_url": f"{normalized_endpoint}/",
                "model": deployment,
                "api_key": token_provider,
            }
        )
    return AzureChatOpenAI.model_validate(
        {
            **common_config,
            "azure_endpoint": normalized_endpoint,
            "azure_deployment": deployment,
            "api_version": api_version,
            "azure_ad_token_provider": _reject_synchronous_model_call,
            "azure_ad_async_token_provider": token_provider,
        }
    )


class LangChainRecruitmentExtractionModel:
    """Map sanitized requests to strict Pydantic output through LangChain."""

    def __init__(
        self,
        *,
        runnable: StructuredExtractionRunnable,
        credential: DefaultAzureCredential | None = None,
    ) -> None:
        self._runnable = runnable
        self._credential = credential

    async def extract(self, request: RecruitmentExtractionRequest) -> RecruitmentExtraction:
        values: dict[str, object] = {
            "prompt_version": request.prompt_version,
            "received_at": request.received_at.isoformat(),
            "allowed_link_refs": list(request.allowed_link_refs),
            "sanitized_text": request.sanitized_text,
        }
        record_extraction_usage(None)
        started = perf_counter()
        try:
            with get_usage_metadata_callback() as usage_callback:
                result = await self._runnable.ainvoke(values)
            extraction = (
                result
                if isinstance(result, RecruitmentExtraction)
                else RecruitmentExtraction.model_validate(result)
            )
        except Exception:
            raise ExtractionInvocationError("structured extraction failed") from None
        latency_ms = int((perf_counter() - started) * 1000)
        record_extraction_usage(
            ExtractionUsage(
                prompt_tokens=sum_usage_tokens(usage_callback.usage_metadata, "input_tokens"),
                completion_tokens=sum_usage_tokens(
                    usage_callback.usage_metadata,
                    "output_tokens",
                ),
                latency_ms=latency_ms,
            )
        )
        return extraction

    async def aclose(self) -> None:
        """Release the Azure Identity transport when this adapter owns it."""
        if self._credential is not None:
            await self._credential.close()


def create_azure_recruitment_extraction_model(
    settings: AzureOpenAISettings,
    *,
    token_provider: Callable[[], Awaitable[str]] | None = None,
) -> LangChainRecruitmentExtractionModel:
    """Compose the versioned prompt and Azure model at the infrastructure boundary."""
    if not settings.llm_enabled:
        raise ValueError("LLM extraction is disabled")
    endpoint = settings.azure_openai_endpoint
    deployment = settings.azure_openai_deployment
    if endpoint is None or deployment is None:
        raise ValueError("Azure OpenAI endpoint and deployment are required")

    credential: DefaultAzureCredential | None = None
    if token_provider is None:
        credential = DefaultAzureCredential()
        token_scope = (
            _FOUNDRY_SCOPE if _uses_foundry_v1(str(endpoint)) else _AZURE_OPENAI_CLASSIC_SCOPE
        )

        async def managed_identity_token_provider() -> str:
            token = await credential.get_token(token_scope)
            return token.token

        token_provider = managed_identity_token_provider

    chat_model = _create_langchain_chat_model(
        endpoint=str(endpoint),
        deployment=deployment,
        api_version=settings.azure_openai_api_version,
        token_provider=token_provider,
        timeout=settings.azure_openai_request_timeout_seconds,
        max_retries=settings.azure_openai_max_retry_attempts - 1,
    )
    structured_model = chat_model.with_structured_output(
        RecruitmentExtraction,
        method="json_schema",
        strict=True,
        include_raw=False,
    )
    runnable = cast(
        StructuredExtractionRunnable,
        RECRUITMENT_EXTRACTION_PROMPT_V2 | structured_model,
    )
    return LangChainRecruitmentExtractionModel(
        runnable=runnable,
        credential=credential,
    )
