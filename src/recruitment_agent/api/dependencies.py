"""Lazy Phase 1 composition; importing the API never opens external connections."""

from functools import lru_cache

from recruitment_agent.application.clock import SystemClock
from recruitment_agent.application.reviews import ReviewService
from recruitment_agent.config import get_microsoft_settings, get_settings
from recruitment_agent.microsoft.auth import MicrosoftAuthorizationService
from recruitment_agent.microsoft.crypto import AesGcmCipher
from recruitment_agent.persistence.microsoft_auth import SqlAlchemyMicrosoftAuthStore
from recruitment_agent.persistence.reviews import SqlAlchemyReviewStore
from recruitment_agent.persistence.session import create_database_engine, create_session_factory
from recruitment_agent.web.security import WebSessionManager


@lru_cache(maxsize=1)
def get_authorization_service() -> MicrosoftAuthorizationService:
    """Compose the OAuth application service on first authenticated request."""
    settings = get_microsoft_settings()
    database_settings = get_settings()
    engine = create_database_engine(database_settings.database_url)
    session_factory = create_session_factory(engine)
    return MicrosoftAuthorizationService(
        settings=settings,
        store=SqlAlchemyMicrosoftAuthStore(session_factory),
        cipher=AesGcmCipher(
            key=settings.token_cache_key_bytes,
            key_version=settings.token_cache_encryption_key_version,
        ),
        clock=SystemClock(),
    )


@lru_cache(maxsize=1)
def get_web_session_manager() -> WebSessionManager:
    settings = get_microsoft_settings()
    return WebSessionManager(
        key=settings.web_session_key_bytes,
        clock=SystemClock(),
        ttl_seconds=settings.web_session_ttl_seconds,
    )


@lru_cache(maxsize=1)
def get_review_service() -> ReviewService:
    settings = get_settings()
    engine = create_database_engine(settings.database_url)
    session_factory = create_session_factory(engine)
    from recruitment_agent.jobs.mail_processing import resume_mail_processing_job

    return ReviewService(
        store=SqlAlchemyReviewStore(session_factory),
        resumer=resume_mail_processing_job,
    )
