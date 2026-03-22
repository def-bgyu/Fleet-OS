FROM python:3.11-slim
WORKDIR /app
COPY . .
RUN pip install requests numpy prometheus-client
CMD ["python", "agent.py"]