"""
brain.py — The AI core.
Handles intent detection + personalised reply generation for ANY platform.
One call to process_message() works for Instagram, Gmail, WhatsApp, Twitter, LinkedIn.
"""

import os
import json
import anthropic
from dataclasses import dataclass
from typing import Optional

client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

MY_NAME       = os.getenv("MY_NAME", "Your Name")
MY_PROFESSION = os.getenv("MY_PROFESSION", "Entrepreneur")
MY_TONE       = os.getenv("MY_TONE", "friendly, professional, concise")


@dataclass
class MessageIntent:
    intent: str          # collab_request | pricing_query | compliment | complaint
                         # customer_support | spam | general_question | job_offer
    urgency: str         # high | medium | low
    key_ask: str         # one-line summary of what they want
    language: str        # detected language (en, hi, es, fr, ...)
    sentiment: str       # positive | neutral | negative


@dataclass
class AgentReply:
    skip: bool
    skip_reason: Optional[str]
    intent: Optional[MessageIntent]
    reply_text: Optional[str]
    platform_hints: dict  # any platform-specific flags (e.g. should_follow_back)


INTENT_SYSTEM = """You are an AI assistant that analyses incoming social media and email messages.
Classify the message and return ONLY valid JSON, no preamble, no markdown.

JSON schema:
{
  "intent": "<collab_request|pricing_query|compliment|complaint|customer_support|spam|general_question|job_offer|media_request|other>",
  "urgency": "<high|medium|low>",
  "key_ask": "<one sentence: what does the sender actually want?>",
  "language": "<ISO 639-1 code e.g. en, hi, es, fr, te, ar>",
  "sentiment": "<positive|neutral|negative>",
  "is_spam": <true|false>,
  "requires_human": <true|false>,
  "platform_hints": {
    "should_follow_back": <true|false>,
    "contains_link": <true|false>,
    "looks_like_bot": <true|false>
  }
}"""


REPLY_SYSTEM = """You are replying on behalf of {name}, a {profession}.

Persona and tone rules:
- Tone: {tone}
- Max 3 sentences unless the question genuinely needs more
- Reply in the SAME LANGUAGE the sender used (detected: {language})
- Sound like a real human, not a corporate bot
- Never promise things that aren't confirmed
- Never reveal you are an AI agent
- If pricing is asked, say you'll share details shortly (don't give numbers)
- End with something that moves the conversation forward
- For complaints: acknowledge first, then help
- For compliments: be warm and genuine, not sycophantic"""


def detect_intent(sender_name: str, message: str, platform: str) -> dict:
    """Call Claude to classify the message intent."""
    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=400,
        system=INTENT_SYSTEM,
        messages=[{
            "role": "user",
            "content": f"Platform: {platform}\nFrom: {sender_name}\nMessage:\n{message}"
        }]
    )
    raw = response.content[0].text.strip()
    # Strip markdown code fences if present
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    return json.loads(raw.strip())


def generate_reply(
    sender_name: str,
    message: str,
    intent_data: dict,
    platform: str,
    conversation_history: list = None
) -> str:
    """Call Claude to write a personalised reply."""
    system = REPLY_SYSTEM.format(
        name=MY_NAME,
        profession=MY_PROFESSION,
        tone=MY_TONE,
        language=intent_data.get("language", "en")
    )

    context = ""
    if conversation_history:
        history_text = "\n".join(
            f"  [{m['role']}]: {m['content']}" for m in conversation_history[-4:]
        )
        context = f"\nPrevious conversation (last 4 messages):\n{history_text}\n"

    user_prompt = f"""Write a reply to this {platform} message.

Sender: {sender_name}
Their message: "{message}"
Intent: {intent_data.get('intent')}
What they want: {intent_data.get('key_ask')}
Urgency: {intent_data.get('urgency')}
Sentiment: {intent_data.get('sentiment')}
{context}
Write ONLY the reply text. No quotes. No labels. No "Sure!" opener. Just the reply."""

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=500,
        system=system,
        messages=[{"role": "user", "content": user_prompt}]
    )
    return response.content[0].text.strip()


def process_message(
    sender_name: str,
    message: str,
    platform: str,
    conversation_history: list = None
) -> AgentReply:
    """
    Master function. Takes any incoming message, returns an AgentReply.
    Used by ALL platform connectors.
    """
    # 1. Detect intent
    intent_data = detect_intent(sender_name, message, platform)

    # 2. Skip spam or bot messages
    if intent_data.get("is_spam") or intent_data.get("platform_hints", {}).get("looks_like_bot"):
        return AgentReply(
            skip=True,
            skip_reason="spam or bot",
            intent=None,
            reply_text=None,
            platform_hints=intent_data.get("platform_hints", {})
        )

    # 3. Flag for human if needed (complex complaints, legal, media)
    if intent_data.get("requires_human"):
        return AgentReply(
            skip=True,
            skip_reason="requires_human_review",
            intent=MessageIntent(**{k: intent_data[k] for k in
                                   ["intent","urgency","key_ask","language","sentiment"]}),
            reply_text=None,
            platform_hints=intent_data.get("platform_hints", {})
        )

    # 4. Generate reply
    reply_text = generate_reply(
        sender_name, message, intent_data, platform, conversation_history
    )

    return AgentReply(
        skip=False,
        skip_reason=None,
        intent=MessageIntent(
            intent=intent_data["intent"],
            urgency=intent_data["urgency"],
            key_ask=intent_data["key_ask"],
            language=intent_data["language"],
            sentiment=intent_data["sentiment"],
        ),
        reply_text=reply_text,
        platform_hints=intent_data.get("platform_hints", {})
    )
