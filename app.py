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


@traceable
@cl.on_chat_start
def on_chat_start():
    message_history = [{"role": "system", "content": prompts.SYSTEM_PROMPT_V4}]
    cl.user_session.set("message_history", message_history)


async def llm_call(role: str, message_content: str, message_history: list) -> str:
    message_history.append({"role": role, "content": message_content})
    print(f"LLM call: {role} - {message_content[:30]}... ({len(message_content)})")
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
    print(f"LLM response: {response_message.content[:30]}.... ({len(response_message.content)})")
    message_history.append({"role": "assistant", "content": response_message.content})
    return response_message.content


async def llm_call_json(
    role: str, message_content: str, message_history: list
) -> dict | list:
    response_content = await llm_call(role, message_content, message_history)
    try:
        return json.loads(response_content)
    except json.JSONDecodeError:
        print("not a JSON response")
        return {"content": response_content}


def call_api(fc: dict) -> dict:
    function_name = fc.get("name")
    print(f"calling: {function_name}")
    if function_name == "get_now_playing":
        return get_now_playing_movies()
    elif function_name == "get_showtimes":
        return get_showtimes()
    return None


@cl.on_message
@traceable
async def on_message(message: cl.Message):
    message_history = cl.user_session.get("message_history", [])
    response_json = await llm_call_json("user", message.content, message_history)
    print(f"JSON: '{response_json}'")
    fc = response_json.get("function_call")
    if fc:
        api_response = call_api(fc)
        if api_response:
            await llm_call("system", api_response, message_history)
    else:
        print("not a function call")

    cl.user_session.set("message_history", message_history)


if __name__ == "__main__":
    cl.main()
