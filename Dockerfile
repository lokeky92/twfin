FROM python:3.11-slim

WORKDIR /app
COPY . /app

ENV PORT=7860
ENV HOST=0.0.0.0

RUN python backend/run_pipeline.py && python backend/export_standalone.py

EXPOSE 7860

CMD ["python", "backend/server.py"]
