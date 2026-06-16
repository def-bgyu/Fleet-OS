FROM python:3.11-slim

WORKDIR /app

RUN pip install --no-cache-dir requests prometheus-client transformers psutil
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu

# Pre-download model at build time so containers start instantly
RUN python -c "from transformers import pipeline; pipeline('sentiment-analysis', model='distilbert-base-uncased-finetuned-sst-2-english', device=-1)"

COPY . .

CMD ["python", "agent.py"]
