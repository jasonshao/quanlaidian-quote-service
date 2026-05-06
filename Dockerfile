FROM jfrog.wosai-inc.com/docker-local-mirror/ft-mirror/python:3.12-slim

WORKDIR /app

COPY pyproject.toml .
COPY app/ ./app/
COPY references/ ./references/
COPY data/logos/ ./data/logos/

RUN mkdir -p data/files data/audit data/fonts \
 && pip install --no-cache-dir .
 
EXPOSE 8000

# 启动服务
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
