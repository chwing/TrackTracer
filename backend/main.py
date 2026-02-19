from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
import yt_dlp
import re
import asyncio
import urllib.parse
from shazamio import Shazam
import os
import tempfile

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, replace with your frontend URL
    allow_methods=["*"],
    allow_headers=["*"],
)


# Helper: remove `list` query param from a URL while preserving others
def sanitize_remove_list(raw: str) -> str:
    try:
        parsed = urllib.parse.urlparse(raw)
        if not parsed.query:
            return raw
        qs = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
        filtered = [(k, v) for (k, v) in qs if k.lower() != 'list']
        new_query = urllib.parse.urlencode(filtered)
        cleaned = urllib.parse.urlunparse(parsed._replace(query=new_query))
        return str(cleaned)
    except Exception:
        # fallback regex removal
        result: str = re.sub(r'([?&])list=[^&]*&?', lambda m: '?' if m.group(1) == '?' else '', raw).rstrip('&').rstrip('?')
        return result


# 1. Health Check (To verify the backend is actually alive)
@app.get("/")
async def root():
    return {"status": "Backend is running!", "endpoints": ["/process", "/"]}


@app.get("/process")
async def process_link(url: str = Query(..., description="The URL of the music video")):
    if not url:
        raise HTTPException(status_code=400, detail="URL is required")

    # Options to make yt-dlp faster and prevent hanging
    ydl_opts = {
        'format': 'bestaudio/best',
        'quiet': True,
        'no_warnings': True,
        'skip_download': True,
        'socket_timeout': 10,  # Stop waiting after 10 seconds for sockets
    }

    # Timeout for the whole extraction attempt (seconds)
    TRY_TIMEOUT = 10

    async def extract(target_url: str):
        # Run yt-dlp extraction in thread pool
        def _extract():
            return yt_dlp.YoutubeDL(ydl_opts).extract_info(target_url, download=False)
        return await asyncio.to_thread(_extract)

    try:
        try:
            # Try original URL first and wait up to TRY_TIMEOUT seconds
            info = await asyncio.wait_for(extract(url), timeout=TRY_TIMEOUT)
        except asyncio.TimeoutError:
            # If it times out, try without the `list` param (for YouTube links)
            print(f"Initial extraction timed out for URL: {url}")
            cleaned = sanitize_remove_list(url)
            if cleaned and cleaned != url:
                print(f"Retrying with cleaned URL (removed list param): {cleaned}")
                try:
                    info = await asyncio.wait_for(extract(cleaned), timeout=TRY_TIMEOUT)
                except asyncio.TimeoutError:
                    print(f"Retry extraction also timed out for cleaned URL: {cleaned}")
                    raise HTTPException(status_code=504, detail="Processing timed out for both original and cleaned URL.")
                except Exception as e2:
                    print(f"Error during retry extraction: {e2}")
                    raise HTTPException(status_code=500, detail="Failed to process video after retrying without playlist parameter.")
            else:
                raise HTTPException(status_code=504, detail="Processing timed out and URL could not be sanitized.")
        except Exception as e:
            # Other errors from yt-dlp on the original URL - do NOT retry with cleaned URL; surface error
            print(f"Error during extraction for URL {url}: {e}")
            raise HTTPException(status_code=500, detail="Failed to process video. The link might be broken or restricted.")

        # If we reach here, `info` should be populated from either the original or cleaned attempt
        description = info.get('description', "")

        # Determine the type of media
        media_type = "Unknown"
        if 'youtube' in str(url).lower() or info.get('extractor') == 'youtube':
            media_type = "YouTube"
        elif 'soundcloud' in str(url).lower() or info.get('extractor') == 'soundcloud':
            media_type = "SoundCloud"
        else:
            media_type = info.get('extractor', 'Unknown')

        # Regex for timestamps
        pattern = r'(\d{1,2}:\d{2}(?::\d{2})?)\s*[-–—:]\s*(.*)'
        tracks = [{"time": m[0], "title": m[1].strip()} for m in re.findall(pattern, description)]

        # If no tracks found in description, use Shazam identification
        if not tracks or len(tracks) == 0:
            print(f"No tracks found in description. Attempting Shazam identification...")
            try:
                duration = int(info.get('duration', 0))
                if duration > 0 and duration < 3600:  # Only process videos up to 1 hour
                    shazam_tracks = await extract_audio_and_identify(url, duration)
                    if shazam_tracks:
                        tracks = shazam_tracks
                        print(f"Shazam found {len(tracks)} track(s)")
            except Exception as e:
                print(f"Shazam identification failed: {e}")

        # If still no tracks, use the video title as fallback
        if not tracks or len(tracks) == 0:
            tracks = [{"time": "00:00", "title": info.get('title')}]

        return {
            "title": info.get('title'),
            "type": media_type,
            "tracks": tracks
        }
    except HTTPException:
        # Re-raise HTTP exceptions created above
        raise
    except Exception as e:
        print(f"Unhandled error: {e}")
        raise HTTPException(status_code=500, detail="Failed to process video. The link might be broken or restricted.")

# Shazam-based song identification (simplified)
async def identify_song_from_audio(audio_file: str):
    """
    Identify a song from an audio file using Shazam.
    Returns song info or None if not found.
    """
    try:
        shazam = Shazam()
        with open(audio_file, 'rb') as f:
            audio_data = f.read()

        result = await asyncio.to_thread(
            shazam.recognize_song,
            audio_data
        )

        if result and 'track' in result:
            track = result['track']
            return {
                'title': f"{track.get('subtitle', '')} - {track.get('title', 'Unknown')}".strip(" - "),
                'artist': track.get('subtitle', 'Unknown')
            }
    except Exception as e:
        print(f"Shazam identification failed: {e}")

    return None


async def extract_audio_and_identify(video_url: str, duration_seconds: int) -> list:
    """
    Download video, extract audio, and attempt to identify songs.
    Falls back to Shazam if no tracklist is found in description.
    """
    tracks = []

    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            # Download the best audio available
            download_opts = {
                'format': 'bestaudio/best',
                'quiet': True,
                'no_warnings': True,
                'extract_audio': True,
                'audio_format': 'wav',
                'audio_quality': '192',
                'outtmpl': os.path.join(temp_dir, 'audio'),
                'socket_timeout': 30,
            }

            def _download():
                with yt_dlp.YoutubeDL(download_opts) as ydl:
                    return ydl.extract_info(video_url, download=True)

            await asyncio.to_thread(_download)

            # Find the downloaded audio file
            audio_file = None
            for file in os.listdir(temp_dir):
                if file.endswith(('.wav', '.mp3', '.m4a')):
                    audio_file = os.path.join(temp_dir, file)
                    break

            if audio_file and os.path.exists(audio_file):
                # Try to identify the song
                song_info = await identify_song_from_audio(audio_file)
                if song_info:
                    tracks.append({
                        'time': '00:00',
                        'title': song_info['title']
                    })

    except Exception as e:
        print(f"Audio extraction/identification error: {e}")

    return tracks

