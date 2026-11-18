FROM python:3.13-slim

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
COPY BridgeCLI/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt 'cryptography>=48,<51'

COPY Agent/ /app/Agent/
COPY BridgeCLI/ /app/BridgeCLI/
COPY deploy/run.py /app/run.py

EXPOSE 8000
CMD ["python", "/app/run.py"]
