FROM python:3.12-slim

WORKDIR /app

# 安装依赖
COPY pyproject.toml .
RUN pip install --no-cache-dir .

# 复制应用代码
COPY app/ ./app/

# 复制 references（价格基线 + 产品目录）
COPY references/ ./references/

# 创建数据目录
RUN mkdir -p data/files data/audit data/fonts

# 复制 logos 图片
COPY data/logos/ ./data/logos/

# 暴露端口
EXPOSE 8000

# 启动服务
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
