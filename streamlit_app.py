"""Streamlit UI for the existing campus electricity agent."""

import logging

import streamlit as st

from loop import run_loop

logger = logging.getLogger(__name__)
MAX_HISTORY_MESSAGES = 10
MAX_HISTORY_MESSAGE_CHARS = 2000


def _friendly_error(error):
    if error == "missing_api_key":
        return "The agent is not configured. Add the Gemini API key to the local .env file."
    if error == "rate_limited":
        return "The model API rate limit was reached. Please wait and try again."
    if error == "api_timeout":
        return "The request timed out. Please try again."
    if error == "api_connection_error":
        return "Could not connect to the model API. Check the connection and try again."
    if error == "invalid_model_response":
        return "The model returned an invalid response. Please try again."
    if error == "max_turns_reached":
        return "The agent reached its tool-call limit before completing this answer. Try a more specific question."
    message = str(error).lower()
    if "timeout" in message or "timed out" in message:
        return "The request timed out. Please try again."
    if "connection" in message:
        return "Could not connect to the model API. Check the connection and try again."
    return "The agent could not complete this request. Please try again later."


def _render_tool_trace(result, key):
    tool_calls = result.get("tool_calls") or []
    st.caption(f"Executed tool calls: {len(tool_calls)}")
    with st.expander("View tool trace", key=key):
        if not tool_calls:
            st.info("No tool calls were executed for this question.")
        for index, call in enumerate(tool_calls, start=1):
            if not isinstance(call, dict):
                continue
            st.markdown(f"**{index}. {call.get('name', 'Tool')}**")
            arguments = call.get("arguments")
            if arguments:
                st.json(arguments)
            if call.get("result") is not None:
                st.code(str(call["result"]), language="text")


st.set_page_config(page_title="Campus Electricity AI Agent")
st.title("Campus Electricity AI Agent")
st.write("Ask questions about campus electricity consumption.")

if "conversation" not in st.session_state:
    st.session_state.conversation = []

if st.button("New Chat"):
    st.session_state.conversation = []
    st.rerun()

question = st.chat_input("Ask about campus electricity consumption...")

if question:
    history = []
    for turn in st.session_state.conversation:
        history.append({
            "role": "user",
            "content": turn["question"][:MAX_HISTORY_MESSAGE_CHARS],
        })
        if turn["result"].get("answer"):
            history.append({
                "role": "assistant",
                "content": turn["result"]["answer"][:MAX_HISTORY_MESSAGE_CHARS],
            })
    history = history[-MAX_HISTORY_MESSAGES:]
    try:
        with st.spinner("Asking the agent..."):
            result = run_loop(question, conversation_history=history)
    except SystemExit as error:
        result = {
            "answer": "",
            "error": (
                "missing_api_key"
                if str(error) == "Set GEMINI_API_KEY in your environment or .env file."
                else "unexpected_error"
            ),
            "tool_calls": [],
            "turns": 0,
        }
    except Exception as error:
        logger.exception("Unexpected Streamlit agent failure (%s)", type(error).__name__)
        result = {"answer": "", "error": "unexpected_error", "tool_calls": [], "turns": 0}
    st.session_state.conversation.append({"question": question, "result": result})

for index, turn in enumerate(st.session_state.conversation):
    st.chat_message("user").write(turn["question"])
    with st.chat_message("assistant"):
        result = turn["result"]
        if result.get("error") is not None:
            st.error(_friendly_error(result["error"]))
        else:
            st.markdown(result.get("answer") or "The agent returned no answer.")
        _render_tool_trace(result, key=f"tool_trace_{index}")
