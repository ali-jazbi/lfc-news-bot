FROM python:3.12-slim

WORKDIR /app
# ffmpeg برای خط لوله ویدیو (مرحله ۸) — دانلود/تبدیل/thumbnail
RUN apt-get update && apt-get install -y --no-install-recommends gcc libxml2-dev libxslt1-dev ffmpeg \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
RUN mkdir -p /app/data

CMD ["python", "-u", "main.py"]
