# Pure Python 3.11 Standard Library (sqlite3, http.server, urllib, json)
# No third-party pip packages required.
FROM python:3.11-slim

WORKDIR /app
COPY . /app

ENV PORT=7860
ENV HOST=0.0.0.0
# 公開部署時請設定 TWFIN_ADMIN_TOKEN，否則寫入型 API 只接受容器內 127.0.0.1 的請求
# ENV TWFIN_ADMIN_TOKEN=...

EXPOSE 7860

# 資料擷取改在「容器啟動時」執行，而不是 docker build 時：
# 映像檔本身可重現、可快取；外部 API 暫時失敗也不會讓建置失敗 (伺服器會以種子資料啟動)。
CMD ["sh", "-c", "python backend/run_pipeline.py --all || echo 'Pipeline failed; starting server with existing/seed data'; exec python backend/server.py"]
