FROM python:3.12.13-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

RUN groupadd --system agenda \
    && useradd --system --gid agenda --home-dir /app --no-create-home agenda

COPY pyproject.toml requirements.txt README.md alembic.ini ./
COPY src ./src
COPY alembic ./alembic

RUN python -m pip install --no-cache-dir --requirement requirements.txt

USER agenda

ENTRYPOINT ["python", "-m", "recruitment_agent.jobs.database_maintenance"]
CMD ["check"]
