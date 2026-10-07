FROM python:3.13-slim

ENV ROOT_DIR=/app
WORKDIR $ROOT_DIR
COPY requirements.txt $ROOT_DIR

RUN pip install -r requirements.txt

COPY . $ROOT_DIR

CMD uvicorn main:app --port 8000 --host 0.0.0.0