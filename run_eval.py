import argparse
import json
from collections import Counter
import pandas as pd
from config import EVAL_PATH
from agent import process_question


def normalize_value(v):
    if v is None:
        return None
    if isinstance(v, bool):
        return int(v)
    if isinstance(v, (int, float)):
        return int(v) if float(v).is_integer() else round(float(v), 3)
    if isinstance(v, str):
        return v.strip()
    return str(v).strip()


def row_to_counter(row) -> Counter:
    """تبدیل یک ردیف (dict یا list) به چندمجموعه مقادیر بدون وابستگی به نام یا ترتیب ستون"""
    if isinstance(row, dict):
        vals = [normalize_value(v) for v in row.values()]
    elif isinstance(row, (list, tuple)):
        vals = [normalize_value(v) for v in row]
    else:
        vals = [normalize_value(row)]
    return Counter(vals)


def is_ranking_question(q_text: str, item: dict) -> bool:
    if item.get("ordered") is True:
        return True
    q_low = q_text.lower()
    keywords = [
        "top", "most", "least", "highest", "lowest", "ranking", "standings", "table", "first", "last",
        "برترین", "بیشترین", "کمترین", "جدول", "رتبه", "صدرنشین", "اول", "آخر"
    ]
    return any(k in q_low for k in keywords)


def rows_match(actual_rows: list, expected_rows: list, ordered: bool):
    if len(actual_rows) != len(expected_rows):
        return False, f"Row count mismatch: got {len(actual_rows)}, expected {len(expected_rows)}"

    actual_counters = [row_to_counter(r) for r in actual_rows]
    expected_counters = [row_to_counter(r) for r in expected_rows]

    if ordered:
        if actual_counters == expected_counters:
            return True, "Exact ordered match"
        if all(all(exp_c[k] <= act_c[k] for k in exp_c) for act_c, exp_c in zip(actual_counters, expected_counters)):
            return False, "Values match partially, but column projection differs from expected_rows"
        return False, f"Row order or values mismatch. Got {actual_rows[:2]}, expected {expected_rows[:2]}"
    else:
        unmatched = list(expected_counters)
        for act in actual_counters:
            if act in unmatched:
                unmatched.remove(act)
            else:
                return False, f"Row mismatch. Unexpected row: {dict(act)}"
        return True, "Exact unordered match"


def run_evaluations(lang: str = "en"):
    with open(EVAL_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)

    questions = data.get("questions", data) if isinstance(data, dict) else data
    results = []
    pass_count = 0

    langs_to_run = ["en", "fa"] if lang == "both" else [lang]
    total_runs = len(questions) * len(langs_to_run)
    print(f"🚀 Running evaluation on {len(questions)} questions (lang={lang}, total={total_runs} runs)...\n")

    run_idx = 0
    for item in questions:
        q_id = str(item.get("id", ""))
        is_trap = (
            item.get("difficulty") == "trap"
            or item.get("expected_behaviour") == "refuse_or_explain"
            or q_id.lower() in ("q16", "q17")
        )
        expected_rows = item.get("expected_rows") or []

        for current_lang in langs_to_run:
            run_idx += 1
            q_key = "question_en" if current_lang == "en" else "question_fa"
            question = item.get(q_key) or item.get("question_en") or item.get("question_fa") or ""

            print(f"[{run_idx}/{total_runs}] Testing {q_id} ({current_lang}): {question[:55]}...")
            trace = process_question(question)

            passed = False
            reason = "OK"

            if is_trap:
                if trace["action"] in ("refuse_write", "refuse_out_of_scope") and not trace["sql"] and trace["row_count"] == 0:
                    passed = True
                    reason = f"Refused properly ({trace['action']}), no SQL executed"
                else:
                    reason = f"Trap failed! Action={trace['action']}, SQL_executed={bool(trace['sql'])}"
            else:
                if trace["action"] != "answer_from_query":
                    reason = f"Did not query DB. Action={trace['action']}"
                elif "FAILED" in trace["validation"] or "Error" in trace["validation"]:
                    reason = f"Validation/Execution failed: {trace['validation']}"
                else:
                    ordered = is_ranking_question(question, item)
                    passed, reason = rows_match(trace["raw_rows"], expected_rows, ordered)

            if passed:
                pass_count += 1

            results.append({
                "ID": f"{q_id}_{current_lang}" if lang == "both" else q_id,
                "Lang": current_lang,
                "Status": "PASS ✅" if passed else "FAIL ❌",
                "Action": trace["action"],
                "Retries": trace["retries"],
                "Generated SQL": trace["sql"].replace("\n", " ") if trace["sql"] else "None",
                "Reason": reason
            })

    df_res = pd.DataFrame(results)

    summary_md = f"# Evaluation Report ({pass_count}/{total_runs} Passed)\n\n"
    summary_md += df_res.to_markdown(index=False)
    with open("eval_report.md", "w", encoding="utf-8") as f:
        f.write(summary_md)

    print(f"\n✨ Evaluation Finished: {pass_count}/{total_runs} PASSED!")
    print("📄 Saved full report to eval_report.md\n")
    print(df_res[["ID", "Status", "Action", "Reason"]].to_string(index=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--lang", choices=["en", "fa", "both"], default="en", help="Language to evaluate")
    args = parser.parse_args()
    run_evaluations(lang=args.lang)