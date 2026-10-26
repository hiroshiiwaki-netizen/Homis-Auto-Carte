# FAX カルテの受け口（横付けで受け取るだけ）v0.1.0
# 仕様: docs/FAXカルテ_検討/SPEC_受け口_横付け_v0.md
# 標準部品だけなので pip install は無い
FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1
COPY server.py /app/server.py
CMD ["python", "-u", "/app/server.py"]
