FROM python:3.11-slim

WORKDIR /app

COPY pyproject.toml .
RUN pip install --no-cache-dir -e ".[dev]"

COPY . .

RUN mkdir -p data/drafts data/master_cv data/templates

CMD ["python", "-m", "jobpipe.scheduler"]
