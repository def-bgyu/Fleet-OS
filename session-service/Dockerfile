FROM python:3.11-slim
WORKDIR /app
COPY . .
RUN pip install --no-cache-dir fastapi uvicorn redis requests slowapi
CMD ["python", "sessions.py"]
