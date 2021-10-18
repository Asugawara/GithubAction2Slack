FROM python:3.9.5-alpine3.14

COPY main.py /app/

ENTRYPOINT ["python", "/app/main.py"]
