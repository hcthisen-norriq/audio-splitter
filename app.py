from fastapi import FastAPI, File, UploadFile, Form, HTTPException, Request
from fastapi.responses import JSONResponse, FileResponse
from pydub import AudioSegment
import base64, io, math, uvicorn, os, time, hmac, hashlib, secrets, asyncio, pathlib, datetime as dt
import httpx
from typing import Optional

app = FastAPI(title="Audio Splitter API")

@app.get("/health")
def health():
    return {"status": "ok"}

SUPPORTED_EXPORTS = {"mp3": "audio/mpeg", "wav": "audio/wav", "flac": "audio/flac", "ogg": "audio/ogg"}

# --- Config via env ---
STORAGE_DIR = os.getenv("STORAGE_DIR", "/tmp/splitter")
TTL_MIN = int(os.getenv("TTL_MIN", "30"))  # signed URL expiry & deletion window
MAX_DOWNLOAD_MB = int(os.getenv("MAX_DOWNLOAD_MB", "200"))
SIGNING_SECRET = os.getenv("SIGNING_SECRET") or secrets.token_urlsafe(32)

pathlib.Path(STORAGE_DIR).mkdir(parents=True, exist_ok=True)

def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")

def _sign(payload: str) -> str:
    return _b64url(hmac.new(SIGNING_SECRET.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).digest())

def _verify(payload: str, sig: str) -> bool:
    want = _sign(payload)
    return hmac.compare_digest(want, sig)

async def _download_url(url: str, cap_mb: int) -> bytes:
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            async with client.stream("GET", url, follow_redirects=True) as resp:
                resp.raise_for_status()
                chunks = []
                total = 0
                limit = cap_mb * 1024 * 1024
                async for part in resp.aiter_bytes():
                    total += len(part)
                    if total > limit:
                        raise HTTPException(status_code=413, detail=f"Remote file exceeds {cap_mb} MB limit")
                    chunks.append(part)
                return b"".join(chunks)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to download URL: {e}")

def _job_dir(job_id: str) -> str:
    d = os.path.join(STORAGE_DIR, job_id)
    os.makedirs(d, exist_ok=True)
    return d

def _now_ts() -> int:
    return int(time.time())

def _to_iso(ts: int) -> str:
    return dt.datetime.utcfromtimestamp(ts).replace(tzinfo=dt.timezone.utc).isoformat()

@app.post("/split")
async def split_audio(
    request: Request,
    file: Optional[UploadFile] = File(None),
    url: Optional[str] = Form(None),
    chunk_ms: int = Form(600_000),
    overlap_ms: int = Form(0),
    export_format: str = Form("mp3"),
    return_mode: str = Form("urls")  # "urls" (default) or "base64"
):
    if export_format not in SUPPORTED_EXPORTS:
        raise HTTPException(status_code=400, detail=f"Unsupported format: {export_format}")
    if chunk_ms <= 0 or overlap_ms < 0 or overlap_ms >= chunk_ms:
        raise HTTPException(status_code=400, detail="Invalid chunk/overlap values")
    if file is None and not url:
        raise HTTPException(status_code=422, detail="Provide either a file upload or a url")

    # ---- read bytes ----
    raw = await file.read() if file is not None else await _download_url(url, MAX_DOWNLOAD_MB)
    if not raw:
        raise HTTPException(status_code=400, detail="Empty audio data")

    # ---- decode ----
    try:
        audio = AudioSegment.from_file(io.BytesIO(raw))
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Could not decode audio: {e}")

    duration = len(audio)  # ms
    step = chunk_ms - overlap_ms
    n = max(1, math.ceil((max(1, duration - overlap_ms)) / step))

    mime = SUPPORTED_EXPORTS[export_format]
    chunks_out = []

    # Per-job storage
    job_id = secrets.token_hex(8)
    base_url = str(request.base_url).rstrip("/")

    # Expiry for signed URLs
    exp_ts = _now_ts() + TTL_MIN * 60

    for i in range(n):
        start = max(0, i * step)
        end = min(duration, start + chunk_ms)
        segment = audio[start:end]

        if return_mode == "base64":
            buf = io.BytesIO()
            segment.export(buf, format=export_format)
            b64 = base64.b64encode(buf.getvalue()).decode("ascii")
            chunks_out.append({
                "index": i, "start_ms": start, "end_ms": end,
                "mime": mime, "data_base64": b64
            })
        else:
            # save to disk and return signed URL
            job_path = _job_dir(job_id)
            filename = f"{i}.{export_format}"
            filepath = os.path.join(job_path, filename)

            with open(filepath, "wb") as f:
                segment.export(f, format=export_format)

            # payload to sign: /get/{job_id}/{filename}|{exp}
            relpath = f"/get/{job_id}/{filename}"
            payload = f"{relpath}|{exp_ts}"
            sig = _sign(payload)
            url_signed = f"{base_url}{relpath}?exp={exp_ts}&sig={sig}"

            chunks_out.append({
                "index": i, "start_ms": start, "end_ms": end,
                "mime": mime, "url": url_signed, "expires_at": _to_iso(exp_ts)
            })

    return JSONResponse({
        "source": "upload" if file is not None else "url",
        "return": "base64" if return_mode == "base64" else "urls",
        "expires_in_minutes": TTL_MIN if return_mode != "base64" else None,
        "chunks": chunks_out,
        "total_duration_ms": duration,
        "chunk_ms": chunk_ms,
        "overlap_ms": overlap_ms,
        "format": export_format,
        "job_id": job_id if return_mode != "base64" else None
    })

@app.get("/get/{job_id}/{filename}")
async def get_chunk(job_id: str, filename: str, exp: int, sig: str):
    # verify expiry
    if _now_ts() > int(exp):
        raise HTTPException(status_code=410, detail="URL expired")
    # verify signature
    relpath = f"/get/{job_id}/{filename}"
    if not _verify(f"{relpath}|{exp}", sig):
        raise HTTPException(status_code=403, detail="Invalid signature")

    # serve file
    filepath = os.path.join(STORAGE_DIR, job_id, filename)
    if not os.path.isfile(filepath):
        raise HTTPException(status_code=404, detail="Not found")

    # infer mime from extension
    ext = pathlib.Path(filename).suffix.lstrip(".").lower()
    if ext not in SUPPORTED_EXPORTS:
        raise HTTPException(status_code=400, detail="Unsupported file type")
    return FileResponse(filepath, media_type=SUPPORTED_EXPORTS[ext], filename=filename)

# --- Background janitor: removes old files/folders ---
async def _janitor():
    while True:
        try:
            cutoff = _now_ts() - TTL_MIN * 60
            for root, dirs, files in os.walk(STORAGE_DIR):
                for d in list(dirs):
                    dpath = os.path.join(root, d)
                    try:
                        mtime = int(os.path.getmtime(dpath))
                        if mtime < cutoff:
                            # delete entire job dir
                            for r, _, fs in os.walk(dpath, topdown=False):
                                for name in fs:
                                    try:
                                        os.remove(os.path.join(r, name))
                                    except Exception:
                                        pass
                                try:
                                    os.rmdir(r)
                                except Exception:
                                    pass
                    except Exception:
                        pass
        except Exception:
            pass
        await asyncio.sleep(300)  # run every 5 minutes

@app.on_event("startup")
async def _on_startup():
    asyncio.create_task(_janitor())

if __name__ == "__main__":
    uvicorn.run("app:app", host="0.0.0.0", port=8000)
