from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import yt_dlp
import time
import asyncio
from concurrent.futures import ThreadPoolExecutor
from pydantic import BaseModel
from typing import List

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Cache em Memória (URLs guardadas por 5 horas)
cache: dict = {}
CACHE_TTL = 18000  

executor = ThreadPoolExecutor(max_workers=4)

def _extract(video_id: str) -> dict:
    ydl_opts = {
        'format': 'bestaudio[ext=m4a]/bestaudio',
        'quiet': True,
        'no_warnings': True,
        'socket_timeout': 10,
    }
    try:
        url = f"https://www.youtube.com/watch?v={video_id}"
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            return {
                "url": info["url"],
                "duration": info.get("duration", 0),
                "title": info.get("title", ""),
                "bitrate": info.get("abr", 0),
                "format": info.get("ext", "unknown"),
                "expires_at": int(time.time() + CACHE_TTL),
            }
    except Exception as e:
        raise Exception(f"Erro yt-dlp: {str(e)}")

@app.get("/")
def health():
    return {"status": "Render is Awake 🚀", "cached_items": len(cache)}

@app.get("/audio/{video_id}")
async def get_audio(video_id: str):
    if video_id in cache:
        entry = cache[video_id]
        if time.time() < entry["expires_at"]:
            return JSONResponse(content={**entry, "cached": True}, headers={"X-Cache": "HIT"})

    try:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(executor, _extract, video_id)
        cache[video_id] = result
        return JSONResponse(content={**result, "cached": False}, headers={"X-Cache": "MISS"})
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

class PrefetchRequest(BaseModel):
    ids: List[str]

@app.post("/prefetch")
async def prefetch(req: PrefetchRequest):
    results = {}
    tasks = []
    for video_id in req.ids[:5]:
        if video_id in cache and time.time() < cache[video_id]["expires_at"]:
            results[video_id] = "cached"
        else:
            tasks.append((video_id, asyncio.get_event_loop().run_in_executor(executor, _extract, video_id)))

    for video_id, task in tasks:
        try:
            result = await task
            cache[video_id] = result
            results[video_id] = "resolved"
        except:
            results[video_id] = "failed"
    return {"results": results}