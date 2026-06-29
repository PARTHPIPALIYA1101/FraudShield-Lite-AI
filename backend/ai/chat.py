"""Provider-agnostic streaming chat for the "AI Analyst" assistant.

History wire format (also persisted in ai_chat_sessions.messages):
    [{"role": "user" | "assistant", "content": "<text>"}, ...]
Gemini wants role "model"/"parts"; we translate at the boundary.
"""

from typing import AsyncIterator

from config import settings

# System prompt: frames the model as a fraud-analyst copilot (not the JSON scorer).
ANALYST_SYSTEM_PROMPT = """You are an AI fraud-analyst assistant embedded in a \
real-time fraud detection dashboard. You help human analysts understand and act \
on transactions the system has scored.

Guidelines:
- Be concise and concrete. Analysts are busy; lead with the answer.
- When transaction context is provided, ground your reasoning in those specifics \
(amount vs. the user's norm, velocity, foreign/new merchant, time of day).
- Explain WHY a transaction looks risky or safe; suggest the next investigative step.
- If you lack the data to answer, say so plainly rather than speculating.
- You are an assistant, not the system of record — never claim to have changed a \
decision or blocked a card; recommend the action instead."""


def build_context_block(transactions: list[dict]) -> str:
    """Render the analyst-pinned transactions into a compact context block ('' if none)."""
    if not transactions:
        return ""
    lines = ["CONTEXT — transactions the analyst is asking about:"]
    for t in transactions:
        lines.append(
            f"- {t.get('merchant', '?')} ${t.get('amount', 0):.2f} "
            f"[{t.get('decision', 'UNSCORED')}"
            + (f" score={t['fraud_score']:.2f}" if t.get("fraud_score") is not None else "")
            + f"] user={t.get('user_id', '?')}"
            + (f" foreign" if t.get("is_foreign_merchant") else "")
            + (f" — {t['explanation']}" if t.get("explanation") else "")
        )
    return "\n".join(lines) + "\n\n"


async def stream_answer(
    history: list[dict],
    user_message: str,
) -> AsyncIterator[str]:
    """Stream the assistant's reply (text chunks) to `user_message` given prior `history`."""
    provider = settings.LLM_PROVIDER.lower().strip()
    if provider == "anthropic":
        async for chunk in _stream_anthropic(history, user_message):
            yield chunk
    else:
        async for chunk in _stream_gemini(history, user_message):
            yield chunk


# Gemini (default)
async def _stream_gemini(history: list[dict], user_message: str) -> AsyncIterator[str]:
    import google.generativeai as genai

    genai.configure(api_key=settings.GOOGLE_API_KEY)
    model = genai.GenerativeModel(
        model_name=settings.GEMINI_MODEL,
        system_instruction=ANALYST_SYSTEM_PROMPT,
        generation_config={"temperature": 0.4, "max_output_tokens": 1024},
    )

    # Translate neutral history -> Gemini's {role, parts} with role "model".
    gemini_history = [
        {
            "role": "model" if m["role"] == "assistant" else "user",
            "parts": [m["content"]],
        }
        for m in history
    ]
    chat = model.start_chat(history=gemini_history)

    response = await chat.send_message_async(user_message, stream=True)
    async for chunk in response:
        # chunk.text raises if a chunk has no text part (e.g. safety) — guard it.
        try:
            text = chunk.text
        except Exception:
            text = ""
        if text:
            yield text


# Anthropic / Claude (alternate; uses ANTHROPIC_BASE_URL)
async def _stream_anthropic(history: list[dict], user_message: str) -> AsyncIterator[str]:
    from anthropic import AsyncAnthropic

    client = AsyncAnthropic(
        api_key=settings.ANTHROPIC_API_KEY,
        base_url=settings.ANTHROPIC_BASE_URL,
    )
    # Anthropic uses "assistant"/"user" already; just append the new user turn.
    messages = [{"role": m["role"], "content": m["content"]} for m in history]
    messages.append({"role": "user", "content": user_message})

    try:
        async with client.messages.stream(
            model=settings.ANTHROPIC_MODEL,
            max_tokens=1024,
            system=ANALYST_SYSTEM_PROMPT,
            messages=messages,
        ) as stream:
            async for text in stream.text_stream:
                if text:
                    yield text
    finally:
        await client.close()
