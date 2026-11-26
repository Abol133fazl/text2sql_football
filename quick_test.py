# test_quick.py
from agent import process_question

print("⏳ در حال ارسال یک سوال تستی...")
result = process_question("تراکتور در بازی‌های خانگی چه نتایجی گرفته است؟")

print("\n--- نتیجه تست ---")
print(f"Action: {result['action']}")
print(f"Intent: {result['intent']}")
print(f"SQL: {result['sql']}")
print(f"Validation: {result['validation']}")
print(f"Row count: {result['row_count']}")
print(f"Answer: {result['answer']}")