FROM python:3.11-slim

WORKDIR /app

COPY proxy-server/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY proxy-server/main.py .

EXPOSE 8080
CMD ["python", "main.py"]
