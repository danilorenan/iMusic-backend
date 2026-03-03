from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import yt_dlp
import time
import asyncio
import os
import tempfile
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

# ── Cookies Setup ──────────────────────────────────────────────
def _get_cookies_path() -> str | None:
    local_path = os.path.join(os.path.dirname(__file__), "cookies.txt")
    if os.path.exists(local_path):
        print("🍪 Usando cookies.txt local")
        return local_path

    cookies_env = os.environ.get("YOUTUBE_COOKIES", "")
    if cookies_env:
        tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".txt", delete=False, prefix="yt_cookies_"
        )
        tmp.write(cookies_env)
        tmp.close()
        print(f"🍪 Cookies carregados da env → {tmp.name}")
        return tmp.name

    print("⚠️ Nenhum cookie encontrado")
    return None

COOKIES_PATH = _get_cookies_path()
# ───────────────────────────────────────────────────────────────

def _extract(video_id: str) -> dict:
    """Tenta múltiplas estratégias de extração"""

    url = f"https://www.youtube.com/watch?v={video_id}"

    # Estratégia 1: Com cookies + formato flexível
    strategies = [
        {
            'format': 'bestaudio/best',
            'cookiefile': COOKIES_PATH,
        },
        # Estratégia 2: Forçar client web
        {
            'format': 'bestaudio/best',
            'cookiefile': COOKIES_PATH,
            'extractor_args': {'youtube': {'player_client': ['web']}},
        },
        # Estratégia 3: Client mweb (mobile web)
        {
            'format': 'bestaudio/best',
            'cookiefile': COOKIES_PATH,
            'extractor_args': {'youtube': {'player_client': ['mweb']}},
        },
        # Estratégia 4: Client android (menos restrições)
        {
            'format': 'bestaudio/best',
            'extractor_args': {'youtube': {'player_client': ['android']}},
        },
        # Estratégia 5: iOS client
        {
            'format': 'bestaudio/best',
            'extractor_args': {'youtube': {'player_client': ['ios']}},
        },
        # Estratégia 6: mediaconnect
        {
            'format': 'bestaudio/best',
            'extractor_args': {'youtube': {'player_client': ['mediaconnect']}},
        },
    ]

    last_error = None

    for i, strategy in enumerate(strategies):
        base_opts = {
            'quiet': True,
            'no_warnings': True,
            'socket_timeout': 15,
            'geo_bypass': True,
            'nocheckcertificate': True,
        }

        # Merge strategy opts
        base_opts.update(strategy)

        # Remove cookiefile se None
        if base_opts.get('cookiefile') is None:
            base_opts.pop('cookiefile', None)

        try:
            print(f"🔄 Estratégia {i+1} para {video_id}...")
            with yt_dlp.YoutubeDL(base_opts) as ydl:
                info = ydl.extract_info(url, download=False)

                # Verifica se realmente tem URL de áudio
                audio_url = info.get("url")
                if not audio_url:
                    # Tenta pegar dos formatos
                    formats = info.get("formats", [])
                    audio_formats = [
                        f for f in formats
                        if f.get("acodec") != "none" and f.get("url")
                    ]
                    if audio_formats:
                        best = audio_formats[-1]
                        audio_url = best["url"]
                        info["abr"] = best.get("abr", 0)
                        info["ext"] = best.get("ext", "unknown")

                if not audio_url:
                    raise Exception("Nenhuma URL de áudio encontrada")

                print(f"✅ Estratégia {i+1} funcionou!")
                return {
                    "url": audio_url,
                    "duration": info.get("duration", 0),
                    "title": info.get("title", ""),
                    "bitrate": info.get("abr", 0),
                    "format": info.get("ext", "unknown"),
                    "expires_at": int(time.time() + CACHE_TTL),
                    "strategy": i + 1,
                }
        except Exception as e:
            last_error = str(e)
            print(f"❌ Estratégia {i+1} falhou: {last_error}")
            continue

    raise Exception(f"Todas as estratégias falharam. Último erro: {last_error}")


@app.get("/")
def health():
    return {
        "status": "Render is Awake 🚀",
        "cached_items": len(cache),
        "cookies_loaded": COOKIES_PATH is not None,
    }

@app.get("/audio/{video_id}")
async def get_audio(video_id: str):
    if video_id in cache:
        entry = cache[video_id]
        if time.time() < entry["expires_at"]:
            return JSONResponse(
                content={**entry, "cached": True},
                headers={"X-Cache": "HIT"},
            )

    try:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(executor, _extract, video_id)
        cache[video_id] = result
        return JSONResponse(
            content={**result, "cached": False},
            headers={"X-Cache": "MISS"},
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/debug/{video_id}")
async def debug_formats(video_id: str):
    """Debug: lista todos os formatos disponíveis com todas as estratégias"""
    clients = ['default', 'web', 'mweb', 'android', 'ios', 'mediaconnect']
    all_results = {}

    for client in clients:
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'socket_timeout': 15,
        }
        if COOKIES_PATH:
            ydl_opts['cookiefile'] = COOKIES_PATH
        if client != 'default':
            ydl_opts['extractor_args'] = {'youtube': {'player_client': [client]}}

        try:
            url = f"https://www.youtube.com/watch?v={video_id}"
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False, process=False)
                formats = []
                for f in info.get("formats", []):
                    formats.append({
                        "id": f.get("format_id"),
                        "ext": f.get("ext"),
                        "acodec": f.get("acodec"),
                        "vcodec": f.get("vcodec"),
                        "abr": f.get("abr"),
                        "note": f.get("format_note"),
                    })
                audio_count = len([
                    f for f in formats if f.get("acodec") != "none"
                ])
                all_results[client] = {
                    "total": len(formats),
                    "audio_formats": audio_count,
                    "formats": formats,
                }
        except Exception as e:
            all_results[client] = {"error": str(e)}

    return {"video_id": video_id, "results": all_results}


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
            tasks.append((
                video_id,
                asyncio.get_event_loop().run_in_executor(executor, _extract, video_id),
            ))

    for video_id, task in tasks:
        try:
            result = await task
            cache[video_id] = result
            results[video_id] = "resolved"
        except:
            results[video_id] = "failed"
    return {"results": results}