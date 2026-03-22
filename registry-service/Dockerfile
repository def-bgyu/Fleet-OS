FROM python:3.11-slim
WORKDIR /app
COPY . .
RUN pip install fastapi uvicorn redis prometheus-client requests
CMD ["python", "registry.py"]