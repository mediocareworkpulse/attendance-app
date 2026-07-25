from flask import Flask, render_template, request, redirect, url_for, session
from datetime import date, datetime, timedelta, timezone
from supabase import create_client
from functools import wraps
from collections import defaultdict
import pytz, time

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
OPERATIONS_MANAGER_TEAM = [
    'Store Manager','Store Assistant','Store Personnel',
    'Dispatch Supervisor','Dispatch Assistant','Dispatch Personnel',
    'Riders','Drivers','Security','Cleaner'
]
RIDER_DRIVER_ROLES = ['Riders','Drivers']
MARKETER_ROLE = 'Marketers'
SALES_MANAGER_ROLE = 'Sales Manager'
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
    return session.get('role','') in SALES_VIEW_ROLES

def execute_query(builder, retries=2):
    for i in range(retries+1):
        try: return builder.execute()
        except Exception as e:
            if i == retries: raise e
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

# ---------- AUTH ----------
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

@app.route('/favicon.ico')
def favicon():
    return '', 204

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
            'status':'pending','shift_start':shift_start,'shift_end':shift_end
        }).execute()
        return render_template('signup.html', branches=get_branch_names(), departments=DEPARTMENTS, roles=signup_roles,
            success='Registration submitted! Welcome to {}!'.format(COMPANY_NAME))
    return render_template('signup.html', branches=get_branch_names(), departments=DEPARTMENTS, roles=signup_roles)

# ---------- DASHBOARD (unchanged) ----------
# ... (all existing routes like home, admin, approvals, employees, branches, check-in, attendance history, sales, profile, reports, leaves, approve-leaves, error handler)
# They remain exactly as they were in the last full version. I'm including only the new routes below.
# You must keep the old routes in your actual file.

# ---------- NEW: MARKETER CHECK-IN REQUEST ----------
@app.route('/marketer/checkin', methods=['POST'])
@login_required
def marketer_checkin():
    if session.get('role') != MARKETER_ROLE: return redirect('/check-in')
    un = session.get('user')
    today = str(now_eat().date())
    now = now_eat().strftime('%H:%M:%S')
    lat = request.form.get('lat',''); lng = request.form.get('lng',''); loc = request.form.get('location','')

    # Create a pending check-in
    supabase.table('marketer_checkins').insert({
        'full_name': un,
        'date': today,
        'check_in_time': now,
        'lat': lat,
        'lng': lng,
        'location': loc,
        'status': 'pending'
    }).execute()

    return redirect('/check-in?pending=1')

# ---------- NEW: MARKETER REPORT SUBMISSION ----------
@app.route('/marketer/report', methods=['POST'])
@login_required
def marketer_report():
    if session.get('role') != MARKETER_ROLE: return redirect('/check-in')
    un = session.get('user')
    today = str(now_eat().date())
    customer = request.form.get('customer_name','').strip()
    phone = request.form.get('customer_phone','').strip()
    details = request.form.get('details','').strip()
    expenses = request.form.get('expenses','0')

    try:
        exp = float(expenses)
    except:
        exp = 0.0

    if customer:
        supabase.table('customer_reports').insert({
            'full_name': un,
            'date': today,
            'customer_name': customer,
            'customer_phone': phone,
            'details': details,
            'expenses': exp
        }).execute()

    return redirect('/check-in?report=1')

# ---------- NEW: SALES MANAGER DASHBOARD ----------
@app.route('/sales-manager')
@login_required
def sales_manager_dashboard():
    if session.get('role') != SALES_MANAGER_ROLE: return redirect('/')
    today = str(now_eat().date())

    # Pending check‑ins from marketers
    pending_checkins = safe_data(execute_query(
        supabase.table('marketer_checkins').select('*').eq('date',today).eq('status','pending').order('created_at',desc=True).limit(50)
    ))

    # Today's approved check‑ins
    approved_checkins = safe_data(execute_query(
        supabase.table('marketer_checkins').select('*').eq('date',today).eq('status','approved').order('check_in_time').limit(50)
    ))

    # Today's reports
    reports = safe_data(execute_query(
        supabase.table('customer_reports').select('*').eq('date',today).order('created_at',desc=True).limit(50)
    ))

    # Assigned places
    assigned = safe_data(execute_query(
        supabase.table('assigned_places').select('*').order('date_assigned',desc=True).limit(100)
    ))

    return render_template('sales_manager.html',
                         pending_checkins=pending_checkins,
                         approved_checkins=approved_checkins,
                         reports=reports,
                         assigned=assigned,
                         today=today,
                         company=COMPANY_NAME)

# ---------- NEW: APPROVE / REJECT CHECK‑IN ----------
@app.route('/sales-manager/approve/<int:cid>', methods=['POST'])
@login_required
def approve_checkin(cid):
    if session.get('role') != SALES_MANAGER_ROLE: return redirect('/')
    supabase.table('marketer_checkins').update({'status':'approved'}).eq('id',cid).execute()
    return redirect('/sales-manager')

@app.route('/sales-manager/reject/<int:cid>', methods=['POST'])
@login_required
def reject_checkin(cid):
    if session.get('role') != SALES_MANAGER_ROLE: return redirect('/')
    supabase.table('marketer_checkins').update({'status':'rejected'}).eq('id',cid).execute()
    return redirect('/sales-manager')

# ---------- NEW: ASSIGN PLACES ----------
@app.route('/sales-manager/assign', methods=['POST'])
@login_required
def assign_place():
    if session.get('role') != SALES_MANAGER_ROLE: return redirect('/')
    marketer = request.form.get('marketer_name','').strip()
    place = request.form.get('place_name','').strip()
    if marketer and place:
        supabase.table('assigned_places').insert({
            'marketer_name': marketer,
            'place_name': place,
            'date_assigned': str(now_eat().date())
        }).execute()
    return redirect('/sales-manager')

# ---------- NEW: VIEW ASSIGNED PLACES (for marketer) ----------
@app.route('/my-places')
@login_required
def my_places():
    if session.get('role') != MARKETER_ROLE: return redirect('/')
    un = session.get('user')
    places = safe_data(execute_query(
        supabase.table('assigned_places').select('*').eq('marketer_name',un).order('date_assigned',desc=True).limit(50)
    ))
    return render_template('my_places.html', places=places, company=COMPANY_NAME)

# ═══════════════ All other routes (keep exactly as they were) ═══════════════
# ... you must have the full routes for home, admin, approvals, employees, branches,
# check-in, attendance history, sales, profile, reports, leaves, approve-leaves, etc.

# ---------- ERROR HANDLER ----------
@app.errorhandler(Exception)
def handle_exception(e):
    print(f"Unhandled error: {e}")
    return render_template('error.html', error=str(e)), 500

if __name__=='__main__':
    app.run(host='0.0.0.0',port=5000)
