FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ /app/app/

EXPOSE 9991
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "9991", "--workers", "1"]
