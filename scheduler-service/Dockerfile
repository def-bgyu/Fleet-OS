FROM python:3.11-slim
WORKDIR /app
COPY . .
RUN pip install --no-cache-dir fastapi uvicorn redis requests prometheus-client slowapi
CMD ["python", "scheduler.py"]