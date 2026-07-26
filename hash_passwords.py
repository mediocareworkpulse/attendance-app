from supabase import create_client
from werkzeug.security import generate_password_hash

SUPABASE_URL = 'https://lznqrkujlrcxcxizygzq.supabase.co'
SUPABASE_KEY = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...'   # your anon key
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# Fetch all employees
emps = supabase.table('employees').select('*').execute()
for e in emps.data:
    pw = e['password']
    # Only hash if it doesn't look like a hash already (simple check)
    if not pw.startswith('scrypt:'):
        hashed = generate_password_hash(pw)
        supabase.table('employees').update({'password': hashed}).eq('id', e['id']).execute()
        print(f"Hashed password for {e['full_name']}")
print("Done.")
