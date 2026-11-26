import os
import re
import json
import streamlit as st
import pandas as pd
import plotly.express as px
from agent import process_question, SCHEMA_CONTENT, SEMANTIC_CONTENT
from db_engine import get_real_schema

st.set_page_config(
    page_title="Iran League AI Analyst | Sharif Text-to-SQL",
    page_icon="⚽",
    layout="wide",
    initial_sidebar_state="expanded"
)

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Vazirmatn:wght@400;500;700&display=swap');

.rtl-box {
    font-family: 'Vazirmatn', sans-serif;
    direction: rtl;
    text-align: right;
    line-height: 1.85;
    font-size: 15px;
    background-color: #f4f8ff;
    color: #111827;
    padding: 14px 18px;
    border-radius: 10px;
    border-right: 4px solid #2563eb;
    margin-bottom: 10px;
}
.ltr-box {
    direction: ltr;
    text-align: left;
    line-height: 1.7;
    font-size: 15px;
    background-color: #f4f8ff;
    color: #111827;
    padding: 14px 18px;
    border-radius: 10px;
    border-left: 4px solid #2563eb;
    margin-bottom: 10px;
}
.badge {
    display: inline-block;
    padding: 3px 10px;
    border-radius: 999px;
    font-size: 12px;
    font-weight: 600;
    margin-bottom: 8px;
}
.badge-green { background-color: #dcfce7; color: #166534; }
.badge-orange { background-color: #ffedd5; color: #9a3412; }
.badge-red { background-color: #fee2e2; color: #991b1b; }
</style>
""", unsafe_allow_html=True)


def is_persian(text: str) -> bool:
    return bool(re.search(r'[\u0600-\u06FF]', text or ""))


def render_bilingual_text(text: str):
    css_class = "rtl-box" if is_persian(text) else "ltr-box"
    safe_text = text.replace("\n", "<br>")
    st.markdown(f'<div class="{css_class}">{safe_text}</div>', unsafe_allow_html=True)


def render_badge(action: str):
    mapping = {
        "answer_from_query": ("badge-green", "✓ answer_from_query"),
        "ask_clarifying_question": ("badge-orange", "? ask_clarifying_question"),
        "refuse_write": ("badge-red", "⛔ refuse_write"),
        "refuse_out_of_scope": ("badge-red", "⛔ refuse_out_of_scope"),
    }
    cls, label = mapping.get(action, ("badge-orange", action))
    st.markdown(f'<span class="badge {cls}">Capability: {label}</span>', unsafe_allow_html=True)


def render_trace_panel(trace: dict, key_prefix: str):
    render_badge(trace["action"])
    render_bilingual_text(trace["answer"])

    if trace["sql"]:
        st.code(trace["sql"], language="sql")

    with st.expander("🔍 Explainability, Trace & Analytics", expanded=False):
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Intent", trace["intent"])
        c2.metric("Rows Returned", trace["row_count"])
        c3.metric("DB Latency", f"{trace['exec_time_ms']} ms")
        c4.metric("Self-Correction Retries", trace["retries"])

        st.markdown(f"**Reasoning:** {trace.get('reasoning', '-')}")
        st.markdown(f"**Tables:** `{', '.join(trace['tables_used']) or 'None'}`")
        st.markdown(f"**Columns:** `{', '.join(trace['columns_used']) or 'None'}`")
        st.markdown(f"**Validation:** `{trace['validation']}`")

        if trace.get("dry_run_plan"):
            st.caption("SQLite EXPLAIN QUERY PLAN:")
            st.code("\n".join(trace["dry_run_plan"]), language="text")

        formal_trace = f"""Question: {trace['question']}
Intent: {trace['intent']}
Tables: {', '.join(trace['columns_used']) if trace['columns_used'] else ', '.join(trace['tables_used'])}
SQL: {trace['sql'] or 'None (Refused/Clarified)'}
Validation: {trace['validation']} rows: {trace['row_count']}
Capability: {trace['action']}
Answer: {trace['answer']}"""
        st.text_area("Copyable Formal Trace (Assignment Format):", formal_trace, height=150, key=f"trace_{key_prefix}")

    if trace.get("raw_rows"):
        df = pd.DataFrame(trace["raw_rows"])
        with st.expander(f"📊 Data Table & Visual Analytics ({len(df)} rows)", expanded=True):
            col_tbl, col_viz = st.columns([1.1, 1])
            with col_tbl:
                st.dataframe(df, use_container_width=True)
                csv_bytes = df.to_csv(index=False).encode("utf-8-sig")
                st.download_button(
                    "⬇️ Download Results (CSV)",
                    data=csv_bytes,
                    file_name="query_results.csv",
                    mime="text/csv",
                    key=f"dl_{key_prefix}"
                )

            with col_viz:
                num_cols = [c for c in df.select_dtypes(include=["number"]).columns if not c.lower().endswith("_id") and c.lower() != "id"]
                cat_cols = df.select_dtypes(include=["object", "string"]).columns.tolist()

                if num_cols and cat_cols and len(df) > 1:
                    x_col = st.selectbox("Label Axis", cat_cols, key=f"x_{key_prefix}")
                    y_col = st.selectbox("Value Axis", num_cols, key=f"y_{key_prefix}")
                    fig = px.bar(df.head(20), x=x_col, y=y_col, text_auto=True, title=f"{y_col} by {x_col}")
                    fig.update_layout(margin=dict(l=10, r=10, t=40, b=10), height=320)
                    st.plotly_chart(fig, use_container_width=True)
                else:
                    st.info("Visual chart is automatically generated for multi-row numeric queries.")


if "chat_history" not in st.session_state:
    st.session_state.chat_history = []

with st.sidebar:
    st.title("⚽ AI Football Analyst")
    st.caption("Sharif University · AI-Native Systems Design")

    st.divider()
    st.subheader("🛡️ Active Guardrails")
    st.markdown("""
    - **DB Mode:** `file:football.db?mode=ro`
    - **AST Validator:** `sqlglot` + `sqlparse`
    - **Dry-Run:** `EXPLAIN QUERY PLAN`
    - **Execution Timeout:** `3.0s` | **Row Cap:** `100`
    """)

    st.divider()
    st.subheader("⚡ Quick Test Prompts")
    presets = [
        ("🏆 League Standings", "جدول رده‌بندی لیگ برتر را نشان بده"),
        ("🏠 Team Home Record", "How did Tractor do at home this season?"),
        ("⚽ Top Scorers", "برترین گلزنان لیگ تا اینجای فصل چه کسانی هستند؟"),
        ("❓ Ambiguous (Clarify)", "Who is the best player?"),
        ("🚫 Out-of-Scope Trap", "Which team has the most fans?"),
        ("⛔ Write Attack Trap", "Delete all cancelled matches from the database")
    ]
    for label, prompt_txt in presets:
        if st.button(label, use_container_width=True):
            st.session_state["pending_prompt"] = prompt_txt

    st.divider()
    if st.button("🗑️ Clear Conversation", use_container_width=True):
        st.session_state.chat_history = []
        st.rerun()

tab_chat, tab_schema, tab_eval = st.tabs(["💬 AI Analyst Workspace", "🗄️ Schema & Semantic Explorer", "📋 Evaluation Report"])

with tab_chat:
    st.markdown("### Ask about Iran Persian Gulf Pro League (1405-06)")
    st.caption("Ask in English or Persian. Ambiguous questions trigger a follow-up clarification.")

    for idx, msg in enumerate(st.session_state.chat_history):
        if msg["role"] == "user":
            with st.chat_message("user"):
                render_bilingual_text(msg["content"])
        else:
            with st.chat_message("assistant"):
                render_trace_panel(msg["trace"], key_prefix=f"hist_{idx}")

    user_input = st.chat_input("سوال خود را بنویسید (فارسی یا انگلیسی)...")
    if "pending_prompt" in st.session_state:
        user_input = st.session_state.pop("pending_prompt")

    if user_input:
        with st.chat_message("user"):
            render_bilingual_text(user_input)

        llm_history = [{"role": m["role"], "content": m["content"]} for m in st.session_state.chat_history]

        with st.chat_message("assistant"):
            with st.spinner("Semantic routing → SQL generation → AST validation → Dry-run → Sandbox..."):
                trace = process_question(user_input, chat_history=llm_history)
            render_trace_panel(trace, key_prefix=f"live_{len(st.session_state.chat_history)}")

        st.session_state.chat_history.append({"role": "user", "content": user_input})
        st.session_state.chat_history.append({"role": "assistant", "content": trace["answer"], "trace": trace})

with tab_schema:
    st.subheader("Live Database Schema & Semantic Layer")
    real_schema = get_real_schema()
    c1, c2 = st.columns([1, 1])
    with c1:
        st.markdown("#### Tables & Views in `football.db`")
        for tbl, cols in real_schema.items():
            with st.expander(f"📁 `{tbl}` ({len(cols)} columns)"):
                st.write(", ".join([f"`{c}`" for c in cols]))
        st.markdown("#### Raw `schema.sql`")
        st.code(SCHEMA_CONTENT, language="sql")
    with c2:
        st.markdown("#### Semantic Model (`semantic_model.md`)")
        st.markdown(SEMANTIC_CONTENT)

with tab_eval:
    st.subheader("17-Question Evaluation Benchmark")
    if os.path.exists("eval_report.md"):
        with open("eval_report.md", "r", encoding="utf-8") as f:
            st.markdown(f.read())
    else:
        st.info("Run `python run_eval.py` in your terminal to generate `eval_report.md` and inspect all 17 test cases here.")