FROM python:3.12-slim

WORKDIR /app

COPY harness/requirements.txt ./harness/requirements.txt
RUN pip install --no-cache-dir -r harness/requirements.txt

COPY harness ./harness
COPY scripts ./scripts
COPY skills ./skills

ENV PYTHONUNBUFFERED=1
VOLUME ["/data"]

CMD ["python", "-m", "harness.src.main"]
