# syntax=docker/dockerfile:1
FROM python:3.14-slim
ENV PYTHONPATH=/app/src \
    PYTHONDONTWRITEBYTECODE=1
WORKDIR /app
RUN pip install --no-cache-dir \
    "mistralai-workflows[mistralai]>=3.17.1" \
    "pydantic>=2.14.1" \
    "pytest>=8" \
    "pytest-asyncio>=0.25.3"
COPY pyproject.toml ./
COPY src ./src
COPY tests ./tests
CMD ["python", "-m", "worker.entrypoint"]
