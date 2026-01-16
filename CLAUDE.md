# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Audio Splitter API is a FastAPI service that splits audio files into chunks with optional overlap. It accepts audio via file upload or URL download, processes it using pydub/ffmpeg, and returns either base64-encoded chunks or signed temporary URLs.

## Architecture

**Single-file application** ([app.py](app.py)): All logic in one FastAPI module with these key components:

- **POST /split**: Main endpoint that accepts audio (file upload or URL), splits it into chunks based on `chunk_ms` and `overlap_ms` parameters, and returns either base64 data or signed URLs
- **GET /get/{job_id}/{filename}**: Serves audio chunks via signed URLs with expiry verification
- **Background janitor**: Async task (`_janitor`) that runs every 5 minutes to delete expired job directories based on TTL

**Storage model**:
- Job-based storage under `STORAGE_DIR/{job_id}/`
- Files auto-deleted after TTL_MIN (default 30 minutes)
- Signed URLs include expiry timestamp and HMAC signature for security

**Audio processing flow**:
1. Accept file upload or download from URL (with MAX_DOWNLOAD_MB limit)
2. Decode using pydub (which requires ffmpeg)
3. Split into overlapping chunks based on step size: `step = chunk_ms - overlap_ms`
4. Export in requested format (mp3, wav, flac, ogg)
5. Return base64 data OR save to disk and generate signed URLs

## Development Commands

**Run locally**:
```bash
python app.py
# Or with uvicorn for auto-reload during development:
uvicorn app:app --reload --host 0.0.0.0 --port 8000
```

**Docker**:
```bash
docker build -t audio-splitter .
docker run -p 8000:8000 audio-splitter
```

**Install dependencies** (requires Python 3.12+ and ffmpeg):
```bash
pip install -r requirements.txt
# System dependency: ffmpeg must be installed
```

**Test the API**:
```bash
# Health check
curl http://localhost:8000/health

# Split a file (returns signed URLs)
curl -X POST http://localhost:8000/split -F "file=@audio.mp3" -F "chunk_ms=60000"

# Split with base64 response (no file storage)
curl -X POST http://localhost:8000/split -F "file=@audio.mp3" -F "return_mode=base64"
```

**Interactive API docs**: Available at `http://localhost:8000/docs` (Swagger UI) when running locally.

## Environment Variables

- `STORAGE_DIR`: Temporary file storage location (default: `/tmp/splitter`)
- `TTL_MIN`: Minutes until signed URLs expire and files are deleted (default: `30`)
- `MAX_DOWNLOAD_MB`: Maximum size for URL downloads (default: `200`)
- `SIGNING_SECRET`: HMAC secret for URL signing (auto-generated if not set)

## Key Implementation Details

**Signed URLs**: Uses HMAC-SHA256 with payload format `{path}|{expiry_timestamp}`. Signature verification in `_verify()` uses timing-safe comparison.

**Chunk calculation**: Number of chunks = `ceil((duration - overlap_ms) / (chunk_ms - overlap_ms))`. Each chunk starts at `i * step` where step accounts for overlap.

**Return modes**:
- `return_mode="base64"`: Inline JSON with base64-encoded audio (no storage)
- `return_mode="urls"`: Store files and return signed URLs with expiry (default)

**Dependencies**: pydub requires ffmpeg to be installed at the system level (handled in Dockerfile via apt-get).

## Concurrency Hardening

The service is designed to handle simultaneous requests from multiple users:

**Job isolation**: Each request gets a 128-bit unique job_id (`secrets.token_hex(16)`), making collisions virtually impossible even under extreme load.

**Atomic file writes**: Audio chunks are written to temp files first, then atomically renamed to final paths. This prevents serving partial/corrupted files.

**Thread pool execution**: CPU-bound pydub/ffmpeg operations run in a `ThreadPoolExecutor` to avoid blocking the async event loop during concurrent requests.

**Active job tracking**: An in-memory set (`_active_jobs`) with async lock prevents the janitor from deleting jobs that are still being processed.

**Completion markers**: A `.complete` file is written after all chunks are saved. The `/get` endpoint checks for this marker before serving files.

**Path traversal protection**: Regex validation on `job_id` (`^[a-f0-9]{32}$`) and `filename` (`^\d+\.(mp3|wav|flac|ogg)$`) prevents directory traversal attacks.
