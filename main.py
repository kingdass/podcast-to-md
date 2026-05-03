import os
import re
import math
import json
import tempfile
import subprocess
import httpx
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse
from pydantic import BaseModel

app = FastAPI()

GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")

MAX_FILE_MB = 20


class TranscribeRequest(BaseModel):
    url: str


def download_audio(url: str, output_path: str) -> str:
    cmd = [
        "yt-dlp",
        "--extract-audio",
        "--audio-format", "mp3",
        "--audio-quality", "5",
        "--postprocessor-args", "ffmpeg:-ar 16000 -ac 1",
        "--output", output_path,
        "--no-playlist",
        url
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    if result.returncode != 0:
        raise Exception(f"下载失败: {result.stderr}")
    if not os.path.exists(output_path):
        output_path = output_path.replace(".mp3", "") + ".mp3"
    return output_path


def get_audio_duration(audio_path: str) -> float:
    cmd = [
        "ffprobe", "-v", "quiet", "-print_format", "json",
        "-show_format", audio_path
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    data = json.loads(result.stdout)
    return float(data["format"]["duration"])


def split_audio(audio_path: str, tmpdir: str, chunk_minutes: int = 20) -> list:
    duration = get_audio_duration(audio_path)
    chunk_seconds = chunk_minutes * 60
    num_chunks = math.ceil(duration / chunk_seconds)
    chunks = []
    for i in range(num_chunks):
        start = i * chunk_seconds
        chunk_path = os.path.join(tmpdir, f"chunk_{i:03d}.mp3")
        cmd = [
            "ffmpeg", "-i", audio_path,
            "-ss", str(start),
            "-t", str(chunk_seconds),
            "-acodec", "copy",
            "-y", chunk_path
        ]
        subprocess.run(cmd, capture_output=True, timeout=120)
        if os.path.exists(chunk_path):
            chunks.append(chunk_path)
    return chunks


def transcribe_chunk(audio_path: str) -> str:
    if not GROQ_API_KEY:
        raise Exception("未设置 GROQ_API_KEY 环境变量")
    with open(audio_path, "rb") as f:
        audio_data = f.read()
    with httpx.Client(timeout=300) as client:
        response = client.post(
            "https://api.groq.com/openai/v1/audio/transcriptions",
            headers={"Authorization": f"Bearer {GROQ_API_KEY}"},
            files={"file": ("audio.mp3", audio_data, "audio/mpeg")},
            data={
                "model": "whisper-large-v3",
                "language": "zh",
                "response_format": "text"
            }
        )
    if response.status_code != 200:
        raise Exception(f"Groq 转写失败: {response.text}")
    return response.text


def transcribe_audio(audio_path: str, tmpdir: str) -> str:
    file_size_mb = os.path.getsize(audio_path) / (1024 * 1024)
    if file_size_mb <= MAX_FILE_MB:
        return transcribe_chunk(audio_path)
    chunks = split_audio(audio_path, tmpdir, chunk_minutes=20)
    if not chunks:
        raise Exception("音频分段失败")
    results = []
    for i, chunk in enumerate(chunks):
        try:
            text = transcribe_chunk(chunk)
            results.append(text.strip())
        except Exception as e:
            results.append(f"[第{i+1}段转写失败: {str(e)}]")
    return "\n\n".join(results)


def polish_with_deepseek(raw_text: str) -> str:
    if not DEEPSEEK_API_KEY:
        return basic_format(raw_text)
    text_to_polish = raw_text[:8000] if len(raw_text) > 8000 else raw_text
    remainder = raw_text[8000:] if len(raw_text) > 8000 else ""
    prompt = f"""你是一个播客文稿整理助手。请将以下语音转写的原始文字整理成干净、易读的 Markdown 格式文稿。

要求：
1. 清理口语化语气词（"然后然后"、"就是那个"、"嗯"、"啊"等）
2. 合理断句分段，每段不超过200字
3. 根据内容自动添加小标题（用 ## 标记）
4. 保留说话人的原意，不要改变内容
5. 输出纯 Markdown，不要加任何解释

原始文字：
{text_to_polish}"""
    with httpx.Client(timeout=120) as client:
        response = client.post(
            "https://api.deepseek.com/chat/completions",
            headers={
                "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
                "Content-Type": "application/json"
            },
            json={
                "model": "deepseek-chat",
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 8000
            }
        )
    if response.status_code != 200:
        return basic_format(raw_text)
    data = response.json()
    polished = data["choices"][0]["message"]["content"]
    if remainder:
        polished += "\n\n" + basic_format(remainder)
    return polished


def basic_format(text: str) -> str:
    text = re.sub(r'([。！？])\s*', r'\1\n\n', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return f"# 播客文稿\n\n{text.strip()}"


@app.post("/api/transcribe")
async def transcribe(req: TranscribeRequest):
    if not req.url.strip():
        raise HTTPException(status_code=400, detail="请输入播客链接")
    with tempfile.TemporaryDirectory() as tmpdir:
        audio_path = os.path.join(tmpdir, "audio.mp3")
        try:
            audio_path = download_audio(req.url, audio_path)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"音频下载失败：{str(e)}")
        try:
            raw_text = transcribe_audio(audio_path, tmpdir)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"语音转写失败：{str(e)}")
        try:
            markdown = polish_with_deepseek(raw_text)
        except Exception as e:
            markdown = basic_format(raw_text)
        return JSONResponse({
            "markdown": markdown,
            "raw": raw_text
        })


app.mount("/", StaticFiles(directory="static", html=True), name="static")
