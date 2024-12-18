import json

import chainlit as cl
import litellm
from dotenv import load_dotenv

from movie_functions import get_now_playing_movies, get_showtimes

load_dotenv(override=True)

from langsmith import traceable

litellm.success_callback = ["langsmith"]

import prompts

# Choose one of these model configurations by uncommenting it:

# OpenAI GPT-4
OPEN_AI_MODEL = "openai/gpt-4o"

# Anthropic Claude
CLAUDE_MODEL = "claude-3-5-sonnet-20241022"

# Fireworks Qwen
FIREWORKS_MODEL = "fireworks_ai/accounts/fireworks/models/qwen2p5-coder-32b-instruct"

CURRENT_MODEL = CLAUDE_MODEL  # Change this to the model you want to use


def extract_tag_content(text: str, tag_name: str) -> str | None:
    """
    Extract content between XML-style tags.

    Args:
        text: The text containing the tags
        tag_name: Name of the tag to find

    Returns:
        String content between tags if found, None if not found

    Example:
        >>> text = "before <foo>content</foo> after"
        >>> extract_tag_content(text, "foo")
        'content'
    """
    import re

    pattern = f"<{tag_name}>(.*?)</{tag_name}>"
    match = re.search(pattern, text, re.DOTALL)
    return match.group(1) if match else None


@traceable
@cl.on_chat_start
def on_chat_start():
    message_history = [{"role": "system", "content": prompts.SYSTEM_PROMPT}]
    cl.user_session.set("message_history", message_history)


async def llm_call(role, message_content, message_history):
    message_history.append({"role": role, "content": message_content})
    response_message = cl.Message(content="")
    await response_message.send()

    response = litellm.completion(
        model=CURRENT_MODEL,
        messages=message_history,
        stream=True,
        temperature=0.2,
        max_tokens=1000,
    )

    for part in response:
        if token := part.choices[0].delta.content or "":
            await response_message.stream_token(token)
    await response_message.update()
    message_history.append({"role": "assistant", "content": response_message.content})


@cl.on_message
@traceable
async def on_message(message: cl.Message):
    message_history = cl.user_session.get("message_history", [])
    await llm_call("user", message.content, message_history)
    cl.user_session.set("message_history", message_history)


if __name__ == "__main__":
    cl.main()
