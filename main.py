from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import yt_dlp
import time
import asyncio
import random
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

cache: dict = {}
CACHE_TTL = 18000
executor = ThreadPoolExecutor(max_workers=4)

# Seus proxies Webshare
PROXIES = [
    "http://rsmkyxgl:eeqkqp76p7pj@31.59.20.176:6754",
    "http://rsmkyxgl:eeqkqp76p7pj@23.95.150.145:6114",
    "http://rsmkyxgl:eeqkqp76p7pj@198.23.239.134:6540",
    "http://rsmkyxgl:eeqkqp76p7pj@45.38.107.97:6014",
    "http://rsmkyxgl:eeqkqp76p7pj@107.172.163.27:6543",
    "http://rsmkyxgl:eeqkqp76p7pj@198.105.121.200:6462",
    "http://rsmkyxgl:eeqkqp76p7pj@64.137.96.74:6641",
    "http://rsmkyxgl:eeqkqp76p7pj@216.10.27.159:6837",
    "http://rsmkyxgl:eeqkqp76p7pj@142.111.67.146:5611",
    "http://rsmkyxgl:eeqkqp76p7pj@194.39.32.164:6461",
]

def _extract(video_id: str) -> dict:
    url = f"https://www.youtube.com/watch?v={video_id}"
    
    # Embaralha proxies para distribuir carga
    shuffled_proxies = random.sample(PROXIES, len(PROXIES))
    
    for proxy in shuffled_proxies:
        ydl_opts = {
            'format': 'bestaudio/best',
            'quiet': True,
            'no_warnings': True,
            'socket_timeout': 20,
            'proxy': proxy,
            'extractor_args': {'youtube': {'player_client': ['android']}},
        }
        
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                audio_url = info.get("url")
                
                if not audio_url:
                    formats = info.get("formats", [])
                    audio_formats = [f for f in formats if f.get("acodec") != "none" and f.get("url")]
                    if audio_formats:
                        best = audio_formats[-1]
                        audio_url = best["url"]
                        info["abr"] = best.get("abr", 0)
                        info["ext"] = best.get("ext", "unknown")
                
                if audio_url:
                    return {
                        "url": audio_url,
                        "duration": info.get("duration", 0),
                        "title": info.get("title", ""),
                        "bitrate": info.get("abr", 0),
                        "format": info.get("ext", "unknown"),
                        "expires_at": int(time.time() + CACHE_TTL),
                    }
        except Exception as e:
            print(f"❌ Proxy falhou: {proxy.split('@')[1]} - {str(e)[:50]}")
            continue
    
    raise Exception("Todos os proxies falharam")

@app.get("/")
def health():
    return {"status": "🚀 Online", "cached": len(cache), "proxies": len(PROXIES)}

@app.get("/audio/{video_id}")
async def get_audio(video_id: str):
    if video_id in cache and time.time() < cache[video_id]["expires_at"]:
        return JSONResponse(content={**cache[video_id], "cached": True})
    
    try:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(executor, _extract, video_id)
        cache[video_id] = result
        return JSONResponse(content={**result, "cached": False})
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

class PrefetchRequest(BaseModel):
    ids: List[str]

@app.post("/prefetch")
async def prefetch(req: PrefetchRequest):
    results = {}
    for video_id in req.ids[:5]:
        if video_id in cache and time.time() < cache[video_id]["expires_at"]:
            results[video_id] = "cached"
        else:
            try:
                loop = asyncio.get_event_loop()
                result = await loop.run_in_executor(executor, _extract, video_id)
                cache[video_id] = result
                results[video_id] = "resolved"
            except:
                results[video_id] = "failed"
    return {"results": results}