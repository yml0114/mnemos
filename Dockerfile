FROM python:3.11-slim

LABEL org.opencontainers.image.title="Mnemos"
LABEL org.opencontainers.image.description="独立记忆世界 — 可移植的多层AI记忆系统"
LABEL org.opencontainers.image.url="https://github.com/yml0114/mnemos"

WORKDIR /app

# 安装依赖
COPY pyproject.toml .
COPY mnemos/ mnemos/
RUN pip install --no-cache-dir -e .

# 暴露端口
EXPOSE 8765

# 数据卷
VOLUME /data

ENV MNEMOS_DB_PATH=/data/memory.db

# 默认启动可视化仪表盘
CMD ["python", "-m", "mnemos.viz.dashboard", "--db", "/data/memory.db", "--port", "8765", "--host", "0.0.0.0"]
