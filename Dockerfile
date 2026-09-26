# Containerizes the webapp (FastAPI WebSocket proxy + browser UI).
# The native voice pipeline (ai_companion/main.py) needs direct host
# microphone/speaker access and Raspberry Pi GPIO in some modes, so it's
# meant to run natively rather than in this container — see README.
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8000

WORKDIR /app
COPY webapp/requirements.txt webapp/requirements.txt
RUN pip install --no-cache-dir -r webapp/requirements.txt

COPY . .

# Run unprivileged; the app writes session state under /tmp only.
RUN useradd --system --uid 10001 maya && chown -R maya /app
USER maya

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
  CMD python -c "import urllib.request,os; urllib.request.urlopen(f'http://127.0.0.1:{os.environ[\"PORT\"]}/health', timeout=4)"
# PORT is set by most container hosts; --proxy-headers trusts X-Forwarded-*
CMD ["sh", "-c", "uvicorn webapp.server:app --host 0.0.0.0 --port ${PORT} --proxy-headers --forwarded-allow-ips='*'"]
