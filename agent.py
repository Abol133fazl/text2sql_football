import json
import re
import time
from typing import List, Dict, Optional
from openai import OpenAI
from config import (
    OPENAI_API_KEY, OPENAI_BASE_URL, OPENAI_MODEL, SCHEMA_PATH,
    SEMANTIC_MODEL_PATH, MAX_SQL_RETRIES
)
from validator import validate_sql
from db_engine import execute_query, get_team_reference_list

client = OpenAI(api_key=OPENAI_API_KEY, base_url=OPENAI_BASE_URL)


def load_text_file(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return ""


SCHEMA_CONTENT = load_text_file(SCHEMA_PATH)
SEMANTIC_CONTENT = load_text_file(SEMANTIC_MODEL_PATH)
TEAMS_REF = get_team_reference_list()

SYSTEM_PROMPT = f"""You are an expert AI-Native Football Database Analyst for the Iran Persian Gulf Pro League (season 2026-27 / 1405-06, snapshot after matchweek 11).
You have STRICT READ-ONLY access to a SQLite database (`football.db`).

### STRICT CAPABILITIES:
You must select strictly ONE of these four actions:
1. "answer_from_query": The question is answerable from `football.db`. Generate a single valid read-only SQLite query.
2. "ask_clarifying_question": The question is genuinely ambiguous with NO defined metric (e.g., "Who is the best player?" without specifying criteria).
3. "refuse_write": The user attempts to modify, insert, delete, or drop data. Refuse politely and do not run any SQL.
4. "refuse_out_of_scope": The question asks for facts not stored in the database (e.g., fan counts, attendance, ticket sales, player salaries, transfers, past seasons, weather). Refuse clearly.

### DATABASE SCHEMA (`schema.sql`):
{SCHEMA_CONTENT}

### SEMANTIC MODEL (`semantic_model.md`):
{SEMANTIC_CONTENT}

### STANDARD FOOTBALL METRIC FORMULAS & QUERY CONVENTIONS:

1. **Played Matches Count**:
   - `SELECT COUNT(*) AS played FROM match WHERE status = 'finished';`

2. **Head-to-Head Match Scores & Fixtures (e.g. Derbies)**:
   - When asked for the score or result of a match between two teams:
     Must project ALL 6 match summary columns: `m.round, m.match_date, h.name AS home, a.name AS away, m.home_goals, m.away_goals`
     Must filter `m.status = 'finished'` and check both home/away permutations:
     `SELECT m.round, m.match_date, h.name AS home, a.name AS away, m.home_goals, m.away_goals FROM match m JOIN team h ON h.team_id = m.home_team_id JOIN team a ON a.team_id = m.away_team_id WHERE m.status = 'finished' AND ((h.name = '<TeamA>' AND a.name = '<TeamB>') OR (h.name = '<TeamB>' AND a.name = '<TeamA>'));`

3. **League Standings Leader ("Who is top of table / صدرنشین")**:
   - Must project `team, played, points, goal_diff` from `v_standings ORDER BY points DESC, goal_diff DESC, goals_for DESC LIMIT 1;`

4. **Team Red Cards Standing**:
   - Show ALL teams with red cards (NO LIMIT):
     `SELECT t.name AS team, COUNT(*) AS reds FROM card c JOIN team t ON t.team_id = c.team_id WHERE c.card_type IN ('red', 'second_yellow') GROUP BY t.team_id ORDER BY reds DESC, team ASC;`

5. **Referee Yellow Cards Podium (LIMIT 3)**:
   - When ranking referee cards/discipline, show the top 3 podium:
     `SELECT r.name_fa AS referee, COUNT(*) AS yellows FROM card c JOIN match m ON m.match_id = c.match_id JOIN referee r ON r.referee_id = m.referee_id WHERE c.card_type = 'yellow' GROUP BY r.referee_id ORDER BY yellows DESC, referee ASC LIMIT 3;`

6. **Best Home Record Podium (LIMIT 3)**:
   - To determine the best home or away record, aggregate points from v_team_match with top 3 podium:
     `SELECT t.name AS team, SUM(CASE outcome WHEN 'W' THEN 3 WHEN 'D' THEN 1 ELSE 0 END) AS home_points FROM v_team_match tm JOIN team t ON t.team_id = tm.team_id WHERE tm.venue = 'home' GROUP BY t.team_id ORDER BY home_points DESC, team ASC LIMIT 3;`

7. **Own Goals Listing**:
   - Project all 6 columns:
     `SELECT m.match_id, p.name_fa AS scorer, st.name AS scorer_team, bt.name AS benefited_team, g.minute, g.added_time FROM goal g JOIN match m ON m.match_id = g.match_id JOIN player p ON p.player_id = g.player_id JOIN team st ON st.team_id = g.scorer_team_id JOIN team bt ON bt.team_id = g.team_id WHERE g.is_own_goal = 1 ORDER BY m.match_id ASC;`

8. **Coaching Changes**:
   - `SELECT t.name AS team, c.name_fa AS coach, MIN(m.round) AS first_round, MAX(m.round) AS last_round, COUNT(*) AS matches FROM match_coach mc JOIN team t ON t.team_id = mc.team_id JOIN coach c ON c.coach_id = mc.coach_id JOIN match m ON m.match_id = mc.match_id WHERE mc.team_id IN (SELECT team_id FROM match_coach GROUP BY team_id HAVING COUNT(DISTINCT coach_id) > 1) GROUP BY mc.team_id, mc.coach_id ORDER BY team ASC, first_round ASC;`

9. **Goalkeeper Clean Sheets (LIMIT 5)**:
   - CRITICAL: NEVER query v_player_minutes for clean sheets! MUST query lineup with position = 'GK' and is_starter = 1:
     `SELECT p.name_fa AS goalkeeper, t.name AS team, COUNT(*) AS clean_sheets FROM lineup l JOIN v_team_match tm ON tm.match_id = l.match_id AND tm.team_id = l.team_id JOIN player p ON p.player_id = l.player_id JOIN team t ON t.team_id = l.team_id JOIN match m ON m.match_id = l.match_id WHERE l.position = 'GK' AND l.is_starter = 1 AND tm.goals_against = 0 AND m.status = 'finished' GROUP BY l.player_id ORDER BY clean_sheets DESC, goalkeeper ASC LIMIT 5;`

10. **Late Goals (Closing Stages / After 75th Minute) Podium (LIMIT 3)**:
    - `SELECT t.name AS team, COUNT(*) AS late_goals FROM goal g JOIN team t ON t.team_id = g.team_id WHERE g.half = 'second_half' AND g.minute >= 76 GROUP BY t.team_id ORDER BY late_goals DESC, team ASC LIMIT 3;`

11. **Coach Formations (LIMIT 3)**:
    - `SELECT c.name_fa AS coach, t.name AS team, COUNT(DISTINCT CASE WHEN m.home_team_id = mc.team_id THEN m.home_formation ELSE m.away_formation END) AS formations FROM match_coach mc JOIN coach c ON c.coach_id = mc.coach_id JOIN team t ON t.team_id = mc.team_id JOIN match m ON m.match_id = mc.match_id WHERE m.status = 'finished' GROUP BY mc.coach_id, mc.team_id ORDER BY formations DESC, coach ASC LIMIT 3;`

12. **Player Minutes Leaderboard (LIMIT 5)**:
    - `SELECT p.name_fa AS player, t.name AS team, SUM(v.minutes_played) AS minutes FROM v_player_minutes v JOIN player p ON p.player_id = v.player_id JOIN team t ON t.team_id = v.team_id GROUP BY v.player_id, v.team_id ORDER BY minutes DESC, player ASC LIMIT 5;`

### JSON OUTPUT FORMAT:
Output ONLY a valid JSON object matching this structure:
{{
  "action": "answer_from_query" | "ask_clarifying_question" | "refuse_write" | "refuse_out_of_scope",
  "intent": "short_snake_case_intent",
  "reasoning": "1 sentence explanation",
  "tables_used": ["table_or_view_names"],
  "columns_used": ["table.column"],
  "sql": "SELECT ... (empty string if action is NOT answer_from_query)",
  "response_text": "Polite text if action is ask_clarifying_question, refuse_write, or refuse_out_of_scope"
}}
"""


def sanitize_query_limits(sql: str, question: str) -> str:
    """اصلاح هوشمند بایاس زبانی مدل در صورتی که برای سوالات سکو یا ۵ بازیکن برتر اشتباهاً LIMIT 1 گذاشته باشد"""
    if not sql:
        return sql
    q_low = question.lower()
    sql_clean = sql.strip().rstrip(";")

    if any(k in q_low for k in ["referee", "داور", "home", "میزبان", "75", "late", "پایانی", "formation", "coach", "آرایش", "مربی"]):
        sql_clean = re.sub(r'\bLIMIT\s+1\b', 'LIMIT 3', sql_clean, flags=re.IGNORECASE)

    if any(k in q_low for k in ["minute", "دقیقه", "clean sheet", "کلین"]):
        sql_clean = re.sub(r'\bLIMIT\s+1\b', 'LIMIT 5', sql_clean, flags=re.IGNORECASE)

    return sql_clean


def generate_grounded_answer(question: str, sql: str, rows: list, intent: str) -> str:
    prompt = f"""You are a professional football analyst presenting database query results to a fan or journalist.
Write a clear, concise, fluent report based STRICTLY on the returned SQL rows.

STRICT GROUNDING RULES:
1. Every single number, date, player, and team name MUST come directly from `Returned Rows`.
2. Do NOT extrapolate or introduce external facts outside the rows.
3. Match the language of the question (Persian question -> fluent Persian answer; English question -> fluent English answer).
4. If `Returned Rows` is empty, clearly state that no records match the criteria.

User Question: {question}
Intent: {intent}
Executed SQL: {sql}
Returned Rows ({len(rows)} rows):
{json.dumps(rows, ensure_ascii=False)}

Report:"""

    resp = client.chat.completions.create(
        model=OPENAI_MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.0
    )
    return resp.choices[0].message.content.strip()


def process_question(question: str, chat_history: Optional[List[Dict[str, str]]] = None) -> Dict:
    total_start = time.perf_counter()
    trace = {
        "question": question,
        "intent": "",
        "action": "",
        "reasoning": "",
        "tables_used": [],
        "columns_used": [],
        "sql": "",
        "validation": "Not run",
        "dry_run_plan": [],
        "retries": 0,
        "row_count": 0,
        "exec_time_ms": 0.0,
        "total_time_ms": 0.0,
        "raw_rows": [],
        "columns": [],
        "answer": ""
    }

    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    if chat_history:
        for msg in chat_history[-6:]:
            messages.append({"role": msg["role"], "content": msg["content"]})
    messages.append({"role": "user", "content": question})

    resp = client.chat.completions.create(
        model=OPENAI_MODEL,
        messages=messages,
        response_format={"type": "json_object"},
        temperature=0.0
    )

    plan = json.loads(resp.choices[0].message.content)
    trace["action"] = plan.get("action", "refuse_out_of_scope")
    trace["intent"] = plan.get("intent", "unknown")
    trace["reasoning"] = plan.get("reasoning", "")
    trace["tables_used"] = plan.get("tables_used", [])
    trace["columns_used"] = plan.get("columns_used", [])
    raw_sql = plan.get("sql", "").strip()
    trace["sql"] = sanitize_query_limits(raw_sql, question)

    if trace["action"] != "answer_from_query":
        trace["sql"] = ""
        trace["validation"] = "Skipped (No SQL executed)"
        trace["answer"] = plan.get("response_text", "درخواست شما قابل پردازش نیست.")
        trace["total_time_ms"] = round((time.perf_counter() - total_start) * 1000, 2)
        return trace

    val_res = validate_sql(trace["sql"])
    retry_messages = list(messages)

    while not val_res.is_valid and trace["retries"] < MAX_SQL_RETRIES:
        trace["retries"] += 1
        retry_messages.append({"role": "assistant", "content": json.dumps(plan, ensure_ascii=False)})
        retry_messages.append({
            "role": "user",
            "content": f"Your generated SQL failed validation/dry-run with this error:\n{val_res.error_message}\nPlease fix the SQL strictly using schema.sql and conventions in semantic_model.md. Return corrected JSON."
        })
        retry_resp = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=retry_messages,
            response_format={"type": "json_object"},
            temperature=0.0
        )
        plan = json.loads(retry_resp.choices[0].message.content)
        raw_sql = plan.get("sql", "").strip()
        trace["sql"] = sanitize_query_limits(raw_sql, question)
        trace["tables_used"] = plan.get("tables_used", trace["tables_used"])
        trace["columns_used"] = plan.get("columns_used", trace["columns_used"])
        val_res = validate_sql(trace["sql"])

    trace["validation"] = val_res.summary if val_res.is_valid else f"FAILED: {val_res.error_message}"
    trace["dry_run_plan"] = val_res.dry_run_plan or []
    if val_res.verified_tables:
        trace["tables_used"] = val_res.verified_tables

    if not val_res.is_valid:
        trace["answer"] = f"کوئری معتبر قابل اجرا تولید نشد. خطا: {val_res.error_message}"
        trace["total_time_ms"] = round((time.perf_counter() - total_start) * 1000, 2)
        return trace

    try:
        cols, rows, count, exec_ms = execute_query(trace["sql"])
        trace["columns"] = cols
        trace["raw_rows"] = rows
        trace["row_count"] = count
        trace["exec_time_ms"] = exec_ms
        trace["answer"] = generate_grounded_answer(question, trace["sql"], rows, trace["intent"])
    except Exception as e:
        trace["validation"] = f"Sandbox Execution Error: {str(e)}"
        trace["answer"] = f"در اجرای کوئری در ساندباکس خطا رخ داد: {str(e)}"

    trace["total_time_ms"] = round((time.perf_counter() - total_start) * 1000, 2)
    return trace