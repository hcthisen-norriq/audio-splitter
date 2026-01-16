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
# Or with uvicorn directly:
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
