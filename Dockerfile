# Small, reliable base with ffmpeg installed
FROM python:3.12-slim

# Install ffmpeg for pydub
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py .

# For Coolify, exposing a web service on 8000 is perfect
EXPOSE 8000
CMD ["uvicorn", "app:app", "--host=0.0.0.0", "--port=8000"]
