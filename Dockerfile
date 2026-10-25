# Quantitative-selection: stdlib-first runtime; dev deps carry pytest and
# the optional parquet/duckdb readers used by tests.
FROM python:3.11-slim

WORKDIR /app
COPY requirements.txt requirements-dev.txt ./
RUN pip install --no-cache-dir -r requirements.txt -r requirements-dev.txt

COPY src ./src
COPY configs ./configs
COPY tests ./tests
ENV PYTHONPATH=/app/src

# Paper trading only: every entry point fails closed without approvals,
# and prod defaults to dry-run (DETAILED_DESIGN section 9).
CMD ["python", "-m", "quant_agent.cli.paper", "--approvals", "state/paper-approvals.json"]
