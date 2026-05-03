import os
import re
import tempfile
import subprocess
import httpx
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

app = FastAPI()

GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")


class TranscribeRequest(BaseModel):
    url: str


def download_audio(url: str, output_path: str) -> str:
    """Use yt-dlp to download audio from URL."""
    cmd = [
        "yt-dlp",
        "--extract-audio",
        "--audio-format", "mp3",
        "--audio-quality", "0",
        "--output", output_path,
        "--no-playlist",
        url
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    if result.returncode != 0:
        raise Exception(f"下载失败: {result.stderr}")
    # yt-dlp may append extension
    if not os.path.exists(output_path):
        output_path = output_path.replace(".mp3", "") + ".mp3"
    return output_path


def transcribe_with_groq(audio_path: str) -> str:
    """Transcribe audio using Groq's Whisper API."""
    if not GROQ_API_KEY:
        raise Exception("未设置 GROQ_API_KEY 环境变量")

    with open(audio_path, "rb") as f:
        audio_data = f.read()

    import httpx
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


def polish_with_deepseek(raw_text: str) -> str:
    """Use DeepSeek to clean up and format the transcription."""
    if not DEEPSEEK_API_KEY:
        # Return basic formatting if no DeepSeek key
        return basic_format(raw_text)

    prompt = f"""你是一个播客文稿整理助手。请将以下语音转写的原始文字整理成干净、易读的 Markdown 格式文稿。

要求：
1. 清理口语化语气词（"然后然后"、"就是那个"、"嗯"、"啊"等）
2. 合理断句分段，每段不超过200字
3. 根据内容自动添加小标题（用 ## 标记）
4. 保留说话人的原意，不要改变内容
5. 输出纯 Markdown，不要加任何解释

原始文字：
{raw_text}"""

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
    return data["choices"][0]["message"]["content"]


def basic_format(text: str) -> str:
    """Basic formatting without AI."""
    # Split into paragraphs by punctuation
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
            # Step 1: Download
            audio_path = download_audio(req.url, audio_path)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"音频下载失败：{str(e)}")

        try:
            # Step 2: Transcribe
            raw_text = transcribe_with_groq(audio_path)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"语音转写失败：{str(e)}")

        try:
            # Step 3: Polish
            markdown = polish_with_deepseek(raw_text)
        except Exception as e:
            markdown = basic_format(raw_text)

        return JSONResponse({
            "markdown": markdown,
            "raw": raw_text
        })


# Serve frontend
app.mount("/", StaticFiles(directory="static", html=True), name="static")
