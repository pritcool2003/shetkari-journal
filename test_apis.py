import os
import sys
import json
from dotenv import load_dotenv

# Try loading from .env
load_dotenv()

print("=== Shetkari Journal Bot Diagnostic Tool ===")

# 1. Check Env Variables
required_vars = [
    "TELEGRAM_BOT_TOKEN",
    "OPENAI_API_KEY",
    "SUPABASE_URL",
    "SUPABASE_KEY"
]

all_set = True
for var in required_vars:
    val = os.getenv(var)
    if val:
        # Hide sensitive values partially
        display_val = val[:10] + "..." if len(val) > 10 else val
        print(f"[OK] {var} is set (starts with: '{display_val}')")
    else:
        print(f"[MISSING] {var} is MISSING!")
        all_set = False

if not all_set:
    print("\n[WARNING] Please configure all missing environment variables in your environment or a .env file.")
    sys.exit(1)

# 2. Test OpenAI connection
print("\n--- Testing OpenAI API ---")
try:
    from openai import OpenAI
    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": "Hello"}],
        max_tokens=5
    )
    print("[OK] OpenAI API: Connection successful!")
    print(f"   Response: {response.choices[0].message.content.strip()}")
except Exception as e:
    print(f"[ERROR] OpenAI API: Failed! Error: {e}")

# 3. Test Supabase Database Connection
print("\n--- Testing Supabase Connection ---")
try:
    from supabase_client import _get_client
    supabase = _get_client()
    
    print("   Fetching expenses table to verify read permissions...")
    res = supabase.table("expenses").select("id").limit(1).execute()
    print(f"[OK] Supabase DB: Connection successful! Found records: {len(res.data)}")
    
    print("   Checking Supabase Storage bucket 'bills' exists...")
    buckets = supabase.storage.list_buckets()
    bucket_names = [b.name for b in buckets]
    if "bills" in bucket_names:
        print("[OK] Supabase Storage: 'bills' bucket exists and is accessible!")
        bill_bucket = next(b for b in buckets if b.name == "bills")
        print(f"   Bucket 'bills' public status: {bill_bucket.public} (Should be True)")
    else:
        print("[WARNING] Supabase Storage: 'bills' bucket not found! Please create a public bucket named 'bills'.")
except Exception as e:
    print(f"[ERROR] Supabase Connection: Failed! Error: {e}")

print("\n=== Diagnostics Completed ===")

