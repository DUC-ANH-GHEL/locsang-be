from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
import httpx

router = APIRouter()

class GeminiRequest(BaseModel):
    text: str
    prompt: str

class GeminiResponse(BaseModel):
    result: str

API_KEY = 'AIzaSyCJtsERcSIYdBnOvUWpL7Ca9BGuOGUOxEs'
GEMINI_URL = 'https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent'

@router.post("/ask", response_model=GeminiResponse)
async def ask_gemini(data: GeminiRequest):
    body = {
        "contents": [
            {
                "role": "user",
                "parts": [
                    {"text": data.prompt + f"\n\nBình luận: {data.text}"}
                ]
            }
        ]
    }
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{GEMINI_URL}?key={API_KEY}",
                json=body,
                headers={"Content-Type": "application/json"}
            )
        response.raise_for_status()
        data = response.json()
        result = data.get("candidates", [{}])[0].get("content", {}).get("parts", [{}])[0].get("text", "Không rõ")
        return GeminiResponse(result=result.strip().lower())
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Gemini API error: {str(e)}")
