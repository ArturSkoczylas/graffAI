FROM python:3.12-slim

WORKDIR /app

COPY harness/requirements.txt ./harness/requirements.txt
RUN pip install --no-cache-dir -r harness/requirements.txt

COPY harness ./harness
COPY scripts ./scripts
COPY agents ./agents
COPY skills ./skills

ENV PYTHONUNBUFFERED=1
EXPOSE 8765

CMD ["python", "-m", "harness.src.main"]
