import json
import logging
import re
from pathlib import Path

import chainlit as cl
import litellm
from dotenv import load_dotenv
from langsmith import traceable

import movie_functions
import prompts

_logger = logging.getLogger(__name__)
load_dotenv(override=True)

litellm.success_callback = ["langsmith"]
# litellm.set_verbose=True


MAX_FUNCTION_CALLS_PER_MESSAGE = 4
# Choose one of these model configurations by uncommenting it:

# OpenAI GPT-4
OPEN_AI_MODEL = "openai/gpt-4o"

# Anthropic Claude
CLAUDE_MODEL = "claude-3-5-sonnet-20241022"

# Fireworks Qwen
FIREWORKS_MODEL = "fireworks_ai/accounts/fireworks/models/qwen2p5-coder-32b-instruct"

CURRENT_MODEL = CLAUDE_MODEL  # Change this to the model you want to use
# see: https://docs.anthropic.com/en/api/messages#body-messages
SUPPORT_SYSTEM_MESSAGE = CURRENT_MODEL != CLAUDE_MODEL


def get_system_prompt():
    example_function_call = {
        "name": "get_now_playing",
        "arguments": {},
    }
    example_function_call_get_showtimes = {
        "name": "get_showtimes",
        "arguments": {"title": "The Batman", "location": "Los Angeles"},
    }
    # We don't really need is as JSON, but this is a way to validate the JSON is valid
    functions_defs = json.loads(Path("./functions_defs.json.json").read_text())
    # validate functions, fail fast if there is an issue
    missing = []
    for function_name in functions_defs.keys():
        if not getattr(movie_functions, function_name, None):
            missing.append(function_name)
    if missing:
        raise ValueError(
            f"Missing functions in 'movie_functions' module : {', '.join(missing)}"
        )
    # temporary, testing w/o confirmation first
    del functions_defs["confirm_ticket_purchase"]

    return prompts.SYSTEM_PROMPT_V7.format(
        functions_defs=json.dumps(functions_defs, indent=2),
        example_function_call=json.dumps(example_function_call, indent=2),
        example_function_call_get_showtimes=json.dumps(
            example_function_call_get_showtimes, indent=2
        ),
    )


def extract_tag_content(text: str, tag_name: str) -> str | None:
    pattern = f"<{tag_name}>(.*?)</{tag_name}>"
    match = re.search(pattern, text, re.DOTALL)
    return match.group(1) if match else None


def extract_json_tag_content(text: str, tag_name: str) -> dict | list | None:
    content = extract_tag_content(text, tag_name)
    return json.loads(content) if content else None


@traceable
@cl.on_chat_start
def on_chat_start():
    message_history = [{"role": "system", "content": get_system_prompt()}]
    cl.user_session.set("message_history", message_history)


async def llm_call(role: str, message_content: str, temperature=0.2) -> str:
    message_history = cl.user_session.get("message_history", [])
    message_history.append({"role": role, "content": message_content})
    _logger.info(
        f"LLM call: {role} - {message_content[:30]}... ({len(message_content)}) - history: {len(message_history)}"
    )
    response_message = cl.Message(content="")
    await response_message.send()

    response = litellm.completion(
        model=CURRENT_MODEL,
        supports_system_message=SUPPORT_SYSTEM_MESSAGE,
        messages=message_history,
        stream=True,
        temperature=temperature,
        max_tokens=1000,
    )

    for part in response:
        if token := part.choices[0].delta.content or "":
            await response_message.stream_token(token)
    await response_message.update()
    _logger.info(
        f"LLM response: {response_message.content[:30]}.... ({len(response_message.content)})"
    )
    message_history.append({"role": "assistant", "content": response_message.content})
    cl.user_session.set("message_history", message_history)
    return response_message.content


def call_api(fc: dict) -> dict:
    function_name = fc.get("name")
    function_args = fc.get("arguments")
    _logger.info(f"calling: {function_name} w/ {function_args}")
    func = getattr(movie_functions, function_name, None)
    if not func:
        raise ValueError(f"Function {function_name} not found")
    return func(**function_args)


@cl.on_message
@traceable
async def on_message(message: cl.Message):
    remaining_calls = MAX_FUNCTION_CALLS_PER_MESSAGE
    response_content = await llm_call("user", message.content)
    while remaining_calls > 0:
        fc = extract_json_tag_content(response_content, "function_call")
        if not fc:
            break
        api_response = call_api(fc)
        _logger.info(
            f"API {fc} - {api_response[:50]}... ({len(api_response)}) - remaining calls: {remaining_calls}"
        )
        if not api_response:
            break
        remaining_calls -= 1
        response_content = await llm_call(
            "system", f"<function_response>{api_response}</function_response>"
        )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    cl.main()
