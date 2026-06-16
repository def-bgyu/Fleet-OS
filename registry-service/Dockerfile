FROM python:3.11-slim
WORKDIR /app
COPY . .
RUN pip install --no-cache-dir fastapi uvicorn redis prometheus-client requests slowapi
CMD ["python", "registry.py"]