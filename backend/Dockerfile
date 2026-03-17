FROM python:3.11-slim

# 安装系统依赖（Playwright 需要的浏览器运行时依赖）
# 同时安装 tzdata，并把容器系统时区固定为 Asia/Shanghai。
# 当前后端日志和 Uvicorn 访问日志都依赖容器本地时区格式化时间；
# 如果这里不统一，docker logs 会与前端东八区展示相差 8 小时，排障时很容易误判时间线。
ENV TZ=Asia/Shanghai
RUN apt-get update && apt-get install -y --no-install-recommends \
    tzdata \
    libnss3 libnspr4 libatk1.0-0 libatk-bridge2.0-0 \
    libcups2 libdrm2 libxkbcommon0 libxcomposite1 \
    libxdamage1 libxfixes3 libxrandr2 libgbm1 libpango-1.0-0 \
    libcairo2 libasound2 libatspi2.0-0 libwayland-client0 \
    && ln -snf /usr/share/zoneinfo/$TZ /etc/localtime \
    && echo $TZ > /etc/timezone \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 安装 Python 依赖
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 安装 Playwright Chromium 浏览器
RUN playwright install chromium

# 复制应用代码
COPY . .

# 创建数据目录
RUN mkdir -p /app/data

EXPOSE 8000

# 使用 Uvicorn 启动 FastAPI
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
