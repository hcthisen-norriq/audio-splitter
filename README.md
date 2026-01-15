# Audio Splitter API

A FastAPI service that splits audio files into chunks with optional overlap. It accepts audio via file upload or URL download, processes it using pydub/ffmpeg, and returns either base64-encoded chunks or signed temporary URLs.

## Installation

### Using Docker

```bash
docker build -t audio-splitter .
docker run -p 8000:8000 audio-splitter
```

### Local Setup

Requires Python 3.12+ and ffmpeg installed on your system.

```bash
pip install -r requirements.txt
python app.py
```

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `STORAGE_DIR` | `/tmp/splitter` | Temporary file storage location |
| `TTL_MIN` | `30` | Minutes until signed URLs expire and files are deleted |
| `MAX_DOWNLOAD_MB` | `200` | Maximum size for URL downloads in MB |
| `SIGNING_SECRET` | Auto-generated | HMAC secret for URL signing |

## API Endpoints

### Health Check

```
GET /health
```

Returns `{"status": "ok"}` when the service is running.

### Split Audio

```
POST /split
```

Splits an audio file into chunks with optional overlap.

#### Request Parameters

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `file` | File | No* | - | Audio file upload (multipart/form-data) |
| `url` | String | No* | - | URL to download audio from |
| `chunk_ms` | Integer | No | `600000` (10 min) | Chunk size in milliseconds |
| `overlap_ms` | Integer | No | `0` | Overlap between chunks in milliseconds |
| `export_format` | String | No | `mp3` | Output format: `mp3`, `wav`, `flac`, or `ogg` |
| `return_mode` | String | No | `urls` | Return mode: `urls` or `base64` |

*Either `file` or `url` must be provided.

#### Example: Upload a File

```bash
curl -X POST "http://localhost:8000/split" \
  -F "file=@audio.mp3" \
  -F "chunk_ms=60000" \
  -F "overlap_ms=5000" \
  -F "export_format=mp3" \
  -F "return_mode=urls"
```

#### Example: Download from URL

```bash
curl -X POST "http://localhost:8000/split" \
  -F "url=https://example.com/audio.mp3" \
  -F "chunk_ms=300000" \
  -F "export_format=wav"
```

#### Example: Get Base64 Response

```bash
curl -X POST "http://localhost:8000/split" \
  -F "file=@audio.mp3" \
  -F "chunk_ms=60000" \
  -F "return_mode=base64"
```

#### Response (URLs mode)

```json
{
  "source": "upload",
  "return": "urls",
  "expires_in_minutes": 30,
  "chunks": [
    {
      "index": 0,
      "start_ms": 0,
      "end_ms": 60000,
      "mime": "audio/mpeg",
      "url": "http://localhost:8000/get/abc123/0.mp3?exp=1234567890&sig=...",
      "expires_at": "2024-01-01T12:30:00+00:00"
    }
  ],
  "total_duration_ms": 180000,
  "chunk_ms": 60000,
  "overlap_ms": 0,
  "format": "mp3",
  "job_id": "abc123"
}
```

#### Response (Base64 mode)

```json
{
  "source": "upload",
  "return": "base64",
  "expires_in_minutes": null,
  "chunks": [
    {
      "index": 0,
      "start_ms": 0,
      "end_ms": 60000,
      "mime": "audio/mpeg",
      "data_base64": "..."
    }
  ],
  "total_duration_ms": 180000,
  "chunk_ms": 60000,
  "overlap_ms": 0,
  "format": "mp3",
  "job_id": null
}
```

### Get Chunk

```
GET /get/{job_id}/{filename}?exp={expiry}&sig={signature}
```

Retrieves a specific audio chunk via a signed URL. This endpoint is used by the URLs returned from the `/split` endpoint.
