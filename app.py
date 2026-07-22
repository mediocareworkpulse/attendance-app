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

# ═══════════════ RETRY & SAFE DATA ═══════════════
def execute_query(builder, max_retries=2):
    """Execute a Supabase query builder, retry on failure, return raw response."""
    for attempt in range(max_retries + 1):
        try:
            return builder.execute()
        except Exception as e:
            if attempt == max_retries:
                raise e
            time.sleep(1)

def safe_data(r):
    """Extract data list from Supabase response or dict."""
    if hasattr(r, 'data'):
        return r.data if r.data else []
    if isinstance(r, dict):
        return r.get('data', [])
    return []

def get_branches():
    """Return list of branch dicts (e.g., [{'name':'Ahero','id':1},...])"""
    res = execute_query(supabase.table('branches').select('*').order('name'))
    return safe_data(res)

def get_branch_names():
    return [b['name'] for b in get_branches()]

def now_eat():
    return datetime.now(EAT)

# ═══════════════ LOGIN ═══════════════
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
    present = sum(1 for a in att_data if a.get('check_in'))
    late = sum(1 for a in att_data if a.get('status')=='late')
    total_sales = sum(float(s.get('total_sales',0)) for s in safe_data(sales_r))

    records = [{'full_name':r.get('full_name',''),'department':r.get('department','—'),'check_in':r.get('check_in','—'),'check_out':r.get('check_out','—'),'status':r.get('status','present'),'label':{'present':'Present','late':'Arrived Late'}.get(r.get('status','present'),'Present')} for r in att_data[:10]]

    uci=uco=False
    if role not in NO_CHECKIN_ROLES:
        my = safe_data(execute_query(supabase.table('attendance').select('check_in,check_out').eq('full_name',un).eq('date',today)))
        if my: uci=bool(my[0].get('check_in')); uco=bool(my[0].get('check_out'))

    pending=0
    if role in FULL_ACCESS_ROLES:
        pending=len(safe_data(execute_query(supabase.table('employees').select('id').eq('status','pending'))))

    return render_template('index.html',total_employees=total_emp,present_count=present,late_count=late,total_sales=total_sales,recent_records=records,user_checked_in=uci,user_checked_out=uco,pending_count=pending,company=COMPANY_NAME)

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
    branch_info = {}
    if ub:
        br = execute_query(supabase.table('branches').select('*').eq('name',ub))
        brd = safe_data(br)
        if brd: branch_info = brd[0]

    if role in FULL_ACCESS_ROLES or can_view_all():
        r = safe_data(execute_query(supabase.table('attendance').select('*').eq('date',today).limit(50)))
    elif role == 'Store Manager':
        team_names = [e['full_name'] for e in safe_data(execute_query(supabase.table('employees').select('full_name').eq('status','approved').in_('role', STORE_MANAGER_TEAM).eq('branch',ub)))]
        r = safe_data(execute_query(supabase.table('attendance').select('*').eq('date',today).in_('full_name', team_names)))
    elif role == 'Operations Manager':
        team_names = [e['full_name'] for e in safe_data(execute_query(supabase.table('employees').select('full_name').eq('status','approved').in_('role', OPERATIONS_MANAGER_TEAM)))]
        r = safe_data(execute_query(supabase.table('attendance').select('*').eq('date',today).in_('full_name', team_names)))
    else:
        r = safe_data(execute_query(supabase.table('attendance').select('*').eq('date',today).eq('full_name',un)))

    records = [{'full_name':x.get('full_name',''),'department':x.get('department','—'),'check_in':x.get('check_in','—'),'check_out':x.get('check_out','—'),'status':x.get('status','present'),'label':{'present':'Present','late':'Arrived Late'}.get(x.get('status','present'),'Present')} for x in r]

    us = 'none'; check_in_time = None
    if role not in NO_CHECKIN_ROLES:
        my = safe_data(execute_query(supabase.table('attendance').select('*').eq('full_name',un).eq('date',today)))
        if my:
            if my[0].get('check_out'): us = 'completed'
            elif my[0].get('check_in'):
                us = 'checked_in'
                check_in_time = my[0].get('check_in')

    return render_template('check_in.html', records=records, user_status=us, today=today, company=COMPANY_NAME, branch_info=branch_info, check_in_time=check_in_time)

@app.route('/check-in', methods=['POST'])
@login_required
def process_attendance():
    if session.get('role') in NO_CHECKIN_ROLES: return redirect('/')
    un = session.get('user')
    action = request.form.get('action')
    today = str(now_eat().date())
    now = now_eat().strftime('%H:%M:%S')
    emp = safe_data(execute_query(supabase.table('employees').select('department,branch,shift_start,shift_end').eq('full_name',un)))
    if not emp: return redirect('/check-in')
    dept = emp[0].get('department','')
    branch = emp[0].get('branch','')
    exd = safe_data(execute_query(supabase.table('attendance').select('*').eq('full_name',un).eq('date',today)))

    if action == 'check_in':
        if exd and exd[0].get('check_in'): return redirect('/check-in')
        shift_start_time = emp[0].get('shift_start')
        if not shift_start_time and branch:
            br = execute_query(supabase.table('branches').select('shift_start').eq('name',branch))
            brd = safe_data(br)
            if brd: shift_start_time = str(brd[0].get('shift_start','09:00'))
        if not shift_start_time: shift_start_time = '09:00'
        status = 'late'
        if now <= str(shift_start_time): status = 'present'

        d = {'check_in':now,'status':status,'check_in_lat':request.form.get('lat',''),'check_in_lng':request.form.get('lng',''),'check_in_location':request.form.get('location','')}
        if exd: supabase.table('attendance').update(d).eq('full_name',un).eq('date',today).execute()
        else:
            d.update({'full_name':un,'department':dept,'branch':branch,'date':today})
            supabase.table('attendance').insert(d).execute()
    elif action == 'check_out':
        if exd and exd[0].get('check_in') and not exd[0].get('check_out'):
            supabase.table('attendance').update({'check_out':now}).eq('full_name',un).eq('date',today).execute()
    return redirect('/check-in')

@app.route('/manual-attendance', methods=['POST'])
@login_required
def manual_attendance():
    if session.get('role') in NO_CHECKIN_ROLES: return redirect('/')
    un = session.get('user')
    action = request.form.get('action')
    manual_time = request.form.get('manual_time','')
    today = str(now_eat().date())
    if not manual_time: return redirect('/check-in')
    now = manual_time + ':00'

    emp = safe_data(execute_query(supabase.table('employees').select('department,branch,shift_start,shift_end').eq('full_name',un)))
    if not emp: return redirect('/check-in')
    dept = emp[0].get('department','')
    branch = emp[0].get('branch','')
    exd = safe_data(execute_query(supabase.table('attendance').select('*').eq('full_name',un).eq('date',today)))

    if action == 'check_in':
        if exd and exd[0].get('check_in'): return redirect('/check-in')
        shift_start_time = emp[0].get('shift_start')
        if not shift_start_time and branch:
            br = execute_query(supabase.table('branches').select('shift_start').eq('name',branch))
            brd = safe_data(br)
            if brd: shift_start_time = str(brd[0].get('shift_start','09:00'))
        if not shift_start_time: shift_start_time = '09:00'
        status = 'late'
        if now <= str(shift_start_time): status = 'present'

        d = {'check_in':now,'status':status,'check_in_lat':'','check_in_lng':'','check_in_location':'Manual entry'}
        if exd: supabase.table('attendance').update(d).eq('full_name',un).eq('date',today).execute()
        else:
            d.update({'full_name':un,'department':dept,'branch':branch,'date':today})
            supabase.table('attendance').insert(d).execute()
    elif action == 'check_out':
        if exd and exd[0].get('check_in') and not exd[0].get('check_out'):
            supabase.table('attendance').update({'check_out':now,'check_out_location':'Manual entry'}).eq('full_name',un).eq('date',today).execute()
    return redirect('/check-in')

# ═══════════════ ATTENDANCE HISTORY ═══════════════
@app.route('/attendance-history')
@login_required
def attendance_history():
    role=session.get('role'); un=session.get('user'); ub=session.get('branch','')
    period=request.args.get('period','month'); today=now_eat().date()
    sd=str(today-timedelta(days=7)) if period=='week' else str(today.replace(day=1)); ed=str(today)
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
    records = [{'date':x.get('date',''),'full_name':x.get('full_name',''),'check_in':x.get('check_in','—'),'check_out':x.get('check_out','—'),'status':x.get('status','present'),'label':{'present':'Present','late':'Arrived Late'}.get(x.get('status','present'),'Present')} for x in r]
    return render_template('attendance_history.html', records=records, period=period, today=str(today), company=COMPANY_NAME)

# ═══════════════ SALES ═══════════════
@app.route('/sales', methods=['GET','POST'])
@login_required
def sales_page():
    role=session.get('role'); un=session.get('user'); ub=session.get('branch',''); today=str(now_eat().date())
    if request.method=='POST':
        if role not in SALES_SUBMIT_ROLES: return redirect('/sales')
        try:
            mpesa=float(request.form.get('mpesa_sales','0') or 0); cash=float(request.form.get('cash_sales','0') or 0)
            total=mpesa+cash; stype=request.form.get('sales_type','individual'); notes=request.form.get('notes','')
            emp=safe_data(execute_query(supabase.table('employees').select('department,branch').eq('full_name',un)))
            if emp and total>0:
                if stype=='branch_total' and role=='Branch Manager':
                    supabase.table('branch_sales').upsert({'branch':ub,'date':today,'mpesa_sales':mpesa,'cash_sales':cash,'total_sales':total,'submitted_by':un,'notes':notes}).execute()
                else:
                    supabase.table('sales').insert({'full_name':un,'department':emp[0].get('department',''),'branch':emp[0].get('branch',''),'date':today,'mpesa_sales':mpesa,'cash_sales':cash,'total_sales':total,'sales_type':stype,'notes':notes}).execute()
        except: pass
        return redirect('/sales?success=1')
    if role in FULL_ACCESS_ROLES or can_view_all():
        sd=safe_data(execute_query(supabase.table('sales').select('*').eq('date',today).order('created_at',desc=True).limit(100)))
        bd=safe_data(execute_query(supabase.table('branch_sales').select('*').eq('date',today)))
    elif role=='Branch Manager':
        sd=safe_data(execute_query(supabase.table('sales').select('*').eq('date',today).eq('branch',ub).order('created_at',desc=True).limit(100)))
        bd=safe_data(execute_query(supabase.table('branch_sales').select('*').eq('date',today).eq('branch',ub)))
    else:
        sd=safe_data(execute_query(supabase.table('sales').select('*').eq('date',today).eq('full_name',un).order('created_at',desc=True).limit(100)))
        bd=[]
    t_mpesa=sum(float(s.get('mpesa_sales',0)) for s in sd); t_cash=sum(float(s.get('cash_sales',0)) for s in sd)
    bt=defaultdict(lambda:{'mpesa':0,'cash':0,'total':0})
    for s in sd:
        br=s.get('branch','Unknown')
        bt[br]['mpesa']+=float(s.get('mpesa_sales',0)); bt[br]['cash']+=float(s.get('cash_sales',0)); bt[br]['total']+=float(s.get('total_sales',0))
    return render_template('sales.html',sales=sd,branch_sales=bd,branch_totals=dict(bt),total_mpesa=t_mpesa,total_cash=t_cash,total_all=t_mpesa+t_cash,today=today,company=COMPANY_NAME,success_msg=request.args.get('success',''))

# ═══════════════ PROFILE ═══════════════
@app.route('/profile', methods=['GET','POST'])
@login_required
def profile():
    un=session.get('user'); sm=''
    if request.method=='POST':
        np = request.form.get('new_password','').strip()
        if np:
            supabase.table('employees').update({'password':np}).eq('full_name',un).execute()
            sm = 'Password updated!'
    emp=safe_data(execute_query(supabase.table('employees').select('*').eq('full_name',un)))
    ed=emp[0] if emp else {}
    today=now_eat().date(); ms=today.replace(day=1)
    dp=len(set(a['date'] for a in safe_data(execute_query(supabase.table('attendance').select('date,check_in').eq('full_name',un).gte('date',str(ms)).lte('date',str(today)))) if a.get('check_in')))
    tms=sum(float(s.get('total_sales',0)) for s in safe_data(execute_query(supabase.table('sales').select('total_sales').eq('full_name',un).gte('date',str(ms)).lte('date',str(today)))))
    return render_template('profile.html', employee=ed, days_present=dp, total_my_sales=tms, success_msg=sm, company=COMPANY_NAME)

# ═══════════════ REPORTS ═══════════════
@app.route('/reports')
@login_required
def reports():
    if not (session.get('role') in FULL_ACCESS_ROLES or session.get('role')=='Branch Manager' or can_view_all()): return redirect('/')
    fd=request.args.get('from_date',str(now_eat().date().replace(day=1))); td=request.args.get('to_date',str(now_eat().date())); rt=request.args.get('type','attendance')
    records=[]; srecs=[]; brecs=[]
    if rt=='attendance':
        for rec in safe_data(execute_query(supabase.table('attendance').select('*').gte('date',fd).lte('date',td).order('date',desc=True).limit(200))):
            st=rec.get('status','present'); records.append({'date':rec.get('date',''),'full_name':rec.get('full_name',''),'check_in':rec.get('check_in','—'),'check_out':rec.get('check_out','—'),'status':st,'label':{'present':'Present','late':'Arrived Late'}.get(st,st)})
    elif rt=='sales':
        srecs=safe_data(execute_query(supabase.table('sales').select('*').gte('date',fd).lte('date',td).order('date',desc=True).limit(200)))
        brecs=safe_data(execute_query(supabase.table('branch_sales').select('*').gte('date',fd).lte('date',td).order('date',desc=True).limit(200)))
    return render_template('reports.html',records=records,sales_recs=srecs,branch_recs=brecs,from_date=fd,to_date=td,report_type=rt,total_sales_amount=sum(float(s.get('total_sales',0)) for s in srecs),total_branch_amount=sum(float(s.get('total_sales',0)) for s in brecs),company=COMPANY_NAME)

# ═══════════════ LEAVES ═══════════════
@app.route('/leaves', methods=['GET','POST'])
@login_required
def leaves():
    un = session.get('user')
    role = session.get('role')
    today = str(now_eat().date())
    if request.method == 'POST':
        leave_start = request.form.get('leave_start','')
        leave_end = request.form.get('leave_end','')
        leave_date = leave_start if leave_start else request.form.get('leave_date','')
        if leave_date:
            supabase.table('leaves').insert({
                'full_name': un,
                'role': role,
                'branch': session.get('branch', ''),
                'leave_date': leave_date,
                'leave_start': leave_start,
                'leave_end': leave_end,
                'total_days': int(request.form.get('total_days', 1)),
                'leave_type': request.form.get('leave_type', 'Annual Leave'),
                'reason': request.form.get('reason', ''),
                'remaining_balance': request.form.get('remaining_balance', ''),
                'handover_notes': request.form.get('handover_notes', ''),
                'backup_person': request.form.get('backup_person', ''),
                'emergency_contact': request.form.get('emergency_contact', ''),
                'department': session.get('department', ''),
                'position': role,
                'phone': request.form.get('phone', ''),
                'email': request.form.get('email', ''),
                'status': 'pending'
            }).execute()
        return redirect('/leaves?success=1')
    my_leaves = safe_data(execute_query(supabase.table('leaves').select('*').eq('full_name',un).order('created_at',desc=True).limit(50)))
    return render_template('leaves.html', leaves=my_leaves, today=today, company=COMPANY_NAME, success_msg=request.args.get('success',''))

@app.route('/leave-pdf/<int:lid>')
@login_required
def leave_pdf(lid):
    leave = safe_data(execute_query(supabase.table('leaves').select('*').eq('id', lid)))
    if not leave: return "Leave not found", 404
    return render_template('leave_pdf.html', lv=leave[0], company=COMPANY_NAME)

@app.route('/approve-leaves')
@login_required
def approve_leaves():
    role = session.get('role')
    ub = session.get('branch','')
    if role not in ['Store Manager','Operations Manager','admin','ceo']: return redirect('/')
    if role == 'Store Manager':
        team_names = [e['full_name'] for e in safe_data(execute_query(supabase.table('employees').select('full_name').eq('status','approved').in_('role', STORE_MANAGER_TEAM).eq('branch',ub)))]
        pending = safe_data(execute_query(supabase.table('leaves').select('*').in_('full_name', team_names).eq('status','pending').order('created_at',desc=True)))
    elif role == 'Operations Manager':
        team_names = [e['full_name'] for e in safe_data(execute_query(supabase.table('employees').select('full_name').eq('status','approved').in_('role', OPERATIONS_MANAGER_TEAM)))]
        pending = safe_data(execute_query(supabase.table('leaves').select('*').in_('full_name', team_names).in_('status', ['pending','approved_by_manager']).order('created_at',desc=True)))
    else:
        pending = safe_data(execute_query(supabase.table('leaves').select('*').in_('status', ['pending','approved_by_manager']).order('created_at',desc=True).limit(100)))
    return render_template('approve_leaves.html', pending=pending, role=role)

@app.route('/approve-leaves/<int:lid>/<action>', methods=['POST'])
@login_required
def process_leave(lid, action):
    role = session.get('role')
    leave = safe_data(execute_query(supabase.table('leaves').select('*').eq('id',lid)))
    if not leave: return redirect('/approve-leaves')
    leave = leave[0]
    new_status = leave['status']
    if action == 'approve':
        if role == 'Store Manager': new_status = 'approved_by_manager'
        elif role in ['Operations Manager','admin','ceo']: new_status = 'approved_final'
        else: return redirect('/approve-leaves')
    elif action == 'reject':
        new_status = 'rejected'
    else:
        return redirect('/approve-leaves')
    supabase.table('leaves').update({'status':new_status,'approved_by':role}).eq('id',lid).execute()
    return redirect('/approve-leaves')

# ═══════════════ ERROR HANDLER ═══════════════
@app.errorhandler(Exception)
def handle_exception(e):
    print(f"Unhandled error: {e}")
    return render_template('error.html', error=str(e)), 500

if __name__=='__main__':
    app.run(host='0.0.0.0',port=5000)
