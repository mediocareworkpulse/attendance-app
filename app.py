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
    for attempt in range(max_retries + 1):
        try:
            return builder.execute()
        except Exception as e:
            if attempt == max_retries:
                raise e
            time.sleep(1)

def safe_data(r):
    if hasattr(r, 'data'):
        return r.data if r.data else []
    if isinstance(r, dict):
        return r.get('data', [])
    return []

def get_branches():
    res = execute_query(supabase.table('branches').select('*').order('name'))
    return safe_data(res)

def get_branch_names():
    return [b['name'] for b in get_branches()]

def now_eat():
    return datetime.now(EAT)

# ═══════════════ LOGIN / LOGOUT / KEEP‑ALIVE ═══════════════
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

# ═══════════════ SIGNUP ═══════════════
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
            'shift_start':shift_start,
            'shift_end':shift_end
        }).execute()
        return render_template('signup.html', branches=get_branch_names(), departments=DEPARTMENTS, roles=signup_roles,
            success='Registration submitted! Welcome to {}!'.format(COMPANY_NAME))
    return render_template('signup.html', branches=get_branch_names(), departments=DEPARTMENTS, roles=signup_roles)

# ═══════════════ DASHBOARD ═══════════════
@app.route('/')
@login_required
def home():
    today = str(now_eat().date())
    role = session.get('role','Staff')
    ub = session.get('branch','')
    un = session.get('user','')

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

    # Build records with role/department
    records = []
    for rec in att_data[:10]:
        st = rec.get('status','present')
        emp_detail = safe_data(execute_query(supabase.table('employees').select('role,department').eq('full_name',rec['full_name'])))
        role_display = emp_detail[0].get('role','') if emp_detail else ''
        dept_display = emp_detail[0].get('department','') if emp_detail else rec.get('department','')
        records.append({
            'full_name': rec['full_name'],
            'department': dept_display,
            'role': role_display,
            'check_in': rec.get('check_in','—'),
            'check_out': rec.get('check_out','—'),
            'status': st,
            'lunch_start': rec.get('lunch_start'),
            'lunch_end': rec.get('lunch_end'),
            'label': {'present':'Working','late':'Working','lunch':'At Lunch','checked_out':'Checked Out'}.get(st, st)
        })

    uci=uco=False
    user_status = ''
    if role not in NO_CHECKIN_ROLES:
        my = safe_data(execute_query(supabase.table('attendance').select('*').eq('full_name',un).eq('date',today)))
        if my:
            uci = bool(my[0].get('check_in'))
            uco = bool(my[0].get('check_out'))
            if uco:
                user_status = 'Checked Out'
            elif my[0].get('status') == 'lunch':
                user_status = 'At Lunch'
            elif uci:
                user_status = 'Working'
            else:
                user_status = 'Not Checked In'
        else:
            user_status = 'Not Checked In'

    pending = 0
    if role in FULL_ACCESS_ROLES:
        pending = len(safe_data(execute_query(supabase.table('employees').select('id').eq('status','pending'))))

    return render_template('index.html',
                         total_employees=total_emp,
                         present_count=present,
                         late_count=late,
                         total_sales=total_sales,
                         recent_records=records,
                         user_checked_in=uci,
                         user_checked_out=uco,
                         user_status=user_status,
                         pending_count=pending,
                         company=COMPANY_NAME)

# ═══════════════ ADMIN PANEL ═══════════════
@app.route('/admin')
@login_required
@admin_required
def admin_panel():
    total_emp = len(safe_data(execute_query(supabase.table('employees').select('id').eq('status','approved'))))
    pending = len(safe_data(execute_query(supabase.table('employees').select('id').eq('status','pending'))))
    total_branches = len(get_branches())
    today = str(now_eat().date())
    att_today = len(safe_data(execute_query(supabase.table('attendance').select('id').eq('date',today))))
    return render_template('admin.html',
                         total_employees=total_emp,
                         pending_count=pending,
                         total_branches=total_branches,
                         att_today=att_today,
                         company=COMPANY_NAME)

# ═══════════════ APPROVALS ═══════════════
@app.route('/approvals')
@login_required
@admin_required
def approvals_page():
    pending = safe_data(execute_query(supabase.table('employees').select('*').eq('status','pending').order('created_at',desc=True).limit(50)))
    return render_template('approvals.html', pending=pending)

@app.route('/approvals/approve/<int:eid>', methods=['POST'])
@login_required
@admin_required
def approve(eid):
    supabase.table('employees').update({'status':'approved'}).eq('id',eid).execute()
    return redirect('/approvals')

@app.route('/approvals/reject/<int:eid>', methods=['POST'])
@login_required
@admin_required
def reject(eid):
    supabase.table('employees').delete().eq('id',eid).execute()
    return redirect('/approvals')

# ═══════════════ EMPLOYEES ═══════════════
@app.route('/employees')
@login_required
@admin_required
def employees_page():
    emps = safe_data(execute_query(supabase.table('employees').select('*').eq('status','approved').order('full_name').limit(200)))
    return render_template('employees.html', employees=emps, branches=get_branch_names(), departments=DEPARTMENTS, roles=ALL_ROLES, company=COMPANY_NAME)

@app.route('/employees/add', methods=['POST'])
@login_required
@admin_required
def add_employee():
    d = {'full_name':request.form.get('full_name','').strip(),'department':request.form.get('department','').strip(),'branch':request.form.get('branch','').strip(),'role':request.form.get('role','Staff').strip(),'password':request.form.get('password','1234').strip(),'status':'approved'}
    if d['full_name']:
        check = execute_query(supabase.table('employees').select('id').eq('full_name',d['full_name']))
        if not safe_data(check):
            supabase.table('employees').insert(d).execute()
    return redirect('/employees')

@app.route('/employees/delete/<int:eid>', methods=['POST'])
@login_required
@admin_required
def delete_employee(eid):
    emp = safe_data(execute_query(supabase.table('employees').select('full_name').eq('id',eid)))
    if emp:
        n = emp[0]['full_name']
        supabase.table('attendance').delete().eq('full_name',n).execute()
        supabase.table('sales').delete().eq('full_name',n).execute()
        supabase.table('leaves').delete().eq('full_name',n).execute()
    supabase.table('employees').delete().eq('id',eid).execute()
    return redirect('/employees')

@app.route('/employees/edit/<int:eid>', methods=['POST'])
@login_required
@admin_required
def edit_employee(eid):
    data = {
        'full_name': request.form.get('full_name','').strip(),
        'department': request.form.get('department','').strip(),
        'branch': request.form.get('branch','').strip(),
        'role': request.form.get('role','Staff').strip(),
        'password': request.form.get('password','1234').strip(),
        'shift_start': request.form.get('shift_start','08:00').strip(),
        'shift_end': request.form.get('shift_end','17:00').strip(),
        'updated_at': now_eat().isoformat()
    }
    if not data['full_name']: return redirect('/employees')
    supabase.table('employees').update(data).eq('id', eid).execute()
    return redirect('/employees')

# ═══════════════ BRANCHES ═══════════════
@app.route('/branches')
@login_required
@admin_required
def branches_page():
    branches = get_branches()
    return render_template('branches.html', branches=branches, company=COMPANY_NAME)

@app.route('/branches/add', methods=['POST'])
@login_required
@admin_required
def add_branch():
    n = request.form.get('name','').strip()
    ss = request.form.get('shift_start','08:00')
    se = request.form.get('shift_end','17:00')
    if n: supabase.table('branches').insert({'name':n,'shift_start':ss,'shift_end':se}).execute()
    return redirect('/branches')

@app.route('/branches/edit/<int:bid>', methods=['POST'])
@login_required
@admin_required
def edit_branch(bid):
    supabase.table('branches').update({
        'name':request.form.get('name','').strip(),
        'shift_start':request.form.get('shift_start','08:00'),
        'shift_end':request.form.get('shift_end','17:00')
    }).eq('id',bid).execute()
    return redirect('/branches')

@app.route('/branches/delete/<int:bid>', methods=['POST'])
@login_required
@admin_required
def delete_branch(bid):
    supabase.table('branches').delete().eq('id',bid).execute()
    return redirect('/branches')

# ═══════════════ CHECK IN / OUT ═══════════════
@app.route('/check-in')
@login_required
def check_in_page():
    today = str(now_eat().date())
    role = session.get('role')
    un = session.get('user')
    ub = session.get('branch','')
    emp = safe_data(execute_query(supabase.table('employees').select('shift_start,shift_end,role,department,branch').eq('full_name',un)))
    emp_info = emp[0] if emp else {}
    shift_start = emp_info.get('shift_start','08:00')
    shift_end = emp_info.get('shift_end','17:00')

    branch_info = {}
    if ub:
        br = execute_query(supabase.table('branches').select('*').eq('name',ub))
        brd = safe_data(br)
        if brd: branch_info = brd[0]

    my_att = safe_data(execute_query(supabase.table('attendance').select('*').eq('full_name',un).eq('date',today)))
    current_status = 'none'
    check_in_time = None
    lunch_active = False
    if my_att:
        rec = my_att[0]
        if rec.get('check_out'):
            current_status = 'completed'
        elif rec.get('status') == 'lunch':
            current_status = 'lunch'
            check_in_time = rec.get('check_in')
        elif rec.get('check_in'):
            current_status = 'checked_in'
            check_in_time = rec.get('check_in')
            lunch_active = (rec.get('lunch_start') and not rec.get('lunch_end'))

    if role in FULL_ACCESS_ROLES or can_view_all():
        r = safe_data(execute_query(supabase.table('attendance').select('*').eq('date',today).limit(50)))
    elif role == 'Store Manager':
        team_names = [e['full_name'] for e in safe_data(execute_query(supabase.table('employees').select('full_name').eq('status','approved').in_('role', STORE_MANAGER_TEAM).eq('branch',ub)))]
        r = safe_data(execute_query(supabase.table('attendance').select('*').eq('date',today).in_('full_name', team_names)))
    elif role == 'Operations Manager':
        team_names = [e['full_name'] for e in safe_data(execute_query(supabase.table('employees').select('full_name').eq('status','approved').in_('role', OPERATIONS_MANAGER_TEAM)))]
        r = safe_data(execute_query(supabase.table('attendance').select('*').eq('date',today).in_('full_name', team_names)))
    else:
        r = my_att

    records = []
    for rec in r:
        st = rec.get('status','present')
        emp_det = safe_data(execute_query(supabase.table('employees').select('role,department').eq('full_name',rec['full_name'])))
        role_disp = emp_det[0].get('role','') if emp_det else ''
        dept_disp = emp_det[0].get('department','') if emp_det else rec.get('department','')
        records.append({
            'full_name': rec['full_name'],
            'department': dept_disp,
            'role': role_disp,
            'check_in': rec.get('check_in','—'),
            'check_out': rec.get('check_out','—'),
            'status': st,
            'label': {'present':'Working','late':'Working','lunch':'At Lunch','checked_out':'Checked Out'}.get(st, 'Working')
        })

    return render_template('check_in.html',
                         records=records,
                         user_status=current_status,
                         today=today,
                         company=COMPANY_NAME,
                         branch_info=branch_info,
                         check_in_time=check_in_time,
                         shift_start=shift_start,
                         shift_end=shift_end,
                         lunch_active=lunch_active,
                         emp_info=emp_info)

@app.route('/check-in', methods=['POST'])
@login_required
def process_attendance():
    if session.get('role') in NO_CHECKIN_ROLES: return redirect('/')
    un = session.get('user')
    action = request.form.get('action')
    today = str(now_eat().date())
    now = now_eat().strftime('%H:%M:%S')
    lat = request.form.get('lat','')
    lng = request.form.get('lng','')
    loc = request.form.get('location','')

    emp = safe_data(execute_query(supabase.table('employees').select('department,branch,shift_start').eq('full_name',un)))
    if not emp: return redirect('/check-in')
    dept = emp[0].get('department','')
    branch = emp[0].get('branch','')
    shift_start = emp[0].get('shift_start','09:00')

    existing = safe_data(execute_query(supabase.table('attendance').select('*').eq('full_name',un).eq('date',today)))
    exd = existing[0] if existing else None

    if action == 'check_in':
        if exd and exd.get('check_in'): return redirect('/check-in')
        status = 'late' if now > shift_start else 'present'
        d = {
            'check_in': now,
            'status': status,
            'check_in_lat': lat, 'check_in_lng': lng, 'check_in_location': loc
        }
        if exd:
            supabase.table('attendance').update(d).eq('full_name',un).eq('date',today).execute()
        else:
            d.update({'full_name':un,'department':dept,'branch':branch,'date':today})
            supabase.table('attendance').insert(d).execute()
    elif action == 'check_out':
        if exd and exd.get('check_in') and not exd.get('check_out') and exd.get('status') != 'lunch':
            supabase.table('attendance').update({
                'check_out': now,
                'status': 'checked_out',
                'check_out_lat': lat, 'check_out_lng': lng, 'check_out_location': loc
            }).eq('full_name',un).eq('date',today).execute()
    elif action == 'start_lunch':
        if exd and exd.get('check_in') and not exd.get('check_out') and exd.get('status') != 'lunch':
            supabase.table('attendance').update({
                'lunch_start': now,
                'status': 'lunch'
            }).eq('full_name',un).eq('date',today).execute()
    elif action == 'end_lunch':
        if exd and exd.get('status') == 'lunch' and not exd.get('lunch_end'):
            supabase.table('attendance').update({
                'lunch_end': now,
                'status': 'present'   # back to working
            }).eq('full_name',un).eq('date',today).execute()

    return redirect('/check-in')

# ═══════════════ ATTENDANCE HISTORY (with perfect filter buttons) ═══════════════
@app.route('/attendance-history')
@login_required
def attendance_history():
    role = session.get('role')
    un = session.get('user')
    ub = session.get('branch','')
    period = request.args.get('period','month')
    today = now_eat().date()
    sd = str(today - timedelta(days=7)) if period == 'week' else str(today.replace(day=1))
    ed = str(today)
    if role in FULL_ACCESS_ROLES or can_view_all():
        r = safe_data(execute_query(supabase.table('attendance').select('*').gte('date',sd).lte('date',ed).order('date',desc=True).limit(100)))
    elif role == 'Store Manager':
        team_names = [e['full_name'] for e in safe_data(execute_query(supabase.table('employees').select('full_name').eq('status','approved').in_('role', STORE_MANAGER_TEAM).eq('branch',ub)))]
        r = safe_data(execute_query(supabase.table('attendance').select('*').gte('date',sd).lte('date',ed).in_('full_name', team_names).order('date',desc=True).limit(100)))
    elif role == 'Operations Manager':
        team_names = [e['full_name'] for e in safe_data(execute_query(supabase.table('employees').select('full_name').eq('status','approved').in_('role', OPERATIONS_MANAGER_TEAM)))]
        r = safe_data(execute_query(supabase.table('attendance').select('*').gte('date',sd).lte('date',ed).in_('full_name', team_names).order('date',desc=True).limit(100)))
    else:
        r = safe_data(execute_query(supabase.table('attendance').select('*').gte('date',sd).lte('date',ed).eq('full_name',un).order('date',desc=True).limit(100)))
    records = []
    for rec in r:
        st = rec.get('status','present')
        records.append({
            'date': rec.get('date',''),
            'full_name': rec.get('full_name',''),
            'check_in': rec.get('check_in','—'),
            'check_out': rec.get('check_out','—'),
            'status': st,
            'label': {'present':'Working','late':'Working','lunch':'At Lunch','checked_out':'Checked Out'}.get(st, st)
        })
    return render_template('attendance_history.html', records=records, period=period, today=str(today), company=COMPANY_NAME)

# ═══════════════ SALES, PROFILE, REPORTS, LEAVES (unchanged) ═══════════════
# ... (include all other existing routes from the previous full app.py exactly as they were)

@app.route('/sales', methods=['GET','POST'])
@login_required
def sales_page():
    # (same as before)
    pass  # placeholder – keep your existing code

@app.route('/profile', methods=['GET','POST'])
@login_required
def profile():
    # (same as before)
    pass

@app.route('/reports')
@login_required
def reports():
    # (same as before)
    pass

@app.route('/leaves', methods=['GET','POST'])
@login_required
def leaves():
    # (same as before)
    pass

@app.route('/leave-pdf/<int:lid>')
@login_required
def leave_pdf(lid):
    # (same as before)
    pass

@app.route('/approve-leaves')
@login_required
def approve_leaves():
    # (same as before)
    pass

@app.route('/approve-leaves/<int:lid>/<action>', methods=['POST'])
@login_required
def process_leave(lid, action):
    # (same as before)
    pass

@app.errorhandler(Exception)
def handle_exception(e):
    print(f"Unhandled error: {e}")
    return render_template('error.html', error=str(e)), 500

if __name__=='__main__':
    app.run(host='0.0.0.0',port=5000)
