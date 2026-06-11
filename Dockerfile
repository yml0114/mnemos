# Mnemos Docker Image — 一体化部署（API + Web Dashboard）
# Build: docker build -t yml0114/mnemos:latest .
# Run: docker run -p 9730:9730 -v mnemos_data:/root/.hermes yml0114/mnemos:latest

FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# 安装 uv（加速 pip）
RUN pip install --upgrade pip && \
    pip install uv

# 复制项目文件
COPY pyproject.toml .
COPY mnemos ./mnemos
COPY README.md .

# 安装依赖及包（可编辑模式）
RUN uv pip install -e .

EXPOSE 9730

# 启动统一服务器（API + Dashboard）
CMD ["uvicorn", "mnemos.api.server_with_dashboard:app", "--host", "0.0.0.0", "--port", "9730"]