# Checker, benchmark and tests run offline on the committed fact table.
#   docker build -t finllm-qa .
#   docker run --rm finllm-qa                       # synthetic benchmark
#   docker run --rm finllm-qa check Apple-FY2025 "Revenue rose 16% to $416.2 billion."
FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY finllm_qa finllm_qa
COPY data/facts.csv data/facts.csv
COPY scripts scripts
COPY tests tests
RUN pip install --no-cache-dir -e ".[dev]"
ENTRYPOINT ["python", "-m", "finllm_qa"]
CMD ["benchmark"]
