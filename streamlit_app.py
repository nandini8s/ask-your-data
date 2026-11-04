"""Streamlit UI for the existing campus electricity agent."""

import streamlit as st

from loop import run_loop


def _friendly_error(error):
    if error == "missing_api_key":
        return "The agent is not configured. Add the Gemini API key to the local .env file."
    if error == "rate_limited":
        return "The model API rate limit was reached. Please wait and try again."
    message = str(error).lower()
    if "timeout" in message or "timed out" in message:
        return "The request timed out. Please try again."
    if "connection" in message:
        return "Could not connect to the model API. Check the connection and try again."
    return "The agent could not complete this request. Please try again later."


st.set_page_config(page_title="Campus Electricity AI Agent")
st.title("Campus Electricity AI Agent")
st.write("Ask questions about campus electricity consumption.")

with st.form("agent_question_form"):
    question_input = st.text_area("Your question")
    submitted = st.form_submit_button("Ask Agent")

if submitted:
    question = question_input.strip()
    if not question:
        st.session_state.pop("agent_question", None)
        st.session_state.pop("agent_result", None)
        st.warning("Enter a question before submitting.")
    else:
        st.session_state["agent_question"] = question
        st.session_state["agent_result"] = None
        try:
            with st.spinner("Asking the agent..."):
                st.session_state["agent_result"] = run_loop(question)
        except SystemExit as error:
            st.session_state["agent_result"] = {
                "answer": "",
                "error": (
                    "missing_api_key"
                    if str(error) == "Set GEMINI_API_KEY in your environment or .env file."
                    else "unexpected_error"
                ),
                "tool_calls": [],
                "turns": 0,
            }
        except Exception:
            st.session_state["agent_result"] = {
                "answer": "",
                "error": "unexpected_error",
                "tool_calls": [],
                "turns": 0,
            }

saved_question = st.session_state.get("agent_question")
result = st.session_state.get("agent_result")

if saved_question and result is not None:
    st.subheader("Your question")
    st.write(saved_question)

    tool_calls = result.get("tool_calls") or []
    if isinstance(tool_calls, list):
        st.caption(f"Executed tool calls: {len(tool_calls)}")

    error = result.get("error")
    if error is not None:
        st.error(_friendly_error(error))
    else:
        st.subheader("Answer")
        st.markdown(result.get("answer") or "The agent returned no answer.")

    with st.expander("View executed SQL"):
        sql_queries = [
            call.get("arguments", {}).get("query")
            for call in tool_calls
            if isinstance(call, dict)
            and call.get("name") == "run_sql"
            and isinstance(call.get("arguments"), dict)
            and isinstance(call["arguments"].get("query"), str)
        ]
        if not sql_queries:
            st.info("No SQL query was executed for this question.")
        else:
            for index, query in enumerate(sql_queries, start=1):
                if len(sql_queries) > 1:
                    st.markdown(f"**SQL query {index}**")
                st.code(query, language="sql")
