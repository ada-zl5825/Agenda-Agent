"""LangChain Azure OpenAI adapter for strict Phase 4 structured output."""

from collections.abc import Awaitable, Callable
from typing import Protocol, cast

from azure.identity.aio import DefaultAzureCredential
from langchain_openai import AzureChatOpenAI

from recruitment_agent.application.errors import ExtractionInvocationError
from recruitment_agent.config.settings import AzureOpenAISettings
from recruitment_agent.extraction.models import (
    RecruitmentExtraction,
    RecruitmentExtractionRequest,
)
from recruitment_agent.extraction.prompt import RECRUITMENT_EXTRACTION_PROMPT_V1

_AZURE_OPENAI_SCOPE = "https://cognitiveservices.azure.com/.default"


def _reject_synchronous_model_call() -> str:
    """Satisfy client construction while enforcing the async-only application port."""
    raise RuntimeError("synchronous model invocation is not supported")


class StructuredExtractionRunnable(Protocol):
    """Small async boundary implemented by a composed LangChain runnable."""

    def ainvoke(self, value: dict[str, object]) -> Awaitable[object]: ...


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
        try:
            result = await self._runnable.ainvoke(values)
            if isinstance(result, RecruitmentExtraction):
                return result
            return RecruitmentExtraction.model_validate(result)
        except Exception:
            raise ExtractionInvocationError("structured extraction failed") from None

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

        async def managed_identity_token_provider() -> str:
            token = await credential.get_token(_AZURE_OPENAI_SCOPE)
            return token.token

        token_provider = managed_identity_token_provider

    chat_model = AzureChatOpenAI.model_validate(
        {
            "azure_endpoint": str(endpoint).rstrip("/"),
            "azure_deployment": deployment,
            "api_version": settings.azure_openai_api_version,
            "azure_ad_token_provider": _reject_synchronous_model_call,
            "azure_ad_async_token_provider": token_provider,
            "temperature": 0,
            "timeout": settings.azure_openai_request_timeout_seconds,
            "max_retries": settings.azure_openai_max_retry_attempts - 1,
        }
    )
    structured_model = chat_model.with_structured_output(
        RecruitmentExtraction,
        method="json_schema",
        strict=True,
        include_raw=False,
    )
    runnable = cast(
        StructuredExtractionRunnable,
        RECRUITMENT_EXTRACTION_PROMPT_V1 | structured_model,
    )
    return LangChainRecruitmentExtractionModel(
        runnable=runnable,
        credential=credential,
    )
