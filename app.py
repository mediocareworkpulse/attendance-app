from flask import Flask, render_template, request, redirect, url_for, session, Response
from datetime import date, datetime, timedelta, timezone
from supabase import create_client
from functools import wraps
from collections import defaultdict
from werkzeug.security import generate_password_hash, check_password_hash
import pytz, time, csv, io

app = Flask(__name__)
app.secret_key = 'mediocare-attendance-secret-2024'

app.config.update(
    SESSION_COOKIE_HTTPONLY = True,
    SESSION_COOKIE_SECURE = True,
    SESSION_COOKIE_SAMESITE = 'Lax'
)

SUPABASE_URL = 'https://lznqrkujlrcxcxizygzq.supabase.co'
SUPABASE_KEY = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Imx6bnFya3VqbHJjeGN4aXp5Z3pxIiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc4NDU2MjA2NSwiZXhwIjoyMTAwMTM4MDY1fQ.XmMAGB1G8hOOLr7PTnn100cifWMkja2gcZfKRSBI5Ec'

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
EAT = timezone(timedelta(hours=3))

DEPARTMENTS = ['Staff','Store','Dispatch','Sales','Stock Control','Procurement','Accounts Office','Operations','Branch Management','Management']
ALL_ROLES = [
    'Staff','Branch Manager','Branch Order Processor','Stock Controller','Assistant Stock Controller',
    'Procurement Officer','Accountant','Accountant Assistant','Cashier',
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

COMPANY_NAME = 'Mediocare Pharmaceuticals Ltd'
LATE_GRACE_MINUTES = 20   # changed from 30

# ---------- HELPERS ----------
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

def normalize_role(role):
    role_lower = role.strip().lower()
    for r in ALL_ROLES:
        if r.lower() == role_lower: return r
    return role

def get_active_delegation(user_id):
    data = safe_data(execute_query(
        supabase.table('role_delegations').select('role').eq('delegate_id', user_id).eq('active', True).maybe_single()
    ))
    return data.get('role') if data else None

def get_effective_roles():
    own_role = session.get('role','')
    roles = [own_role]
    emp = safe_data(execute_query(
        supabase.table('employees').select('id').eq('full_name', session.get('user')).limit(1)
    ))
    if emp:
        del_role = get_active_delegation(emp[0]['id'])
        if del_role: roles.append(del_role)
    return roles

def get_branch_employees(branch):
    return safe_data(execute_query(
        supabase.table('employees').select('full_name').eq('status','approved').eq('branch', branch).order('full_name')
    ))

# ---------- LEAVE APPROVAL CHAIN ----------
def get_approval_chain(employee_role):
    role_lower = employee_role.strip().lower()
    chain = []
    if role_lower in ['drivers','riders','dispatch personnel','security','cleaner']:
        chain = [
            {'from_status': 'pending', 'to_status': 'approved_by_manager',
             'allowed_roles': ['Operations Manager','Assistant Operations Manager']},
            {'from_status': 'approved_by_manager', 'to_status': 'approved_final',
             'allowed_roles': ['HR','HR Assistant']}
        ]
    elif role_lower == 'store manager':
        chain = [
            {'from_status': 'pending', 'to_status': 'approved_by_manager',
             'allowed_roles': ['Operations Manager','Assistant Operations Manager']},
            {'from_status': 'approved_by_manager', 'to_status': 'approved_by_procurement',
             'allowed_roles': ['Procurement Officer']},
            {'from_status': 'approved_by_procurement', 'to_status': 'approved_final',
             'allowed_roles': ['HR','HR Assistant']}
        ]
    elif role_lower == 'branch manager':
        chain = [
            {'from_status': 'pending', 'to_status': 'approved_by_manager',
             'allowed_roles': ['Stock Controller','Assistant Stock Controller']},
            {'from_status': 'approved_by_manager', 'to_status': 'approved_final',
             'allowed_roles': ['CEO','HR','HR Assistant']}
        ]
    elif role_lower == 'assistant operations manager':
        chain = [
            {'from_status': 'pending', 'to_status': 'approved_by_manager',
             'allowed_roles': ['Operations Manager']},
            {'from_status': 'approved_by_manager', 'to_status': 'approved_final',
             'allowed_roles': ['CEO','HR','HR Assistant']}
        ]
    elif role_lower == 'marketers':
        chain = [
            {'from_status': 'pending', 'to_status': 'approved_by_manager',
             'allowed_roles': ['Sales Manager']},
            {'from_status': 'approved_by_manager', 'to_status': 'approved_final',
             'allowed_roles': ['HR','HR Assistant']}
        ]
    elif role_lower == 'telesales':
        chain = [
            {'from_status': 'pending', 'to_status': 'approved_by_manager',
             'allowed_roles': ['Sales Manager']},
            {'from_status': 'approved_by_manager', 'to_status': 'approved_final',
             'allowed_roles': ['HR','HR Assistant']}
        ]
    elif role_lower == 'branch order processor':
        chain = [
            {'from_status': 'pending', 'to_status': 'approved_by_manager',
             'allowed_roles': ['Operations Manager','Assistant Operations Manager']},
            {'from_status': 'approved_by_manager', 'to_status': 'approved_final',
             'allowed_roles': ['HR','HR Assistant']}
        ]
    elif role_lower in ['store personnel','storekeeper','store assistant']:
        chain = [
            {'from_status': 'pending', 'to_status': 'approved_by_manager',
             'allowed_roles': ['Store Manager']},
            {'from_status': 'approved_by_manager', 'to_status': 'approved_by_ops',
             'allowed_roles': ['Operations Manager','Assistant Operations Manager']},
            {'from_status': 'approved_by_ops', 'to_status': 'approved_final',
             'allowed_roles': ['HR','HR Assistant']}
        ]
    elif role_lower == 'cashier':
        chain = [
            {'from_status': 'pending', 'to_status': 'approved_by_manager',
             'allowed_roles': ['Accountant','Accountant Assistant']},
            {'from_status': 'approved_by_manager', 'to_status': 'approved_final',
             'allowed_roles': ['HR','HR Assistant']}
        ]
    elif role_lower in ['stock controller','assistant stock controller',
                        'accountant','accountant assistant',
                        'operations manager','procurement officer','sales manager']:
        chain = [
            {'from_status': 'pending', 'to_status': 'approved_final',
             'allowed_roles': ['CEO','HR','HR Assistant']}
        ]
    elif role_lower in ['hr','hr assistant']:
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
        if 'admin' not in stage['allowed_roles']: stage['allowed_roles'].append('admin')
        if 'ceo' not in stage['allowed_roles']: stage['allowed_roles'].append('ceo')
    return chain

def count_employees_on_leave(team_names=None, single_user=None):
    today = str(now_eat().date())
    query = (supabase.table('leaves')
             .select('full_name')
             .in_('status', ['approved_final','approved_by_manager','approved_by_procurement','approved_by_ops'])
             .lte('leave_start', today).gte('leave_end', today).limit(500))
    if single_user: query = query.eq('full_name', single_user)
    elif team_names: query = query.in_('full_name', team_names)
    data = safe_data(execute_query(query))
    return len(set(d['full_name'] for d in data))

# ---------- FORCE LOGOUT BLOCKED USERS ----------
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
def login():
    if request.method == 'POST':
        email = request.form['email'].strip()
        password = request.form['password'].strip()
        emp = safe_data(execute_query(
            supabase.table('employees').select('*').eq('email', email).limit(1)
        ))
        if emp:
            emp = emp[0]
            if emp.get('blocked'):
                return render_template('login.html', error='Account blocked. Contact admin.')
            if check_password_hash(emp['password'], password):
                session['user'] = emp['full_name']
                session['email'] = emp['email']
                session['role'] = emp['role']
                session['branch'] = emp.get('branch','')
                session['id'] = emp['id']
                # Check trusted device
                device = safe_data(execute_query(
                    supabase.table('trusted_devices').select('*').eq('user_id', emp['id']).eq('device', request.headers.get('User-Agent','')).limit(1)
                ))
                if not device and emp['role'] not in NO_CHECKIN_ROLES:
                    return redirect('/trust-device')
                return redirect('/dashboard')
            else:
                return render_template('login.html', error='Invalid password')
        else:
            return render_template('login.html', error='Email not found')
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect('/login')

@app.route('/trust-device', methods=['GET','POST'])
@login_required
def trust_device():
    user_id = session.get('id')
    if request.method == 'POST':
        code = request.form['code'].strip()
        # validate code from DB (simple 4-digit)
        emp = safe_data(execute_query(
            supabase.table('employees').select('device_code').eq('id', user_id).limit(1)
        ))
        if emp and emp[0].get('device_code') == code:
            supabase.table('trusted_devices').insert({
                'user_id': user_id,
                'device': request.headers.get('User-Agent',''),
                'created_at': str(now_eat())
            }).execute()
            return redirect('/dashboard')
        return render_template('trust_device.html', error='Invalid code')
    return render_template('trust_device.html')

@app.route('/signup', methods=['GET','POST'])
def signup():
    if request.method == 'POST':
        full_name = request.form['full_name'].strip()
        email = request.form['email'].strip()
        phone = request.form['phone'].strip()
        password = request.form['password'].strip()
        branch = request.form['branch'].strip()
        role = request.form['role'].strip()
        existing = safe_data(execute_query(
            supabase.table('employees').select('id').eq('email', email).limit(1)
        ))
        if existing:
            return render_template('signup.html', error='Email already registered', branches=get_branch_names(), roles=ALL_ROLES)
        hashed = generate_password_hash(password)
        supabase.table('employees').insert({
            'full_name': full_name, 'email': email, 'phone': phone,
            'password': hashed, 'branch': branch, 'role': role,
            'status': 'pending', 'created_at': str(now_eat())
        }).execute()
        return redirect('/login?registered=1')
    return render_template('signup.html', branches=get_branch_names(), roles=ALL_ROLES)

# ---------- DASHBOARD ----------
@app.route('/')
@app.route('/dashboard')
@login_required
def dashboard():
    uname = session['user']
    role = session['role']
    branch = session.get('branch','')
    today = str(now_eat().date())
    # Attendance today
    att = safe_data(execute_query(
        supabase.table('attendance').select('*').eq('full_name', uname).eq('date', today).maybe_single()
    ))
    checked_in = att and att.get('check_in') is not None
    checked_out = att and att.get('check_out') is not None
    # Quick stats
    team_on_leave = count_employees_on_leave(team_names=[e['full_name'] for e in get_branch_employees(branch)]) if branch else 0
    return render_template('dashboard.html', user=uname, role=role, branch=branch,
                           checked_in=checked_in, checked_out=checked_out,
                           team_on_leave=team_on_leave, company=COMPANY_NAME)

# ---------- CHECK IN / OUT ----------
@app.route('/check-in', methods=['POST'])
@login_required
def check_in():
    uname = session['user']
    role = session['role']
    if role in NO_CHECKIN_ROLES:
        return redirect('/')
    today = str(now_eat().date())
    att = safe_data(execute_query(
        supabase.table('attendance').select('*').eq('full_name', uname).eq('date', today).maybe_single()
    ))
    if att and att.get('check_in'):
        return redirect('/dashboard?error=already_checked_in')
    time_in = now_eat().strftime('%H:%M:%S')
    status = 'present'
    # Check late
    shift_start = '08:00:00'  # default
    emp = safe_data(execute_query(
        supabase.table('employees').select('shift_start').eq('full_name', uname).limit(1)
    ))
    if emp and emp[0].get('shift_start'):
        shift_start = emp[0]['shift_start']
    if datetime.strptime(time_in, '%H:%M:%S') > (datetime.strptime(shift_start, '%H:%M:%S') + timedelta(minutes=LATE_GRACE_MINUTES)):
        status = 'late'
    supabase.table('attendance').insert({
        'full_name': uname,
        'date': today,
        'check_in': time_in,
        'status': status,
        'branch': session.get('branch','')
    }).execute()
    return redirect('/dashboard?checked_in=1')

@app.route('/check-out', methods=['POST'])
@login_required
def check_out():
    uname = session['user']
    today = str(now_eat().date())
    att = safe_data(execute_query(
        supabase.table('attendance').select('*').eq('full_name', uname).eq('date', today).maybe_single()
    ))
    if not att or att.get('check_out'):
        return redirect('/dashboard?error=already_checked_out')
    time_out = now_eat().strftime('%H:%M:%S')
    supabase.table('attendance').update({'check_out': time_out}).eq('id', att['id']).execute()
    return redirect('/dashboard?checked_out=1')

# ---------- INDIVIDUAL SALES ENTRY ----------
@app.route('/sales', methods=['GET','POST'])
@login_required
def sales_page():
    role = session.get('role','')
    if role not in SALES_SUBMIT_ROLES:
        return redirect('/')
    if request.method == 'POST':
        date_sale = request.form['date']
        mpesa = float(request.form.get('mpesa_sales',0))
        cash = float(request.form.get('cash_sales',0))
        total = mpesa + cash
        expenses = []
        exp_names = request.form.getlist('expense_name[]')
        exp_amounts = request.form.getlist('expense_amount[]')
        for n, a in zip(exp_names, exp_amounts):
            if n.strip():
                expenses.append({'name': n.strip(), 'amount': float(a)})
        notes = request.form.get('notes','')
        supabase.table('sales').insert({
            'date': date_sale,
            'full_name': session['user'],
            'branch': session.get('branch',''),
            'mpesa_sales': mpesa,
            'cash_sales': cash,
            'total_sales': total,
            'expenses': expenses,
            'notes': notes
        }).execute()
        return redirect('/sales?success=1')
    return render_template('sales.html', company=COMPANY_NAME)

# ---------- BRANCH SALES (for branch managers) ----------
@app.route('/branch-sales', methods=['GET','POST'])
@login_required
def branch_sales_page():
    role = session.get('role','')
    if role not in ['Branch Manager','Stock Controller','Assistant Stock Controller','admin','ceo']:
        return redirect('/')
    if request.method == 'POST':
        date_sale = request.form['date']
        branch = session.get('branch','')
        mpesa = float(request.form.get('mpesa_sales',0))
        cash = float(request.form.get('cash_sales',0))
        total = mpesa + cash
        expenses = []
        exp_names = request.form.getlist('expense_name[]')
        exp_amounts = request.form.getlist('expense_amount[]')
        for n, a in zip(exp_names, exp_amounts):
            if n.strip():
                expenses.append({'name': n.strip(), 'amount': float(a)})
        notes = request.form.get('notes','')
        supabase.table('branch_sales').insert({
            'date': date_sale,
            'branch': branch,
            'mpesa_sales': mpesa,
            'cash_sales': cash,
            'total_sales': total,
            'expenses': expenses,
            'submitted_by': session['user'],
            'notes': notes
        }).execute()
        return redirect('/branch-sales?success=1')
    return render_template('branch_sales.html', company=COMPANY_NAME)

# ---------- SALES REPORT (individual with names) ----------
@app.route('/sales-report')
@login_required
def sales_report():
    if session.get('role') not in ['admin','ceo','Stock Controller','Assistant Stock Controller','Accountant','Accountant Assistant']:
        return redirect('/')
    view_type = request.args.get('view_type','individual')
    filter_branch = request.args.get('branch','')
    filter_employee = request.args.get('employee','')
    filter_from = request.args.get('from_date','')
    filter_to = request.args.get('to_date','')
    period = request.args.get('period','')
    today = str(now_eat().date())
    if not filter_from: filter_from = today
    if not filter_to: filter_to = today
    if period == 'week': filter_from = str(now_eat().date() - timedelta(days=7)); filter_to = today
    elif period == 'month': filter_from = str(now_eat().date().replace(day=1)); filter_to = today
    elif period == 'year': filter_from = str(now_eat().date().replace(month=1, day=1)); filter_to = today

    branches = get_branch_names()
    employees_list = safe_data(execute_query(
        supabase.table('employees').select('full_name').eq('status','approved').order('full_name')
    ))
    totals = []

    if view_type == 'individual':
        query = supabase.table('sales').select('*')
        if filter_branch: query = query.eq('branch', filter_branch)
        if filter_employee: query = query.eq('full_name', filter_employee)
        query = query.gte('date', filter_from).lte('date', filter_to).order('date', desc=True).limit(2000)
        sales = safe_data(execute_query(query))
        grouped = defaultdict(lambda: {'mpesa':0, 'cash':0, 'expenses':[], 'total':0})
        for s in sales:
            key = (s['date'], s['full_name'], s['branch'])
            rec = grouped[key]
            rec['mpesa'] += float(s.get('mpesa_sales',0))
            rec['cash'] += float(s.get('cash_sales',0))
            if s.get('expenses'):
                rec['expenses'].extend(s['expenses'])
            rec['total'] += float(s.get('total_sales',0))
        for (dt, emp, br), vals in grouped.items():
            expenses_total = sum(e['amount'] for e in vals['expenses']) if vals['expenses'] else 0
            totals.append({
                'date': dt, 'employee': emp, 'branch': br,
                'mpesa': vals['mpesa'], 'cash': vals['cash'],
                'expenses_total': expenses_total, 'total': vals['total']
            })
        totals.sort(key=lambda x: x['date'], reverse=True)
    else:
        query = supabase.table('branch_sales').select('date, branch, mpesa_sales, cash_sales, total_sales, submitted_by')
        if filter_branch: query = query.eq('branch', filter_branch)
        query = query.gte('date', filter_from).lte('date', filter_to).order('date', desc=True).limit(2000)
        data = safe_data(execute_query(query))
        grouped = defaultdict(lambda: {'mpesa':0, 'cash':0, 'total':0})
        for s in data:
            key = (s['date'], s['branch'])
            rec = grouped[key]
            rec['mpesa'] += float(s.get('mpesa_sales',0))
            rec['cash'] += float(s.get('cash_sales',0))
            rec['total'] += float(s.get('total_sales',0))
        totals = [{'date': dt, 'branch': br, 'mpesa': vals['mpesa'], 'cash': vals['cash'], 'total': vals['total']}
                  for (dt, br), vals in grouped.items()]
        totals.sort(key=lambda x: x['date'], reverse=True)

    return render_template('sales_report.html', view_type=view_type, filter_branch=filter_branch,
                         filter_employee=filter_employee, filter_from=filter_from, filter_to=filter_to,
                         period=period, branches=branches, employees=employees_list, totals=totals,
                         company=COMPANY_NAME)

# ---------- EXPORT SALES (CSV) – updated with employee column ----------
@app.route('/export-sales')
@login_required
def export_sales():
    if session.get('role') not in FULL_ACCESS_ROLES + ['Stock Controller','Assistant Stock Controller','Accountant','Accountant Assistant']:
        return redirect('/')
    view_type = request.args.get('view_type','individual')
    from_date = request.args.get('from_date', str(now_eat().date().replace(day=1)))
    to_date   = request.args.get('to_date', str(now_eat().date()))
    branch = request.args.get('branch','')
    employee = request.args.get('employee','')
    si = io.StringIO()
    cw = csv.writer(si)
    if view_type == 'individual':
        cw.writerow(['Date','Employee','Branch','M-Pesa','Cash','Expenses','Total Sales','Notes'])
        query = supabase.table('sales').select('*').gte('date', from_date).lte('date', to_date).order('date',desc=True).limit(2000)
        if branch: query = query.eq('branch', branch)
        if employee: query = query.eq('full_name', employee)
        data = safe_data(execute_query(query))
        for s in data:
            expenses_str = '; '.join([f"{e['name']}:{e['amount']}" for e in s.get('expenses',[])]) if s.get('expenses') else ''
            cw.writerow([s['date'], s['full_name'], s['branch'], s['mpesa_sales'], s['cash_sales'], expenses_str, s['total_sales'], s.get('notes','')])
    else:
        cw.writerow(['Date','Branch','M-Pesa','Cash','Expenses','Total Sales','Submitted By','Notes'])
        query = supabase.table('branch_sales').select('*').gte('date', from_date).lte('date', to_date).order('date',desc=True).limit(2000)
        if branch: query = query.eq('branch', branch)
        data = safe_data(execute_query(query))
        for s in data:
            expenses_str = '; '.join([f"{e['name']}:{e['amount']}" for e in s.get('expenses',[])]) if s.get('expenses') else ''
            cw.writerow([s['date'], s['branch'], s['mpesa_sales'], s['cash_sales'], expenses_str, s['total_sales'], s.get('submitted_by',''), s.get('notes','')])
    output = si.getvalue(); si.close()
    return Response(output, mimetype='text/csv', headers={"Content-Disposition": "attachment;filename=sales_report.csv"})

# ---------- LEAVES ----------
@app.route('/leaves', methods=['GET','POST'])
@login_required
def leaves_page():
    uname = session['user']
    role = session.get('role','')
    if request.method == 'POST':
        start = request.form['leave_start']
        end = request.form['leave_end']
        reason = request.form['reason']
        emp = safe_data(execute_query(
            supabase.table('employees').select('role').eq('full_name', uname).limit(1)
        ))
        emp_role = emp[0]['role'] if emp else role
        supabase.table('leaves').insert({
            'full_name': uname,
            'leave_start': start,
            'leave_end': end,
            'reason': reason,
            'status': 'pending',
            'employee_role': emp_role
        }).execute()
        return redirect('/leaves?submitted=1')
    # View leaves
    my_leaves = safe_data(execute_query(
        supabase.table('leaves').select('*').eq('full_name', uname).order('created_at', desc=True).limit(50)
    ))
    # Approvals for managers
    pending = []
    eff_roles = get_effective_roles()
    # Fetch all pending leaves
    all_pending = safe_data(execute_query(
        supabase.table('leaves').select('*').eq('status', 'pending').limit(500)
    ))
    # For each, check if user can approve
    for lv in all_pending:
        chain = get_approval_chain(lv.get('employee_role', ''))
        for stage in chain:
            if stage['from_status'] == lv['status'] and any(r in eff_roles for r in stage['allowed_roles']):
                pending.append(lv)
                break
            elif stage['from_status'] != 'pending':
                # Also check later stages if current status matches
                if stage['from_status'] == lv['status'] and any(r in eff_roles for r in stage['allowed_roles']):
                    pending.append(lv)
                    break
    return render_template('leaves.html', my_leaves=my_leaves, pending=pending, company=COMPANY_NAME)

@app.route('/leave/approve/<int:leave_id>', methods=['POST'])
@login_required
def approve_leave(leave_id):
    leave = safe_data(execute_query(
        supabase.table('leaves').select('*').eq('id', leave_id).maybe_single()
    ))
    if not leave: return redirect('/leaves')
    chain = get_approval_chain(leave['employee_role'])
    new_status = None
    for stage in chain:
        if stage['from_status'] == leave['status'] and session.get('role') in stage['allowed_roles']:
            new_status = stage['to_status']
            break
    if new_status:
        supabase.table('leaves').update({'status': new_status}).eq('id', leave_id).execute()
    return redirect('/leaves')

@app.route('/leave/reject/<int:leave_id>', methods=['POST'])
@login_required
def reject_leave(leave_id):
    supabase.table('leaves').update({'status': 'rejected'}).eq('id', leave_id).execute()
    return redirect('/leaves')

# ---------- ATTENDANCE SUMMARY (fast single query) ----------
@app.route('/attendance-summary')
@login_required
def attendance_summary():
    if session.get('role') not in FULL_ACCESS_ROLES + ['HR','HR Assistant']:
        return redirect('/')
    from_date = request.args.get('from_date', str(now_eat().date().replace(day=1)))
    to_date = request.args.get('to_date', str(now_eat().date()))
    branch_filter = request.args.get('branch', '')
    employee_filter = request.args.get('employee', '')

    emp_query = supabase.table('employees').select('full_name, branch, department, role').eq('status','approved')
    if branch_filter: emp_query = emp_query.eq('branch', branch_filter)
    if employee_filter: emp_query = emp_query.eq('full_name', employee_filter)
    employees = safe_data(execute_query(emp_query.order('full_name').limit(500)))
    emp_names = [e['full_name'] for e in employees]

    att_data = safe_data(execute_query(
        supabase.table('attendance')
               .select('full_name, date')
               .gte('date', from_date).lte('date', to_date)
               .in_('full_name', emp_names)
               .not_.is_('check_in', 'null')
               .limit(10000)
    ))
    emp_days = defaultdict(set)
    for a in att_data:
        emp_days[a['full_name']].add(a['date'])
    summary = []
    for e in employees:
        days_present = len(emp_days.get(e['full_name'], set()))
        summary.append({**e, 'days_present': days_present})

    branches = get_branch_names()
    all_employees = safe_data(execute_query(supabase.table('employees').select('full_name').eq('status','approved').order('full_name')))
    return render_template('attendance_summary.html', summary=summary, from_date=from_date, to_date=to_date,
                           branch_filter=branch_filter, employee_filter=employee_filter,
                           branches=branches, all_employees=all_employees, company=COMPANY_NAME)

@app.route('/export-attendance-summary')
@login_required
def export_attendance_summary():
    if session.get('role') not in FULL_ACCESS_ROLES + ['HR','HR Assistant']: return redirect('/')
    from_date = request.args.get('from_date', str(now_eat().date().replace(day=1)))
    to_date = request.args.get('to_date', str(now_eat().date()))
    branch_filter = request.args.get('branch', '')
    employee_filter = request.args.get('employee', '')
    emp_query = supabase.table('employees').select('full_name, branch, department, role').eq('status','approved')
    if branch_filter: emp_query = emp_query.eq('branch', branch_filter)
    if employee_filter: emp_query = emp_query.eq('full_name', employee_filter)
    employees = safe_data(execute_query(emp_query.order('full_name').limit(500)))
    emp_names = [e['full_name'] for e in employees]
    att_data = safe_data(execute_query(
        supabase.table('attendance').select('full_name, date')
               .gte('date', from_date).lte('date', to_date).in_('full_name', emp_names)
               .not_.is_('check_in', 'null').limit(10000)
    ))
    emp_days = defaultdict(set)
    for a in att_data: emp_days[a['full_name']].add(a['date'])
    summary = []
    for e in employees:
        days_present = len(emp_days.get(e['full_name'], set()))
        summary.append({**e, 'days_present': days_present})
    si = io.StringIO()
    cw = csv.writer(si)
    cw.writerow(['Employee','Department','Branch','Role','Days Present'])
    for s in summary: cw.writerow([s['full_name'], s['department'], s['branch'], s['role'], s['days_present']])
    output = si.getvalue(); si.close()
    return Response(output, mimetype='text/csv', headers={"Content-Disposition": "attachment;filename=attendance_summary.csv"})

# ---------- SHIFT CHANGE ----------
@app.route('/shift-change', methods=['GET','POST'])
@login_required
def shift_change_page():
    user_role = session.get('role')
    un = session.get('user')
    ub = session.get('branch','')
    if user_role not in ['Branch Manager','Stock Controller','Assistant Stock Controller','admin','ceo']:
        return redirect('/')

    if request.method == 'POST' and user_role == 'Branch Manager':
        employee_name = request.form.get('employee','').strip()
        new_start = request.form.get('shift_start','')
        new_end   = request.form.get('shift_end','')
        reason    = request.form.get('reason','')
        if not employee_name or not new_start or not new_end:
            return render_template('shift_change.html', error='All fields required',
                                   employees=get_branch_employees(ub), requests=[], company=COMPANY_NAME)
        supabase.table('shift_change_requests').insert({
            'requested_by': un, 'branch': ub,
            'employee_full_name': employee_name,
            'new_shift_start': new_start, 'new_shift_end': new_end,
            'reason': reason, 'status': 'pending'
        }).execute()
        return redirect('/shift-change?success=1')

    if user_role in ['Stock Controller','Assistant Stock Controller','admin','ceo']:
        requests_data = safe_data(execute_query(
            supabase.table('shift_change_requests').select('*').in_('status', ['pending','approved','rejected'])
                   .order('created_at',desc=True).limit(200)
        ))
    else:
        requests_data = safe_data(execute_query(
            supabase.table('shift_change_requests').select('*').eq('branch', ub)
                   .order('created_at',desc=True).limit(100)
        ))

    employees = get_branch_employees(ub) if user_role == 'Branch Manager' else []
    return render_template('shift_change.html', requests=requests_data, employees=employees,
                           success=request.args.get('success',''), company=COMPANY_NAME)

@app.route('/shift-change/approve/<int:req_id>', methods=['POST'])
@login_required
def approve_shift_change(req_id):
    if session.get('role') not in ['Stock Controller','Assistant Stock Controller','admin','ceo']:
        return redirect('/')
    supabase.table('shift_change_requests').update({'status': 'approved'}).eq('id', req_id).execute()
    return redirect('/shift-change')

@app.route('/shift-change/reject/<int:req_id>', methods=['POST'])
@login_required
def reject_shift_change(req_id):
    if session.get('role') not in ['Stock Controller','Assistant Stock Controller','admin','ceo']:
        return redirect('/')
    supabase.table('shift_change_requests').update({'status': 'rejected'}).eq('id', req_id).execute()
    return redirect('/shift-change')

# ---------- DIRECTORATE (Contacts) ----------
@app.route('/contacts')
@login_required
def contacts_page():
    allowed_roles = DIRECTORATE_ROLES + ['Procurement Officer']
    if session.get('role') not in allowed_roles: return redirect('/')
    contacts = safe_data(execute_query(
        supabase.table('contacts').select('*').order('full_name')
    ))
    return render_template('contacts.html', contacts=contacts, company=COMPANY_NAME)

# ---------- ADMIN PANEL (manage employees, branches, delegations) ----------
@app.route('/admin')
@admin_required
def admin_page():
    employees = safe_data(execute_query(
        supabase.table('employees').select('*').order('full_name')
    ))
    branches = get_branches()
    contacts = safe_data(execute_query(
        supabase.table('contacts').select('*').order('full_name')
    ))
    delegations = safe_data(execute_query(
        supabase.table('role_delegations').select('*, employees!inner(full_name)').eq('active', True).limit(100)
    ))
    return render_template('admin.html', employees=employees, branches=branches, contacts=contacts,
                           delegations=delegations, company=COMPANY_NAME)

@app.route('/admin/employee/<int:emp_id>/update', methods=['POST'])
@admin_required
def update_employee(emp_id):
    data = request.form
    updates = {}
    for field in ['role','branch','status','blocked']:
        if field in data: updates[field] = data[field]
    if data.get('password'):
        updates['password'] = generate_password_hash(data['password'])
    supabase.table('employees').update(updates).eq('id', emp_id).execute()
    return redirect('/admin')

@app.route('/admin/employee/<int:emp_id>/delete', methods=['POST'])
@admin_required
def delete_employee(emp_id):
    supabase.table('employees').delete().eq('id', emp_id).execute()
    return redirect('/admin')

@app.route('/admin/branch/add', methods=['POST'])
@admin_required
def add_branch():
    supabase.table('branches').insert({'name': request.form['name']}).execute()
    return redirect('/admin')

@app.route('/admin/branch/<int:branch_id>/delete', methods=['POST'])
@admin_required
def delete_branch(branch_id):
    supabase.table('branches').delete().eq('id', branch_id).execute()
    return redirect('/admin')

@app.route('/admin/contact/add', methods=['POST'])
@admin_required
def add_contact():
    supabase.table('contacts').insert({
        'full_name': request.form['full_name'],
        'role': request.form['role'],
        'branch': request.form.get('branch',''),
        'phone': request.form['phone']
    }).execute()
    return redirect('/admin')

@app.route('/admin/contact/<int:cid>/delete', methods=['POST'])
@admin_required
def delete_contact(cid):
    supabase.table('contacts').delete().eq('id', cid).execute()
    return redirect('/admin')

@app.route('/admin/delegation/add', methods=['POST'])
@admin_required
def add_delegation():
    delegate_id = request.form['delegate_id']
    role = request.form['role']
    supabase.table('role_delegations').insert({
        'delegate_id': delegate_id,
        'role': role,
        'active': True
    }).execute()
    return redirect('/admin')

@app.route('/admin/delegation/<int:did>/revoke', methods=['POST'])
@admin_required
def revoke_delegation(did):
    supabase.table('role_delegations').update({'active': False}).eq('id', did).execute()
    return redirect('/admin')

# ---------- PROFILE ----------
@app.route('/profile')
@login_required
def profile():
    emp = safe_data(execute_query(
        supabase.table('employees').select('*').eq('full_name', session['user']).limit(1)
    ))
    if emp:
        emp = emp[0]
    else:
        emp = {}
    return render_template('profile.html', employee=emp, company=COMPANY_NAME)

# ---------- RUN ----------
if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
