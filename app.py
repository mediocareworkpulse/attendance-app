from flask import Flask, render_template, request, redirect, url_for, session
from datetime import date, datetime, timedelta, timezone
from supabase import create_client
from functools import wraps
from collections import defaultdict
from werkzeug.security import generate_password_hash, check_password_hash
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
import pytz, time

app = Flask(__name__)
app.secret_key = 'mediocare-attendance-secret-2024'

app.config.update(
    SESSION_COOKIE_HTTPONLY = True,
    SESSION_COOKIE_SECURE = True,
    SESSION_COOKIE_SAMESITE = 'Lax'
)

limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=["200 per day", "50 per hour"]
)

SUPABASE_URL = 'https://lznqrkujlrcxcxizygzq.supabase.co'
SUPABASE_KEY = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Imx6bnFya3VqbHJjeGN4aXp5Z3pxIiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODQ1NjIwNjUsImV4cCI6MjEwMDEzODA2NX0.Jj_EW42NVMQk6zbEcNoY-IlrSe0tgW4zFiKoBSapiDA'

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
EAT = timezone(timedelta(hours=3))

DEPARTMENTS = ['Staff','Store','Dispatch','Sales','Stock Control','Procurement','Accounts Office','Operations','Branch Management','Management']
ALL_ROLES = [
    'Staff','Branch Manager','Branch Order Processor','Stock Controller','Assistant Stock Controller',
    'Procurement Officer','Accountant','Accountant Assistant',
    'HR','HR Assistant','Sales Manager','Marketers','Telesales','Dispatch Personnel',
    'Operations Manager','Assistant Operations Manager','Store Manager','Storekeeper',
    'Store Personnel','Dispatch Supervisor','Dispatch Assistant','Cleaner',
    'Riders','Drivers','Security','admin','ceo'
]
NO_CHECKIN_ROLES = ['admin','ceo']
FULL_ACCESS_ROLES = ['admin','ceo']
SALES_SUBMIT_ROLES = ['Staff','Branch Manager']
SALES_VIEW_ROLES = ['admin','ceo','Stock Controller','Assistant Stock Controller','Accountant','Accountant Assistant']
STORE_MANAGER_TEAM = ['Store Assistant','Store Personnel','Storekeeper']
OPERATIONS_MANAGER_TEAM = [
    'Store Manager','Store Assistant','Store Personnel','Storekeeper',
    'Dispatch Supervisor','Dispatch Assistant','Dispatch Personnel',
    'Riders','Drivers','Security','Cleaner'
]
RIDER_DRIVER_ROLES = ['Riders','Drivers']
MARKETER_ROLE = 'Marketers'
SALES_MANAGER_ROLE = 'Sales Manager'
TARGET_SETTER_ROLES = ['Stock Controller','Assistant Stock Controller','Sales Manager']

DIRECTORATE_ROLES = ['admin','ceo','HR','HR Assistant','Stock Controller','Assistant Stock Controller','Operations Manager','Sales Manager','Assistant Operations Manager']

COMPANY_NAME = 'Mediocare Pharmaceutical Ltd'
LATE_GRACE_MINUTES = 30

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
    names = [b['name'] for b in get_branches()]
    if 'Head Office' not in names:
        names.insert(0, 'Head Office')
    return names

def now_eat():
    return datetime.now(EAT)

# ---------- DELEGATION HELPERS ----------
def get_active_delegation(user_id):
    """Return the role this user is currently delegated (if any), else None."""
    data = safe_data(execute_query(
        supabase.table('role_delegations')
               .select('role')
               .eq('delegate_id', user_id)
               .eq('active', True)
               .maybe_single()
    ))
    return data.get('role') if data else None

def get_effective_roles():
    """Return a list of roles the current user effectively has (own + delegated)."""
    own_role = session.get('role','')
    roles = [own_role]
    emp = safe_data(execute_query(
        supabase.table('employees').select('id').eq('full_name', session.get('user')).limit(1)
    ))
    if emp:
        del_role = get_active_delegation(emp[0]['id'])
        if del_role:
            roles.append(del_role)
    return roles

# ---------- LEAVE APPROVAL CHAIN ----------
def get_approval_chain(employee_role):
    chain = []
    if employee_role in ['Drivers','Riders','Dispatch Personnel','Security','Cleaner']:
        chain = [
            {'from_status': 'pending', 'to_status': 'approved_by_manager',
             'allowed_roles': ['Operations Manager','Assistant Operations Manager']},
            {'from_status': 'approved_by_manager', 'to_status': 'approved_final',
             'allowed_roles': ['HR','HR Assistant']}
        ]
    elif employee_role == 'Store Manager':
        chain = [
            {'from_status': 'pending', 'to_status': 'approved_by_manager',
             'allowed_roles': ['Operations Manager','Assistant Operations Manager']},
            {'from_status': 'approved_by_manager', 'to_status': 'approved_by_procurement',
             'allowed_roles': ['Procurement Officer']},
            {'from_status': 'approved_by_procurement', 'to_status': 'approved_final',
             'allowed_roles': ['HR','HR Assistant']}
        ]
    elif employee_role == 'Branch Manager':
        chain = [
            {'from_status': 'pending', 'to_status': 'approved_by_manager',
             'allowed_roles': ['Stock Controller','Assistant Stock Controller']},
            {'from_status': 'approved_by_manager', 'to_status': 'approved_final',
             'allowed_roles': ['CEO','HR','HR Assistant']}
        ]
    elif employee_role == 'Assistant Operations Manager':
        chain = [
            {'from_status': 'pending', 'to_status': 'approved_by_manager',
             'allowed_roles': ['Operations Manager']},
            {'from_status': 'approved_by_manager', 'to_status': 'approved_final',
             'allowed_roles': ['CEO','HR','HR Assistant']}
        ]
    elif employee_role == 'Marketers':
        chain = [
            {'from_status': 'pending', 'to_status': 'approved_by_manager',
             'allowed_roles': ['Sales Manager']},
            {'from_status': 'approved_by_manager', 'to_status': 'approved_final',
             'allowed_roles': ['HR','HR Assistant']}
        ]
    elif employee_role == 'Telesales':
        chain = [
            {'from_status': 'pending', 'to_status': 'approved_by_manager',
             'allowed_roles': ['Sales Manager']},
            {'from_status': 'approved_by_manager', 'to_status': 'approved_final',
             'allowed_roles': ['HR','HR Assistant']}
        ]
    elif employee_role == 'Branch Order Processor':
        chain = [
            {'from_status': 'pending', 'to_status': 'approved_by_manager',
             'allowed_roles': ['Operations Manager','Assistant Operations Manager']},
            {'from_status': 'approved_by_manager', 'to_status': 'approved_final',
             'allowed_roles': ['HR','HR Assistant']}
        ]
    elif employee_role in ['Store Personnel','Storekeeper','Store Assistant']:
        chain = [
            {'from_status': 'pending', 'to_status': 'approved_by_manager',
             'allowed_roles': ['Store Manager']},
            {'from_status': 'approved_by_manager', 'to_status': 'approved_by_ops',
             'allowed_roles': ['Operations Manager','Assistant Operations Manager']},
            {'from_status': 'approved_by_ops', 'to_status': 'approved_final',
             'allowed_roles': ['HR','HR Assistant']}
        ]
    elif employee_role in ['Stock Controller','Assistant Stock Controller',
                           'Accountant','Accountant Assistant',
                           'Operations Manager','Procurement Officer','Sales Manager']:
        chain = [
            {'from_status': 'pending', 'to_status': 'approved_final',
             'allowed_roles': ['CEO','HR','HR Assistant']}
        ]
    elif employee_role in ['HR','HR Assistant']:
        chain = [
            {'from_status': 'pending', 'to_status': 'approved_final',
             'allowed_roles': ['CEO']}
        ]
    else:
        chain = [
            {'from_status': 'pending', 'to_status': 'approved_by_manager',
             'allowed_roles': ['Branch Manager']},
            {'from_status': 'approved_by_manager', 'to_status': 'approved_final',
             'allowed_roles': ['Stock Controller','Assistant Stock Controller']}
        ]
    for stage in chain:
        if 'admin' not in stage['allowed_roles']:
            stage['allowed_roles'].append('admin')
        if 'ceo' not in stage['allowed_roles']:
            stage['allowed_roles'].append('ceo')
    return chain

# ---------- Force logout blocked users ----------
@app.before_request
def block_check():
    if 'user' in session and request.path not in ['/login','/logout','/static','/favicon.ico']:
        emp = safe_data(execute_query(
            supabase.table('employees').select('blocked').eq('full_name', session['user']).limit(1)
        ))
        if emp and emp[0].get('blocked'):
            session.clear()
            return redirect('/login')

# ---------- AUTH ----------
@app.route('/login', methods=['GET','POST'])
@limiter.limit("5 per minute")
def login():
    if request.method == 'POST':
        name = request.form.get('full_name','').strip()
        pw = request.form.get('password','').strip()
        r = execute_query(supabase.table('employees').select('*').eq('full_name',name))
        data = safe_data(r)
        if data:
            emp = data[0]
            if emp.get('blocked') == True:
                return render_template('login.html', error='Account suspended. Contact admin.')
            stored_pw = emp.get('password','')
            if check_password_hash(stored_pw, pw):
                pass
            elif stored_pw == pw:
                supabase.table('employees').update({'password': generate_password_hash(pw)}).eq('id', emp['id']).execute()
            else:
                return render_template('login.html', error='Invalid credentials.')
            if emp.get('status','') not in ['','approved']:
                return render_template('login.html', error='Account pending approval.')
            session['user'] = emp['full_name']
            session['role'] = emp.get('role','Staff')
            session['department'] = emp.get('department','')
            session['branch'] = emp.get('branch','')
            session['shift_end'] = emp.get('shift_end','17:00')
            session['shift_start'] = emp.get('shift_start','08:00')
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
            'full_name':name,'phone':phone,'password': generate_password_hash(pw),
            'department':dept,'branch':branch,'role':role,
            'status':'pending','shift_start':shift_start,'shift_end':shift_end
        }).execute()
        return render_template('signup.html', branches=get_branch_names(), departments=DEPARTMENTS, roles=signup_roles,
            success='Registration submitted! Welcome to {}!'.format(COMPANY_NAME))
    return render_template('signup.html', branches=get_branch_names(), departments=DEPARTMENTS, roles=signup_roles)

# ---------- DASHBOARD ----------
@app.route('/')
@login_required
def home():
    today = str(now_eat().date())
    role = session.get('role','Staff')
    ub = session.get('branch','')
    un = session.get('user','')

    show_sales_card = (
        role in ['Staff','Branch Manager','admin','ceo'] or
        session.get('department','') in ['Stock Control','Stock Assistant','Accounts Office','Accountant','Accountant Assistant']
    )

    if role in FULL_ACCESS_ROLES or role in ['HR','HR Assistant'] or can_view_all():
        emp_r = execute_query(supabase.table('employees').select('id').eq('status','approved').eq('blocked',False))
        att_r = execute_query(supabase.table('attendance').select('*').eq('date',today).limit(50))
        sales_r = execute_query(supabase.table('sales').select('total_sales').eq('date',today))
    elif role in ['Store Manager','Operations Manager','Assistant Operations Manager']:
        team_names = [e['full_name'] for e in safe_data(execute_query(supabase.table('employees').select('full_name').eq('status','approved').in_('role',OPERATIONS_MANAGER_TEAM)))]
        att_r = execute_query(supabase.table('attendance').select('*').eq('date',today).in_('full_name',team_names))
        sales_r = execute_query(supabase.table('sales').select('total_sales').eq('date',today).in_('full_name',team_names)) if show_sales_card else []
        emp_r = execute_query(supabase.table('employees').select('id').eq('status','approved').in_('role',OPERATIONS_MANAGER_TEAM))
    elif role == 'Sales Manager':
        team_names = [e['full_name'] for e in safe_data(execute_query(supabase.table('employees').select('full_name').eq('status','approved').in_('role',[MARKETER_ROLE,'Telesales'])))]
        team_names.append(un)
        att_r = execute_query(supabase.table('attendance').select('*').eq('date',today).in_('full_name',team_names))
        sales_r = execute_query(supabase.table('sales').select('total_sales').eq('date',today).in_('full_name',team_names)) if show_sales_card else []
        emp_r = execute_query(supabase.table('employees').select('id').eq('status','approved').in_('full_name',team_names))
    elif role == 'Branch Manager':
        team_names = [e['full_name'] for e in safe_data(execute_query(supabase.table('employees').select('full_name').eq('status','approved').eq('branch',ub)))]
        att_r = execute_query(supabase.table('attendance').select('*').eq('date',today).in_('full_name',team_names))
        sales_r = execute_query(supabase.table('sales').select('total_sales').eq('date',today).in_('full_name',team_names)) if show_sales_card else []
        emp_r = execute_query(supabase.table('employees').select('id').eq('status','approved').eq('branch',ub))
    else:
        emp_r = None
        att_r = execute_query(supabase.table('attendance').select('*').eq('date',today).eq('full_name',un))
        sales_r = execute_query(supabase.table('sales').select('total_sales').eq('date',today).eq('full_name',un))

    total_emp = len(safe_data(emp_r)) if emp_r else 0
    att_data = safe_data(att_r)
    working = sum(1 for a in att_data if a.get('check_in') and not a.get('check_out'))
    checked_out = sum(1 for a in att_data if a.get('check_out'))
    late_count = sum(1 for a in att_data if a.get('status')=='late')
    total_sales = sum(float(s.get('total_sales',0)) for s in safe_data(sales_r)) if show_sales_card else 0

    leaves_today = safe_data(execute_query(
        supabase.table('leaves').select('full_name').eq('leave_date',today).in_('status',['approved_final','approved_by_manager'])
    ))
    on_leave_count = len(leaves_today)

    my_leaves = safe_data(execute_query(
        supabase.table('leaves').select('*').eq('full_name',un)
        .in_('status',['approved_final','approved_by_manager'])
        .gte('leave_end',today)
        .order('leave_start')
        .limit(1)
    ))
    leave_remaining = None
    if my_leaves:
        lv = my_leaves[0]
        end_date = datetime.strptime(lv['leave_end'], '%Y-%m-%d').date()
        remaining_days = (end_date - now_eat().date()).days
        if remaining_days >= 0:
            leave_remaining = {'end_date': lv['leave_end'], 'days': remaining_days}

    records = []
    for rec in att_data[:10]:
        st = rec.get('status','present')
        if rec.get('check_out'): label = 'Checked Out'
        elif st == 'late': label = 'Arrived Late'
        else: label = 'Working'
        try:
            emp_detail = safe_data(execute_query(supabase.table('employees').select('role,department').eq('full_name',rec['full_name'])))
        except: emp_detail = []
        role_disp = emp_detail[0].get('role','') if emp_detail else ''
        dept_disp = emp_detail[0].get('department','') if emp_detail else rec.get('department','')
        records.append({
            'full_name':rec['full_name'],'department':dept_disp,'role':role_disp,
            'check_in':rec.get('check_in','—'),'check_out':rec.get('check_out','—'),
            'status':st,'label':label
        })

    uci=uco=False; user_status=''
    if role not in NO_CHECKIN_ROLES:
        my = safe_data(execute_query(supabase.table('attendance').select('*').eq('full_name',un).eq('date',today)))
        if my:
            uci = bool(my[0].get('check_in'))
            uco = bool(my[0].get('check_out'))
            if uco: user_status = 'Checked Out'
            elif uci: user_status = 'Working'
            else: user_status = 'Not Checked In'

    pending = len(safe_data(execute_query(supabase.table('employees').select('id').eq('status','pending')))) if role in FULL_ACCESS_ROLES else 0

    target_achieved = False
    if role in SALES_SUBMIT_ROLES:
        month_str = str(now_eat().date().replace(day=1))
        target = safe_data(execute_query(supabase.table('sales_targets').select('target_amount').eq('full_name',un).eq('month',month_str).limit(1)))
        if target:
            target_amt = float(target[0]['target_amount'])
            ms = today.replace(day=1)
            my_sales = safe_data(execute_query(supabase.table('sales').select('total_sales').eq('full_name',un).gte('date',str(ms)).lte('date',today)))
            month_total = sum(float(s['total_sales']) for s in my_sales)
            if month_total >= target_amt and target_amt > 0:
                target_achieved = True

    return render_template('index.html',
        total_employees=total_emp, working=working, checked_out=checked_out,
        late_count=late_count, on_leave_count=on_leave_count,
        total_sales=total_sales, recent_records=records,
        user_checked_in=uci, user_checked_out=uco, user_status=user_status,
        pending_count=pending, show_sales_card=show_sales_card,
        target_achieved=target_achieved, leave_remaining=leave_remaining,
        company=COMPANY_NAME)

# ---------- ADMIN PANEL ----------
@app.route('/admin')
@login_required
@admin_required
def admin_panel():
    total_emp = len(safe_data(execute_query(supabase.table('employees').select('id').eq('status','approved'))))
    pending = len(safe_data(execute_query(supabase.table('employees').select('id').eq('status','pending'))))
    blocked_count = len(safe_data(execute_query(supabase.table('employees').select('id').eq('blocked',True))))
    total_branches = len(get_branches())
    att_today = len(safe_data(execute_query(supabase.table('attendance').select('id').eq('date',str(now_eat().date())))))
    return render_template('admin.html', total_employees=total_emp, pending_count=pending,
                         blocked_count=blocked_count, total_branches=total_branches,
                         att_today=att_today, company=COMPANY_NAME)

@app.route('/admin/block/<int:eid>', methods=['POST'])
@login_required
@admin_required
def block_employee(eid):
    supabase.table('employees').update({'blocked':True}).eq('id',eid).execute()
    return redirect('/employees')

@app.route('/admin/unblock/<int:eid>', methods=['POST'])
@login_required
@admin_required
def unblock_employee(eid):
    supabase.table('employees').update({'blocked':False}).eq('id',eid).execute()
    return redirect('/employees')

# ---------- APPROVALS (employee registration) ----------
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

# ---------- ADMIN SALES MANAGEMENT ----------
@app.route('/admin/sales')
@login_required
@admin_required
def admin_sales():
    fd = request.args.get('from_date','')
    td = request.args.get('to_date','')
    if fd and td:
        sales = safe_data(execute_query(
            supabase.table('sales').select('*').gte('date',fd).lte('date',td).order('date',desc=True).limit(500)
        ))
    else:
        sales = safe_data(execute_query(
            supabase.table('sales').select('*').order('date',desc=True).limit(200)
        ))
    return render_template('admin_sales.html', sales=sales, from_date=fd, to_date=td, company=COMPANY_NAME)

@app.route('/admin/sales/delete/<int:sid>', methods=['POST'])
@login_required
@admin_required
def delete_sale(sid):
    supabase.table('sales').delete().eq('id',sid).execute()
    return redirect(request.referrer or '/admin/sales')

# ---------- EMPLOYEES ----------
@app.route('/employees')
@login_required
@admin_required
def employees_page():
    emps = safe_data(execute_query(supabase.table('employees').select('*').order('full_name').limit(200)))
    return render_template('employees.html', employees=emps, branches=get_branch_names(),
                         departments=DEPARTMENTS, roles=ALL_ROLES, company=COMPANY_NAME)

@app.route('/employees/add', methods=['POST'])
@login_required
@admin_required
def add_employee():
    d = {
        'full_name':request.form.get('full_name','').strip(),
        'department':request.form.get('department','').strip(),
        'branch':request.form.get('branch','').strip(),
        'role':request.form.get('role','Staff').strip(),
        'password': generate_password_hash(request.form.get('password','1234').strip()),
        'status':'approved','blocked':False
    }
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
        supabase.table('journeys').delete().eq('full_name',n).execute()
        supabase.table('marketer_checkins').delete().eq('full_name',n).execute()
        supabase.table('customer_reports').delete().eq('full_name',n).execute()
        supabase.table('marketer_locations').delete().eq('full_name',n).execute()
        supabase.table('contacts').delete().eq('full_name',n).execute()
    supabase.table('employees').delete().eq('id',eid).execute()
    return redirect('/employees')

@app.route('/employees/edit/<int:eid>', methods=['POST'])
@login_required
@admin_required
def edit_employee(eid):
    data = {
        'full_name':request.form.get('full_name','').strip(),
        'department':request.form.get('department','').strip(),
        'branch':request.form.get('branch','').strip(),
        'role':request.form.get('role','Staff').strip(),
        'shift_start':request.form.get('shift_start','08:00').strip(),
        'shift_end':request.form.get('shift_end','17:00').strip(),
        'updated_at':now_eat().isoformat()
    }
    new_pw = request.form.get('password','').strip()
    if new_pw:
        data['password'] = generate_password_hash(new_pw)
    if data['full_name']:
        supabase.table('employees').update(data).eq('id',eid).execute()
    return redirect('/employees')

# ---------- BRANCHES ----------
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

# ---------- DIRECTORATE (Contacts) ----------
@app.route('/contacts')
@login_required
def contacts_page():
    allowed_roles = DIRECTORATE_ROLES + ['Procurement Officer']
    if session.get('role') not in allowed_roles:
        return redirect('/')
    user_role = session.get('role')
    if user_role == 'Sales Manager':
        contacts = safe_data(execute_query(
            supabase.table('contacts').select('*').eq('role', 'Marketers').order('full_name')
        ))
    elif user_role == 'Assistant Operations Manager':
        contacts = safe_data(execute_query(
            supabase.table('contacts').select('*').in_('role', OPERATIONS_MANAGER_TEAM).order('full_name')
        ))
    elif user_role == 'Procurement Officer':
        contacts = safe_data(execute_query(
            supabase.table('contacts').select('*').eq('role', 'Branch Manager').order('full_name')
        ))
    else:
        contacts = safe_data(execute_query(
            supabase.table('contacts').select('*').order('full_name')
        ))
    return render_template('contacts.html', contacts=contacts, company=COMPANY_NAME)

# ---------- CHECK IN / OUT ----------
@app.route('/check-in')
@login_required
def check_in_page():
    today = str(now_eat().date())
    role = session.get('role')
    un = session.get('user')
    ub = session.get('branch','')

    marketer_pending = False; marketer_approved = False
    if role == MARKETER_ROLE:
        mc = safe_data(execute_query(supabase.table('marketer_checkins').select('*').eq('full_name',un).eq('date',today).order('created_at',desc=True).limit(1)))
        if mc:
            if mc[0]['status'] == 'approved': marketer_approved = True
            elif mc[0]['status'] == 'pending': marketer_pending = True

    emp = safe_data(execute_query(supabase.table('employees').select('shift_start,shift_end,role,department,branch').eq('full_name',un)))
    emp_info = emp[0] if emp else {}
    shift_start = emp_info.get('shift_start','08:00') if role not in RIDER_DRIVER_ROLES + [MARKETER_ROLE] else None
    shift_end = emp_info.get('shift_end','17:00') if role not in RIDER_DRIVER_ROLES + [MARKETER_ROLE] else None

    my_att = safe_data(execute_query(supabase.table('attendance').select('*').eq('full_name',un).eq('date',today)))
    current_status = 'none'; check_in_time = None
    if my_att:
        rec = my_att[0]
        if rec.get('check_out'): current_status = 'completed'
        elif rec.get('check_in'):
            current_status = 'checked_in'
            check_in_time = rec.get('check_in')

    if role == MARKETER_ROLE:
        if marketer_approved: current_status = 'approved'
        elif marketer_pending: current_status = 'pending'
        else: current_status = 'none'

    journeys = []
    if role in RIDER_DRIVER_ROLES:
        journeys = safe_data(execute_query(supabase.table('journeys').select('*').eq('full_name',un).eq('date',today).order('journey_number')))

    if role in FULL_ACCESS_ROLES or role in ['HR','HR Assistant']:
        r = safe_data(execute_query(supabase.table('attendance').select('*').eq('date',today).limit(50)))
    elif role in ['Store Manager','Operations Manager','Assistant Operations Manager']:
        team_names = [e['full_name'] for e in safe_data(execute_query(supabase.table('employees').select('full_name').eq('status','approved').in_('role',OPERATIONS_MANAGER_TEAM)))]
        r = safe_data(execute_query(supabase.table('attendance').select('*').eq('date',today).in_('full_name',team_names)))
    elif role == 'Sales Manager':
        team_names = [e['full_name'] for e in safe_data(execute_query(supabase.table('employees').select('full_name').eq('status','approved').in_('role',[MARKETER_ROLE,'Telesales'])))]
        team_names.append(un)
        r = safe_data(execute_query(supabase.table('attendance').select('*').eq('date',today).in_('full_name',team_names)))
    elif role == 'Branch Manager':
        team_names = [e['full_name'] for e in safe_data(execute_query(supabase.table('employees').select('full_name').eq('status','approved').eq('branch',ub)))]
        r = safe_data(execute_query(supabase.table('attendance').select('*').eq('date',today).in_('full_name',team_names)))
    elif role in ['Stock Controller','Assistant Stock Controller']:
        r = safe_data(execute_query(supabase.table('attendance').select('*').eq('date',today).limit(50)))
    else:
        r = my_att

    records = []
    for rec in r:
        st = rec.get('status','present')
        if rec.get('check_out'): label = 'Checked Out'
        elif st == 'late': label = 'Arrived Late'
        else: label = 'Working'
        try:
            emp_det = safe_data(execute_query(supabase.table('employees').select('role,department').eq('full_name',rec['full_name'])))
        except: emp_det = []
        role_disp = emp_det[0].get('role','') if emp_det else ''
        dept_disp = emp_det[0].get('department','') if emp_det else rec.get('department','')
        records.append({
            'full_name':rec['full_name'],'department':dept_disp,'role':role_disp,
            'check_in':rec.get('check_in','—'),'check_out':rec.get('check_out','—'),
            'status':st,'label':label
        })

    return render_template('check_in.html',
        records=records, user_status=current_status, today=today, company=COMPANY_NAME,
        check_in_time=check_in_time, shift_start=shift_start, shift_end=shift_end,
        journeys=journeys, role=role)

@app.route('/check-in', methods=['POST'])
@login_required
def process_attendance():
    if session.get('role') in NO_CHECKIN_ROLES:
        return redirect('/')
    un = session.get('user')
    action = request.form.get('action')
    today = str(now_eat().date())
    now = now_eat().strftime('%H:%M:%S')
    lat = request.form.get('lat', '') or '0'
    lng = request.form.get('lng', '') or '0'
    loc = request.form.get('location', '') or 'Not provided'
    emp = safe_data(execute_query(supabase.table('employees').select('department,branch,shift_start,role').eq('full_name', un)))
    if not emp:
        return redirect('/check-in')
    dept = emp[0].get('department', '') or ''
    branch = emp[0].get('branch', '') or ''
    role = emp[0].get('role', '') or ''
    shift_start = emp[0].get('shift_start', '08:00') or '08:00'
    shift_start = shift_start.strip()
    if len(shift_start) > 5:
        shift_start = shift_start[:5]
    if not shift_start or ':' not in shift_start:
        shift_start = '08:00'

    existing = safe_data(execute_query(supabase.table('attendance').select('*').eq('full_name', un).eq('date', today)))
    exd = existing[0] if existing else None

    if action == 'check_in':
        if role == MARKETER_ROLE:
            return redirect('/check-in')
        if exd and exd.get('check_in'):
            return redirect('/check-in')
        late_threshold = (datetime.strptime(shift_start, '%H:%M') + timedelta(minutes=LATE_GRACE_MINUTES)).strftime('%H:%M')
        status = 'late' if now[:5] > late_threshold else 'present'
        d = {'check_in': now, 'status': status, 'check_in_lat': lat, 'check_in_lng': lng, 'check_in_location': loc}
        if exd:
            supabase.table('attendance').update(d).eq('full_name', un).eq('date', today).execute()
        else:
            d.update({'full_name': un, 'department': dept, 'branch': branch, 'date': today})
            supabase.table('attendance').insert(d).execute()
    elif action == 'check_out':
        if exd and exd.get('check_in') and not exd.get('check_out'):
            supabase.table('attendance').update({
                'check_out': now, 'status': 'checked_out',
                'check_out_lat': lat, 'check_out_lng': lng, 'check_out_location': loc
            }).eq('full_name', un).eq('date', today).execute()
            return redirect('/')
    return redirect('/check-in')

# ---------- JOURNEY ROUTES ----------
@app.route('/journey/start', methods=['POST'])
@login_required
def start_journey():
    if session.get('role') not in RIDER_DRIVER_ROLES: return redirect('/check-in')
    un = session.get('user'); today = str(now_eat().date()); now = now_eat().strftime('%H:%M:%S')
    lat = request.form.get('lat',''); lng = request.form.get('lng',''); loc = request.form.get('location','')
    existing = safe_data(execute_query(supabase.table('journeys').select('journey_number').eq('full_name',un).eq('date',today).order('journey_number', desc=True).limit(1)))
    next_num = (existing[0]['journey_number'] + 1) if existing else 1
    supabase.table('journeys').insert({
        'full_name': un, 'date': today, 'journey_number': next_num,
        'start_time': now, 'start_lat': lat, 'start_lng': lng, 'start_location': loc, 'status': 'active'
    }).execute()
    return redirect('/check-in')

@app.route('/journey/end/<int:jid>', methods=['POST'])
@login_required
def end_journey(jid):
    if session.get('role') not in RIDER_DRIVER_ROLES: return redirect('/check-in')
    now = now_eat().strftime('%H:%M:%S')
    lat = request.form.get('lat',''); lng = request.form.get('lng',''); loc = request.form.get('location','')
    supabase.table('journeys').update({
        'end_time': now, 'end_lat': lat, 'end_lng': lng, 'end_location': loc, 'status': 'completed'
    }).eq('id', jid).execute()
    return redirect('/check-in')

# ---------- ATTENDANCE HISTORY ----------
@app.route('/attendance-history')
@login_required
def attendance_history():
    role = session.get('role'); un = session.get('user'); ub = session.get('branch','')
    period = request.args.get('period','month')
    fd = request.args.get('from_date',''); td = request.args.get('to_date','')
    today = now_eat().date()
    if fd and td: sd, ed = fd, td
    elif period == 'week': sd = str(today - timedelta(days=7)); ed = str(today)
    elif period == 'month': sd = str(today.replace(day=1)); ed = str(today)
    elif period == 'last_month':
        first_of_month = today.replace(day=1)
        last_month_end = first_of_month - timedelta(days=1)
        last_month_start = last_month_end.replace(day=1)
        sd = str(last_month_start); ed = str(last_month_end)
    else: sd = str(today - timedelta(days=30)); ed = str(today)

    if role in FULL_ACCESS_ROLES or role in ['HR','HR Assistant']:
        r = safe_data(execute_query(supabase.table('attendance').select('*').gte('date',sd).lte('date',ed).order('date',desc=True).limit(200)))
    elif role in ['Store Manager','Operations Manager','Assistant Operations Manager']:
        team_names = [e['full_name'] for e in safe_data(execute_query(supabase.table('employees').select('full_name').eq('status','approved').in_('role',OPERATIONS_MANAGER_TEAM)))]
        r = safe_data(execute_query(supabase.table('attendance').select('*').gte('date',sd).lte('date',ed).in_('full_name',team_names).order('date',desc=True).limit(200)))
    elif role == 'Sales Manager':
        team_names = [e['full_name'] for e in safe_data(execute_query(supabase.table('employees').select('full_name').eq('status','approved').in_('role',[MARKETER_ROLE,'Telesales'])))]
        team_names.append(un)
        r = safe_data(execute_query(supabase.table('attendance').select('*').gte('date',sd).lte('date',ed).in_('full_name',team_names).order('date',desc=True).limit(200)))
    elif role == 'Branch Manager':
        team_names = [e['full_name'] for e in safe_data(execute_query(supabase.table('employees').select('full_name').eq('status','approved').eq('branch',ub)))]
        r = safe_data(execute_query(supabase.table('attendance').select('*').gte('date',sd).lte('date',ed).in_('full_name',team_names).order('date',desc=True).limit(200)))
    elif role in ['Stock Controller','Assistant Stock Controller']:
        r = safe_data(execute_query(supabase.table('attendance').select('*').gte('date',sd).lte('date',ed).order('date',desc=True).limit(200)))
    else:
        r = safe_data(execute_query(supabase.table('attendance').select('*').gte('date',sd).lte('date',ed).eq('full_name',un).order('date',desc=True).limit(200)))

    records = []
    for rec in r:
        st = rec.get('status','present')
        if rec.get('check_out'): label = 'Checked Out'
        elif st == 'late': label = 'Arrived Late'
        else: label = 'Working'
        records.append({
            'date':rec.get('date',''),'full_name':rec.get('full_name',''),
            'check_in':rec.get('check_in','—'),'check_out':rec.get('check_out','—'),
            'status':st,'label':label
        })
    return render_template('attendance_history.html', records=records, period=period,
                         from_date=sd, to_date=ed, today=str(today), company=COMPANY_NAME)

# ---------- SALES (individual & branch modules with full filtering) ----------
@app.route('/sales', methods=['GET','POST'])
@login_required
def sales_page():
    role = session.get('role'); un = session.get('user'); ub = session.get('branch','')
    today = str(now_eat().date())

    if request.method == 'POST':
        sales_type = request.form.get('sales_type','individual')
        if sales_type == 'individual' and role in SALES_SUBMIT_ROLES:
            try:
                mpesa = float(request.form.get('mpesa_sales','0') or 0)
                cash  = float(request.form.get('cash_sales','0') or 0)
                notes = request.form.get('notes','')
                expense_names  = request.form.getlist('expense_name[]')
                expense_amounts = request.form.getlist('expense_amount[]')
                expenses = []
                expense_total = 0.0
                for i in range(len(expense_names)):
                    nm = expense_names[i].strip()
                    amt_str = expense_amounts[i] if i < len(expense_amounts) else '0'
                    try: amt = float(amt_str) if amt_str else 0.0
                    except: amt = 0.0
                    if nm and amt > 0:
                        expenses.append({'name': nm, 'amount': amt})
                        expense_total += amt
                total = mpesa + cash + expense_total
                emp = safe_data(execute_query(
                    supabase.table('employees').select('department,branch').eq('full_name', un)
                ))
                if emp and total > 0:
                    supabase.table('sales').insert({
                        'full_name': un,
                        'department': emp[0].get('department',''),
                        'branch': emp[0].get('branch',''),
                        'date': today,
                        'mpesa_sales': mpesa,
                        'cash_sales': cash,
                        'total_sales': total,
                        'sales_type': 'individual',
                        'notes': notes,
                        'expenses': expenses
                    }).execute()
            except Exception as e:
                print(f"Individual sale error: {e}")
        elif sales_type == 'branch' and role == 'Branch Manager':
            try:
                mpesa = float(request.form.get('mpesa_sales','0') or 0)
                cash  = float(request.form.get('cash_sales','0') or 0)
                notes = request.form.get('notes','')
                expense_names  = request.form.getlist('expense_name[]')
                expense_amounts = request.form.getlist('expense_amount[]')
                expenses = []
                expense_total = 0.0
                for i in range(len(expense_names)):
                    nm = expense_names[i].strip()
                    amt_str = expense_amounts[i] if i < len(expense_amounts) else '0'
                    try: amt = float(amt_str) if amt_str else 0.0
                    except: amt = 0.0
                    if nm and amt > 0:
                        expenses.append({'name': nm, 'amount': amt})
                        expense_total += amt
                total = mpesa + cash + expense_total
                if total > 0:
                    supabase.table('branch_sales').insert({
                        'branch': ub,
                        'date': today,
                        'mpesa_sales': mpesa,
                        'cash_sales': cash,
                        'total_sales': total,
                        'submitted_by': un,
                        'notes': notes,
                        'expenses': expenses
                    }).execute()
            except Exception as e:
                print(f"Branch sale error: {e}")
        return redirect('/sales?success=1')

    # View sales
    if role == 'Branch Manager':
        allowed_branches = [ub]
    else:
        allowed_branches = get_branch_names()

    view_type = request.args.get('view_type','individual')
    filter_branch = request.args.get('branch','')
    filter_employee = request.args.get('employee','')
    filter_from = request.args.get('from_date','')
    filter_to = request.args.get('to_date','')
    period = request.args.get('period','')

    today_date = now_eat().date()
    if period == 'week':
        filter_from = str(today_date - timedelta(days=7))
        filter_to = str(today_date)
    elif period == 'month':
        filter_from = str(today_date.replace(day=1))
        filter_to = str(today_date)
    elif period == 'year':
        filter_from = str(today_date.replace(month=1, day=1))
        filter_to = str(today_date)
    elif not filter_from:
        filter_from = str(today_date)
    if not filter_to:
        filter_to = str(today_date)

    ind_query = supabase.table('sales').select('*')
    if view_type == 'individual':
        if filter_branch and filter_branch in allowed_branches:
            ind_query = ind_query.eq('branch', filter_branch)
        elif role == 'Branch Manager':
            ind_query = ind_query.eq('branch', ub)
        if filter_employee:
            ind_query = ind_query.eq('full_name', filter_employee)
        if role not in (FULL_ACCESS_ROLES + ['Stock Controller','Assistant Stock Controller','Accountant','Accountant Assistant','Branch Manager']):
            ind_query = ind_query.eq('full_name', un)
        ind_query = ind_query.gte('date', filter_from).lte('date', filter_to).order('date', desc=True).limit(500)
        individual_sales = safe_data(execute_query(ind_query))
    else:
        individual_sales = []

    br_query = supabase.table('branch_sales').select('*')
    if view_type == 'branch':
        if filter_branch and filter_branch in allowed_branches:
            br_query = br_query.eq('branch', filter_branch)
        elif role == 'Branch Manager':
            br_query = br_query.eq('branch', ub)
        if filter_employee:
            br_query = br_query.eq('submitted_by', filter_employee)
        if role not in (FULL_ACCESS_ROLES + ['Stock Controller','Assistant Stock Controller','Accountant','Accountant Assistant','Branch Manager']):
            br_query = br_query.eq('branch', '__none__')
        br_query = br_query.gte('date', filter_from).lte('date', filter_to).order('date', desc=True).limit(500)
        branch_sales = safe_data(execute_query(br_query))
    else:
        branch_sales = []

    employee_list = []
    if filter_branch or (role == 'Branch Manager'):
        b = filter_branch if filter_branch else ub
        employee_list = safe_data(execute_query(
            supabase.table('employees').select('full_name').eq('status','approved').eq('branch', b).order('full_name')
        ))
    elif role in (FULL_ACCESS_ROLES + ['Stock Controller','Assistant Stock Controller','Accountant','Accountant Assistant']):
        employee_list = safe_data(execute_query(
            supabase.table('employees').select('full_name').eq('status','approved').order('full_name')
        ))

    branches_for_filter = allowed_branches

    target_progress = None
    month_str = str(now_eat().date().replace(day=1))
    target = safe_data(execute_query(
        supabase.table('sales_targets').select('target_amount').eq('full_name',un).eq('month',month_str).limit(1)
    ))
    if target:
        target_amt = float(target[0]['target_amount'])
        ms = today.replace(day=1)
        my_sales = safe_data(execute_query(
            supabase.table('sales').select('total_sales').eq('full_name',un).gte('date',str(ms)).lte('date',today)
        ))
        month_total = sum(float(s['total_sales']) for s in my_sales)
        remaining = max(0, target_amt - month_total)
        target_progress = {
            'target': target_amt,
            'current': month_total,
            'remaining': remaining,
            'percent': round((month_total / target_amt * 100), 1) if target_amt > 0 else 0,
            'achieved': month_total >= target_amt
        }

    return render_template('sales.html',
        individual_sales=individual_sales,
        branch_sales=branch_sales,
        view_type=view_type,
        filter_branch=filter_branch,
        filter_employee=filter_employee,
        filter_from=filter_from,
        filter_to=filter_to,
        period=period,
        branches=branches_for_filter,
        employees=employee_list,
        target_progress=target_progress,
        today=today,
        company=COMPANY_NAME,
        success_msg=request.args.get('success',''))

# ---------- PROFILE ----------
@app.route('/profile', methods=['GET','POST'])
@login_required
def profile():
    un = session.get('user'); sm = ''
    if request.method == 'POST':
        old_pw = request.form.get('old_password','').strip()
        new_pw = request.form.get('new_password','').strip()
        if old_pw and new_pw:
            emp = safe_data(execute_query(supabase.table('employees').select('password').eq('full_name',un).limit(1)))
            if emp:
                stored = emp[0]['password']
                if check_password_hash(stored, old_pw) or stored == old_pw:
                    supabase.table('employees').update({'password': generate_password_hash(new_pw)}).eq('full_name',un).execute()
                    sm = 'Password updated!'
                else:
                    sm = 'Current password is incorrect.'
    emp = safe_data(execute_query(supabase.table('employees').select('*').eq('full_name',un)))
    ed = emp[0] if emp else {}
    today = now_eat().date(); ms = today.replace(day=1)
    dp = len(set(a['date'] for a in safe_data(execute_query(supabase.table('attendance').select('date,check_in').eq('full_name',un).gte('date',str(ms)).lte('date',str(today)))) if a.get('check_in')))
    tms = sum(float(s.get('total_sales',0)) for s in safe_data(execute_query(supabase.table('sales').select('total_sales').eq('full_name',un).gte('date',str(ms)).lte('date',str(today)))))
    return render_template('profile.html', employee=ed, days_present=dp, total_my_sales=tms, success_msg=sm, company=COMPANY_NAME)

# ---------- REPORTS ----------
@app.route('/reports')
@login_required
def reports():
    if not (session.get('role') in FULL_ACCESS_ROLES or session.get('role')=='Branch Manager' or can_view_all()): return redirect('/')
    fd = request.args.get('from_date',str(now_eat().date().replace(day=1)))
    td = request.args.get('to_date',str(now_eat().date()))
    rt = request.args.get('type','attendance')
    records = []; srecs = []; brecs = []
    if rt == 'attendance':
        for rec in safe_data(execute_query(supabase.table('attendance').select('*').gte('date',fd).lte('date',td).order('date',desc=True).limit(200))):
            st = rec.get('status','present')
            if rec.get('check_out'): label = 'Checked Out'
            elif st == 'late': label = 'Arrived Late'
            else: label = 'Working'
            records.append({'date':rec.get('date',''),'full_name':rec.get('full_name',''),'check_in':rec.get('check_in','—'),'check_out':rec.get('check_out','—'),'status':st,'label':label})
    elif rt == 'sales':
        srecs = safe_data(execute_query(supabase.table('sales').select('*').gte('date',fd).lte('date',td).order('date',desc=True).limit(200)))
        brecs = safe_data(execute_query(supabase.table('branch_sales').select('*').gte('date',fd).lte('date',td).order('date',desc=True).limit(200)))
    return render_template('reports.html',records=records,sales_recs=srecs,branch_recs=brecs,from_date=fd,to_date=td,report_type=rt,total_sales_amount=sum(float(s.get('total_sales',0)) for s in srecs),total_branch_amount=sum(float(s.get('total_sales',0)) for s in brecs),company=COMPANY_NAME)

# ---------- LEAVES ----------
@app.route('/leaves', methods=['GET','POST'])
@login_required
def leaves():
    un = session.get('user'); role = session.get('role'); today = str(now_eat().date())
    if request.method == 'POST':
        leave_start = request.form.get('leave_start',''); leave_end = request.form.get('leave_end','')
        leave_date = leave_start if leave_start else request.form.get('leave_date','')
        if leave_date:
            supabase.table('leaves').insert({
                'full_name': un,'role': role,'branch': session.get('branch',''),
                'leave_date': leave_date,'leave_start': leave_start,'leave_end': leave_end,
                'total_days': int(request.form.get('total_days',1)),
                'leave_type': request.form.get('leave_type','Annual Leave'),
                'reason': request.form.get('reason',''),
                'remaining_balance': request.form.get('remaining_balance',''),
                'handover_notes': request.form.get('handover_notes',''),
                'backup_person': request.form.get('backup_person',''),
                'emergency_contact': request.form.get('emergency_contact',''),
                'department': session.get('department',''), 'position': role,
                'phone': request.form.get('phone',''), 'email': request.form.get('email',''),
                'status': 'pending'
            }).execute()
        return redirect('/leaves?success=1')
    my_leaves = safe_data(execute_query(supabase.table('leaves').select('*').eq('full_name',un).order('created_at',desc=True).limit(50)))
    return render_template('leaves.html',
        leaves=my_leaves,
        today=today,
        company=COMPANY_NAME,
        success_msg=request.args.get('success',''),
        departments=DEPARTMENTS,
        roles=ALL_ROLES
    )

@app.route('/leave-pdf/<int:lid>')
@login_required
def leave_pdf(lid):
    leave = safe_data(execute_query(supabase.table('leaves').select('*').eq('id', lid)))
    if not leave: return "Leave not found", 404
    return render_template('leave_pdf.html', lv=leave[0], company=COMPANY_NAME)

# ---------- APPROVE LEAVES (delegation aware) ----------
@app.route('/approve-leaves')
@login_required
def approve_leaves():
    effective_roles = get_effective_roles()
    user_role = session.get('role')
    user_branch = session.get('branch','')
    approver_roles = [
        'Operations Manager','Assistant Operations Manager',
        'Procurement Officer','HR','HR Assistant','CEO','Branch Manager',
        'Stock Controller','Assistant Stock Controller','Sales Manager','Store Manager',
        'admin','ceo'
    ]
    if not any(r in approver_roles or r in FULL_ACCESS_ROLES for r in effective_roles):
        return redirect('/')
    
    all_leaves = safe_data(execute_query(
        supabase.table('leaves')
               .select('*')
               .in_('status', ['pending','approved_by_manager','approved_by_procurement','approved_by_ops'])
               .order('created_at',desc=True)
               .limit(200)
    ))
    
    pending = []
    for leave in all_leaves:
        emp_role = leave.get('role','Staff')
        chain = get_approval_chain(emp_role)
        for stage in chain:
            if leave['status'] == stage['from_status'] and any(r in stage['allowed_roles'] for r in effective_roles):
                if user_role == 'Branch Manager':
                    if leave.get('branch','') == user_branch:
                        pending.append(leave)
                else:
                    pending.append(leave)
                break
    
    return render_template('approve_leaves.html', pending=pending, role=user_role)

@app.route('/approve-leaves/<int:lid>/<action>', methods=['POST'])
@login_required
def process_leave(lid, action):
    user_role = session.get('role')
    user_branch = session.get('branch','')
    effective_roles = get_effective_roles()
    leave = safe_data(execute_query(supabase.table('leaves').select('*').eq('id',lid)))
    if not leave:
        return redirect('/approve-leaves')
    leave = leave[0]
    emp_role = leave.get('role','Staff')
    chain = get_approval_chain(emp_role)
    
    current_stage = None
    for stage in chain:
        if leave['status'] == stage['from_status'] and any(r in stage['allowed_roles'] for r in effective_roles):
            if user_role == 'Branch Manager' and leave.get('branch','') != user_branch:
                continue
            current_stage = stage
            break
    
    if not current_stage:
        return redirect('/approve-leaves')
    
    acting_role = None
    for r in effective_roles:
        if r in current_stage['allowed_roles']:
            acting_role = r
            break
    if not acting_role:
        acting_role = user_role
    
    if action == 'approve':
        if acting_role in ['admin','ceo'] or user_role in ['admin','ceo']:
            new_status = 'approved_final'
        else:
            new_status = current_stage['to_status']
    elif action == 'reject':
        new_status = 'rejected'
    else:
        return redirect('/approve-leaves')
    
    supabase.table('leaves').update({
        'status': new_status,
        'approved_by': acting_role
    }).eq('id', lid).execute()
    return redirect('/approve-leaves')

# ---------- MARKETER ROUTES ----------
@app.route('/marketer/checkin', methods=['POST'])
@login_required
def marketer_checkin():
    if session.get('role') != MARKETER_ROLE: return redirect('/check-in')
    un = session.get('user'); today = str(now_eat().date()); now = now_eat().strftime('%H:%M:%S')
    lat = request.form.get('lat',''); lng = request.form.get('lng',''); loc = request.form.get('location','')
    supabase.table('marketer_checkins').insert({
        'full_name': un, 'date': today, 'check_in_time': now,
        'lat': lat, 'lng': lng, 'location': loc, 'status': 'pending'
    }).execute()
    return redirect('/check-in?pending=1')

@app.route('/marketer/report', methods=['POST'])
@login_required
def marketer_report():
    if session.get('role') != MARKETER_ROLE:
        return redirect('/check-in')
    un = session.get('user')
    today = str(now_eat().date())
    customer_name = request.form.get('customer_name', '').strip()
    customer_phone = request.form.get('customer_phone', '').strip()
    details = request.form.get('details', '').strip()
    expenses = request.form.get('expenses', '0')
    expected_order_date = request.form.get('expected_order_date', '').strip()
    lat = request.form.get('lat', '')
    lng = request.form.get('lng', '')
    location = request.form.get('location', '').strip()

    try: exp = float(expenses)
    except: exp = 0.0

    if not customer_name:
        return redirect('/check-in?report=error')

    existing = safe_data(execute_query(
        supabase.table('customer_reports')
               .select('id')
               .eq('full_name', un)
               .eq('date', today)
               .eq('customer_name', customer_name)
               .limit(1)
    ))
    if existing:
        return redirect('/check-in?report=duplicate')

    supabase.table('customer_reports').insert({
        'full_name': un,
        'date': today,
        'customer_name': customer_name,
        'customer_phone': customer_phone,
        'details': details,
        'expenses': exp,
        'expected_order_date': expected_order_date if expected_order_date else None,
        'lat': lat,
        'lng': lng,
        'location': location
    }).execute()
    return redirect('/check-in?report=1')

# ---------- MARKETER LOCATION SUBMISSION ----------
@app.route('/marketer/submit-location', methods=['POST'])
@login_required
def submit_marketer_location():
    if session.get('role') != MARKETER_ROLE:
        return redirect('/check-in')
    un = session.get('user')
    today = str(now_eat().date())
    now = now_eat().strftime('%H:%M:%S')
    lat = request.form.get('lat', '')
    lng = request.form.get('lng', '')
    loc = request.form.get('location', '')
    supabase.table('marketer_locations').insert({
        'full_name': un,
        'date': today,
        'time': now,
        'lat': lat,
        'lng': lng,
        'location': loc
    }).execute()
    return redirect('/check-in?location=ok')

# ---------- SALES MANAGER DASHBOARD ----------
@app.route('/sales-manager')
@login_required
def sales_manager_dashboard():
    if session.get('role') != SALES_MANAGER_ROLE: return redirect('/')
    today = str(now_eat().date())
    pending_checkins = safe_data(execute_query(
        supabase.table('marketer_checkins').select('*').eq('date',today).eq('status','pending').order('created_at',desc=True).limit(50)
    ))
    approved_checkins = safe_data(execute_query(
        supabase.table('marketer_checkins').select('*').eq('date',today).eq('status','approved').order('check_in_time').limit(50)
    ))
    reports = safe_data(execute_query(
        supabase.table('customer_reports').select('*').eq('date',today).order('created_at',desc=True).limit(50)
    ))
    assigned = safe_data(execute_query(
        supabase.table('assigned_places').select('*').order('date_assigned',desc=True).limit(100)
    ))
    location_pings = safe_data(execute_query(
        supabase.table('marketer_locations')
               .select('*')
               .eq('date', today)
               .order('time')
               .limit(200)
    ))
    return render_template('sales_manager.html',
        pending_checkins=pending_checkins,
        approved_checkins=approved_checkins,
        reports=reports,
        assigned=assigned,
        location_pings=location_pings,
        today=today,
        company=COMPANY_NAME)

@app.route('/sales-manager/approve/<int:cid>', methods=['POST'])
@login_required
def approve_checkin(cid):
    if session.get('role') != SALES_MANAGER_ROLE: return redirect('/')
    supabase.table('marketer_checkins').update({'status':'approved'}).eq('id',cid).execute()
    req = safe_data(execute_query(supabase.table('marketer_checkins').select('*').eq('id',cid)))
    if req:
        r = req[0]
        existing = safe_data(execute_query(supabase.table('attendance').select('id').eq('full_name',r['full_name']).eq('date',r['date'])))
        if not existing:
            supabase.table('attendance').insert({
                'full_name': r['full_name'], 'date': r['date'],
                'check_in': r['check_in_time'], 'status': 'present',
                'check_in_lat': r.get('lat',''), 'check_in_lng': r.get('lng',''),
                'check_in_location': r.get('location',''), 'department': '', 'branch': ''
            }).execute()
    return redirect('/sales-manager')

@app.route('/sales-manager/reject/<int:cid>', methods=['POST'])
@login_required
def reject_checkin(cid):
    if session.get('role') != SALES_MANAGER_ROLE: return redirect('/')
    supabase.table('marketer_checkins').update({'status':'rejected'}).eq('id',cid).execute()
    return redirect('/sales-manager')

@app.route('/sales-manager/assign', methods=['POST'])
@login_required
def assign_place():
    if session.get('role') != SALES_MANAGER_ROLE: return redirect('/')
    marketer = request.form.get('marketer_name','').strip()
    place = request.form.get('place_name','').strip()
    if marketer and place:
        supabase.table('assigned_places').insert({
            'marketer_name': marketer, 'place_name': place, 'date_assigned': str(now_eat().date())
        }).execute()
    return redirect('/sales-manager')

@app.route('/my-places')
@login_required
def my_places():
    if session.get('role') != MARKETER_ROLE: return redirect('/')
    un = session.get('user')
    places = safe_data(execute_query(supabase.table('assigned_places').select('*').eq('marketer_name',un).order('date_assigned',desc=True).limit(50)))
    return render_template('my_places.html', places=places, company=COMPANY_NAME)

# ---------- TARGET SETTING ----------
@app.route('/targets', methods=['GET','POST'])
@login_required
def targets_page():
    if session.get('role') not in TARGET_SETTER_ROLES: return redirect('/')
    user_role = session.get('role')
    if request.method == 'POST':
        employee = request.form.get('employee_name','').strip()
        month = request.form.get('month',''); amount = request.form.get('amount','0')
        try:
            amt = float(amount)
            if employee and month and amt > 0:
                supabase.table('sales_targets').upsert({
                    'full_name': employee, 'month': month, 'target_amount': amt, 'set_by': session.get('user')
                }, on_conflict='full_name,month').execute()
        except: pass
        return redirect('/targets')
    if user_role == 'Sales Manager':
        employees = safe_data(execute_query(
            supabase.table('employees').select('full_name').eq('status','approved').eq('role','Marketers').order('full_name')
        ))
    else:
        employees = safe_data(execute_query(
            supabase.table('employees').select('full_name').eq('status','approved').order('full_name')
        ))
    targets = safe_data(execute_query(supabase.table('sales_targets').select('*').order('month', desc=True).order('full_name').limit(100)))
    return render_template('targets.html', employees=employees, targets=targets, today=str(now_eat().date()), company=COMPANY_NAME)

# ---------- PROCUREMENT OFFICER ROUTES ----------
@app.route('/procurement/status')
@login_required
def procurement_status():
    if session.get('role') != 'Procurement Officer':
        return redirect('/')
    today = str(now_eat().date())
    working = safe_data(execute_query(
        supabase.table('attendance')
               .select('full_name, check_in, department, branch, status')
               .eq('date', today)
               .not_.is_('check_in', 'null')
               .is_('check_out', 'null')
               .order('check_in')
               .limit(200)
    ))
    checked_out = safe_data(execute_query(
        supabase.table('attendance')
               .select('full_name, check_out, department, branch')
               .eq('date', today)
               .not_.is_('check_out', 'null')
               .order('check_out')
               .limit(200)
    ))
    return render_template('procurement_status.html',
        working=working,
        checked_out=checked_out,
        today=today,
        company=COMPANY_NAME)

@app.route('/procurement/delegation', methods=['GET','POST'])
@login_required
def procurement_delegation():
    if session.get('role') != 'Procurement Officer':
        return redirect('/')
    po = safe_data(execute_query(
        supabase.table('employees').select('id').eq('full_name', session.get('user')).limit(1)
    ))
    if not po:
        return redirect('/')
    po_id = po[0]['id']

    if request.method == 'POST':
        action = request.form.get('action')
        if action == 'delegate':
            delegate_name = request.form.get('delegate_name','').strip()
            if delegate_name:
                delegate = safe_data(execute_query(
                    supabase.table('employees').select('id').eq('full_name', delegate_name).limit(1)
                ))
                if delegate:
                    execute_query(supabase.table('role_delegations').update({'active': False})
                        .eq('delegator_id', po_id).eq('active', True))
                    supabase.table('role_delegations').insert({
                        'delegator_id': po_id,
                        'delegate_id': delegate[0]['id'],
                        'role': 'Procurement Officer',
                        'start_date': str(now_eat().date()),
                        'active': True
                    }).execute()
                    return redirect('/procurement/delegation?success=1')
        elif action == 'resume':
            execute_query(supabase.table('role_delegations').update({'active': False})
                .eq('delegator_id', po_id).eq('active', True))
            return redirect('/procurement/delegation?resumed=1')

    active_deleg = safe_data(execute_query(
        supabase.table('role_delegations')
               .select('*, delegate:employees!delegate_id(full_name)')
               .eq('delegator_id', po_id)
               .eq('active', True)
               .maybe_single()
    ))
    delegate_name = active_deleg.get('delegate',{}).get('full_name','') if active_deleg else None

    eligible = safe_data(execute_query(
        supabase.table('employees')
               .select('full_name, branch, department')
               .eq('status','approved')
               .or_('branch.eq.Kisumu HQ,department.eq.Management')
               .neq('full_name', session.get('user'))
               .order('full_name')
               .limit(100)
    ))
    return render_template('procurement_delegation.html',
        delegate_name=delegate_name,
        eligible=eligible,
        success=request.args.get('success',''),
        resumed=request.args.get('resumed',''),
        company=COMPANY_NAME)

# ---------- ERROR HANDLER ----------
@app.errorhandler(Exception)
def handle_exception(e):
    print(f"Unhandled error: {e}")
    return render_template('error.html', error=str(e)), 500

if __name__=='__main__':
    app.run(host='0.0.0.0',port=5000)
