FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && mkdir /data && chown 65534:65534 /data
COPY pipeline pipeline
COPY examples examples
COPY tests tests
USER 65534:65534
ENTRYPOINT ["python", "-m", "pipeline.main"]
CMD ["demo"]
