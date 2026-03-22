FROM python:3.11-slim
WORKDIR /app
COPY . .
RUN pip install fastapi uvicorn redis celery requests prometheus-client
CMD ["python", "scheduler.py"]