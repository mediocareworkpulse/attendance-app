from flask import Flask, render_template, request, redirect, url_for, session
from datetime import date, datetime, timedelta, timezone
from supabase import create_client
from functools import wraps
from collections import defaultdict
import pytz
import time

app = Flask(__name__)
app.secret_key = 'mediocare-attendance-secret-2024'

SUPABASE_URL = 'https://lznqrkujlrcxcxizygzq.supabase.co'
SUPABASE_KEY = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Imx6bnFya3VqbHJjeGN4aXp5Z3pxIiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODQ1NjIwNjUsImV4cCI6MjEwMDEzODA2NX0.Jj_EW42NVMQk6zbEcNoY-IlrSe0tgW4zFiKoBSapiDA'

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
EAT = timezone(timedelta(hours=3))

DEPARTMENTS = ['Staff','Store','Dispatch','Sales','Stock Control','Procurement','Accounts Office','Operations','Branch Management']
ALL_ROLES = [
    'Staff','Branch Manager','Stock Controller','Assistant Stock Controller',
    'Procurement Officer','Procurement Assistant','Accountant','Accountant Assistant',
    'HR','HR Assistant','Sales Manager','Marketers','Telesales','Dispatch Personnel',
    'Operations Manager','Operations Assistant','Store Manager','Storekeeper',
    'Store Personnel','Dispatch Supervisor','Dispatch Assistant','Cleaner',
    'Riders','Drivers','Security','admin','ceo'
]
NO_CHECKIN_ROLES = ['admin','ceo']
FULL_ACCESS_ROLES = ['admin','ceo']
SALES_SUBMIT_ROLES = ['Staff','Branch Manager']
SALES_VIEW_ROLES = ['admin','ceo','Stock Controller','Assistant Stock Controller','Accountant','Accountant Assistant']
STORE_MANAGER_TEAM = ['Store Assistant','Store Personnel']
OPERATIONS_MANAGER_TEAM = ['Store Manager','Store Assistant','Store Personnel',
                          'Dispatch Supervisor','Dispatch Assistant','Dispatch Personnel',
                          'Riders','Drivers','Security','Cleaner']
COMPANY_NAME = 'Mediocare Pharmaceutical Ltd'

def login_required(f):
    @wraps(f)
    def d(*a,**k):
        if 'user' not in session: return redirect('/login')
        return f(*a,**k)
    return d

def admin_required(f):
    @wraps(f)
    def d(*a,**k):
        if session.get('role') not in FULL_ACCESS_ROLES: return redirect('/')
        return f(*a,**k)
    return d

def can_view_all():
    role = session.get('role','')
    return role in SALES_VIEW_ROLES

def execute_query(builder, max_retries=2):
    for attempt in range(max_retries+1):
        try: return builder.execute()
        except Exception as e:
            if attempt == max_retries: raise e
            time.sleep(1)

def safe_data(r):
    if hasattr(r,'data'): return r.data or []
    if isinstance(r,dict): return r.get('data',[])
    return []

def get_branches():
    return safe_data(execute_query(supabase.table('branches').select('*').order('name')))

def get_branch_names():
    return [b['name'] for b in get_branches()]

def now_eat():
    return datetime.now(EAT)

# -----------------------------------------------------------
@app.route('/login', methods=['GET','POST'])
def login():
    if request.method == 'POST':
        name = request.form.get('full_name','').strip()
        pw = request.form.get('password','').strip()
        r = execute_query(supabase.table('employees').select('*').eq('full_name',name))
        data = safe_data(r)
        if data:
            emp = data[0]
            if emp.get('password','') == pw:
                if emp.get('status','') not in ['','approved']:
                    return render_template('login.html', error='Account pending approval.')
                session['user'] = emp['full_name']
                session['role'] = emp.get('role','Staff')
                session['department'] = emp.get('department','')
                session['branch'] = emp.get('branch','')
                return redirect('/')
        return render_template('login.html', error='Invalid credentials.')
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect('/login')

@app.route('/keep-alive')
def keep_alive():
    return 'OK', 200

# -----------------------------------------------------------
@app.route('/signup', methods=['GET','POST'])
def signup():
    signup_roles = [r for r in ALL_ROLES if r not in ['admin','ceo']]
    if request.method == 'POST':
        name = request.form.get('full_name','').strip()
        phone = request.form.get('phone','').strip()
        pw = request.form.get('password','').strip()
        dept = request.form.get('department','').strip()
        branch = request.form.get('branch','').strip()
        role = request.form.get('role','').strip()
        shift_start = request.form.get('shift_start','08:00').strip()
        shift_end = request.form.get('shift_end','17:00').strip()
        if role not in signup_roles: role = 'Staff'
        if not name or not phone or not pw:
            return render_template('signup.html', branches=get_branch_names(), departments=DEPARTMENTS, roles=signup_roles, error='All fields required.')
        check = execute_query(supabase.table('employees').select('id').eq('full_name',name))
        if safe_data(check):
            return render_template('signup.html', branches=get_branch_names(), departments=DEPARTMENTS, roles=signup_roles, error='Name already exists.')
        supabase.table('employees').insert({
            'full_name':name,'phone':phone,'password':pw,
            'department':dept,'branch':branch,'role':role,
            'status':'pending',
            'shift_start':shift_start,'shift_end':shift_end
        }).execute()
        return render_template('signup.html', branches=get_branch_names(), departments=DEPARTMENTS, roles=signup_roles,
            success='Registration submitted! Welcome to {}!'.format(COMPANY_NAME))
    return render_template('signup.html', branches=get_branch_names(), departments=DEPARTMENTS, roles=signup_roles)

# -----------------------------------------------------------
@app.route('/')
@login_required
def home():
    today = str(now_eat().date())
    role = session.get('role','Staff')
    ub = session.get('branch','')
    un = session.get('user','')

    # ---- main queries with retry ----
    if role in FULL_ACCESS_ROLES or can_view_all():
        emp_r = execute_query(supabase.table('employees').select('id').eq('status','approved'))
        att_r = execute_query(supabase.table('attendance').select('*').eq('date',today).limit(20))
        sales_r = execute_query(supabase.table('sales').select('total_sales').eq('date',today))
    elif role == 'Store Manager':
        team_names = [e['full_name'] for e in safe_data(execute_query(supabase.table('employees').select('full_name').eq('status','approved').in_('role', STORE_MANAGER_TEAM).eq('branch',ub)))]
        att_r = execute_query(supabase.table('attendance').select('*').eq('date',today).in_('full_name', team_names))
        sales_r = execute_query(supabase.table('sales').select('total_sales').eq('date',today).in_('full_name', team_names))
        emp_r = execute_query(supabase.table('employees').select('id').eq('status','approved').in_('role', STORE_MANAGER_TEAM).eq('branch',ub))
    elif role == 'Operations Manager':
        team_names = [e['full_name'] for e in safe_data(execute_query(supabase.table('employees').select('full_name').eq('status','approved').in_('role', OPERATIONS_MANAGER_TEAM)))]
        att_r = execute_query(supabase.table('attendance').select('*').eq('date',today).in_('full_name', team_names))
        sales_r = execute_query(supabase.table('sales').select('total_sales').eq('date',today).in_('full_name', team_names))
        emp_r = execute_query(supabase.table('employees').select('id').eq('status','approved').in_('role', OPERATIONS_MANAGER_TEAM))
    else:
        emp_r = None
        att_r = execute_query(supabase.table('attendance').select('*').eq('date',today).eq('full_name',un))
        sales_r = execute_query(supabase.table('sales').select('total_sales').eq('date',today).eq('full_name',un))

    total_emp = len(safe_data(emp_r)) if emp_r else 0
    att_data = safe_data(att_r)
    present = sum(1 for a in att_data if a.get('check_in') and a.get('status') not in ['lunch','checked_out'])
    late = sum(1 for a in att_data if a.get('status')=='late')
    total_sales = sum(float(s.get('total_sales',0)) for s in safe_data(sales_r))

    # ---- build records with graceful detail fetch ----
    records = []
    for rec in att_data[:10]:
        st = rec.get('status','present')
        emp_detail = []
        try:
            # Wrap the single query so it never breaks the page
            emp_detail = safe_data(execute_query(supabase.table('employees').select('role,department').eq('full_name',rec['full_name'])))
        except:
            emp_detail = []
        role_disp = emp_detail[0].get('role','') if emp_detail else ''
        dept_disp = emp_detail[0].get('department','') if emp_detail else rec.get('department','')
        records.append({
            'full_name': rec['full_name'],
            'department': dept_disp,
            'role': role_disp,
            'check_in': rec.get('check_in','—'),
            'check_out': rec.get('check_out','—'),
            'status': st,
            'label': {'present':'Working','late':'Working','lunch':'At Lunch','checked_out':'Checked Out'}.get(st, st)
        })

    uci=uco=False; user_status=''
    if role not in NO_CHECKIN_ROLES:
        my = safe_data(execute_query(supabase.table('attendance').select('*').eq('full_name',un).eq('date',today)))
        if my:
            uci = bool(my[0].get('check_in'))
            uco = bool(my[0].get('check_out'))
            if uco: user_status = 'Checked Out'
            elif my[0].get('status') == 'lunch': user_status = 'At Lunch'
            elif uci: user_status = 'Working'
            else: user_status = 'Not Checked In'

    pending=0
    if role in FULL_ACCESS_ROLES:
        pending=len(safe_data(execute_query(supabase.table('employees').select('id').eq('status','pending'))))

    return render_template('index.html',
        total_employees=total_emp,present_count=present,late_count=late,
        total_sales=total_sales,recent_records=records,
        user_checked_in=uci,user_checked_out=uco,user_status=user_status,
        pending_count=pending,company=COMPANY_NAME)

# -----------------------------------------------------------
# All other routes (admin, approvals, employees, branches, check-in/out,
# attendance history, sales, profile, reports, leaves, approve leaves, error handler)
# are unchanged from the previous full app.py.  Ensure they are present.
# For brevity they are not repeated, but your app.py must include them.

# -----------------------------------------------------------
@app.errorhandler(Exception)
def handle_exception(e):
    print(f"Unhandled error: {e}")
    return render_template('error.html', error=str(e)), 500

if __name__=='__main__':
    app.run(host='0.0.0.0',port=5000)
