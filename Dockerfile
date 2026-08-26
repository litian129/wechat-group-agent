# 企业微信群聊智能体 - Docker 镜像
FROM python:3.12-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    TZ=Asia/Shanghai

# 先装依赖, 利用构建缓存
COPY requirements.txt .
RUN pip install -r requirements.txt

# 拷贝代码与默认配置 (config/input/output/state 建议用卷挂载覆盖)
COPY src ./src
COPY config ./config

# 运行期目录: 输入监听 / 结果落盘 / 监听器状态 / 日志
RUN mkdir -p input output state logs

# 容器内监听 0.0.0.0, 供宿主机端口映射
ENV AGENT_API_HOST=0.0.0.0 \
    AGENT_API_PORT=8000 \
    AGENT_LOG_LEVEL=INFO

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import httpx; httpx.get('http://127.0.0.1:8000/health', timeout=3)" || exit 1

CMD ["python", "src/server.py"]
