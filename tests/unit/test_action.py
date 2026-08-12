from datetime import UTC, datetime
from uuid import uuid4

import pytest

from recruitment_agent.domain.action import ActionItem
from recruitment_agent.domain.enums import ActionStatus, ActionType
from recruitment_agent.domain.errors import DomainValidationError


def test_action_item_requires_a_title() -> None:
    now = datetime(2026, 8, 12, 12, tzinfo=UTC)

    with pytest.raises(DomainValidationError, match="title"):
        ActionItem(
            id=uuid4(),
            application_id=uuid4(),
            source_email_id=uuid4(),
            type=ActionType.ASSESSMENT,
            title="  ",
            status=ActionStatus.OPEN,
            created_at=now,
            updated_at=now,
        )
