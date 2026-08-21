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
TARGET_SETTER_ROLES = ['Stock Controller','Assistant Stock Controller','Sales Manager','admin','ceo']

DIRECTORATE_ROLES = ['admin','ceo','HR','HR Assistant','Stock Controller','Assistant Stock Controller','Operations Manager','Sales Manager','Assistant Operations Manager']

COMPANY_NAME = 'Mediocare Pharmaceuticals Ltd'
LATE_GRACE_MINUTES = 20

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

# ---------- LEAVE WEEKDAY COUNT ----------
def count_weekdays(start_str, end_str):
    if not start_str or not end_str:
        return 0
    try:
        d1 = datetime.strptime(start_str, '%Y-%m-%d').date()
        d2 = datetime.strptime(end_str, '%Y-%m-%d').date()
    except:
        return 0
    count = 0
    while d1 <= d2:
        if d1.weekday() < 5:
            count += 1
        d1 += timedelta(days=1)
    return count

def parse_standin_dates(dates_str, start_str, end_str):
    if not dates_str:
        return 0
    start = datetime.strptime(start_str, '%Y-%m-%d').date()
    end = datetime.strptime(end_str, '%Y-%m-%d').date()
    count = 0
    for d in dates_str.split(','):
        d = d.strip()
        if not d:
            continue
        try:
            d_obj = datetime.strptime(d, '%Y-%m-%d').date()
        except:
            continue
        if start <= d_obj <= end and d_obj.weekday() < 5:
            count += 1
    return count

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
            raw_role = emp.get('role','Staff')
            session['role'] = normalize_role(raw_role)
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

# ---------- TRUST ROUTES ----------
@app.route('/privacy')
def privacy():
    return render_template('privacy.html', company=COMPANY_NAME)

@app.route('/.well-known/security.txt')
def security_txt():
    return (
        "Contact: mailto:support@mediocarepharma.com\n"
        "Expires: 2027-12-31T23:59:59.000Z\n"
        "Preferred-Languages: en\n"
        "Canonical: https://attendance-app-h847.onrender.com/.well-known/security.txt\n",
        200,
        {'Content-Type': 'text/plain'}
    )

@app.route('/robots.txt')
def robots():
    return (
        "User-agent: *\n"
        "Disallow: /admin\n"
        "Disallow: /check-in\n"
        "Disallow: /sales\n"
        "Disallow: /leaves\n"
        "Allow: /\n",
        200,
        {'Content-Type': 'text/plain'}
    )

@app.route('/google1102f1c28cc82b57.html')
def google_verification():
    return 'google-site-verification: google1102f1c28cc82b57.html', 200, {'Content-Type': 'text/html'}

# ---------- SIGNUP ----------
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
        if not name or not phone or not pw or not branch:
            return render_template('signup.html', branches=get_branch_names(), departments=DEPARTMENTS,
                roles=signup_roles, error='All fields are required, including Branch.')
        if branch not in get_branch_names():
            return render_template('signup.html', branches=get_branch_names(), departments=DEPARTMENTS,
                roles=signup_roles, error='Please select a valid branch.')
        check = execute_query(supabase.table('employees').select('id').eq('full_name',name))
        if safe_data(check):
            return render_template('signup.html', branches=get_branch_names(), departments=DEPARTMENTS,
                roles=signup_roles, error='Name already exists.')
        supabase.table('employees').insert({
            'full_name':name,'phone':phone,'password': generate_password_hash(pw),
            'department':dept,'branch':branch,'role': normalize_role(role),
            'status':'pending','shift_start':shift_start,'shift_end':shift_end
        }).execute()
        return render_template('signup.html', branches=get_branch_names(), departments=DEPARTMENTS,
            roles=signup_roles,
            success='Registration submitted! Welcome to {}!'.format(COMPANY_NAME))
    return render_template('signup.html', branches=get_branch_names(), departments=DEPARTMENTS,
        roles=signup_roles)

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
        on_leave_count = count_employees_on_leave()
    elif role in ['Store Manager','Operations Manager','Assistant Operations Manager']:
        team_names = [e['full_name'] for e in safe_data(execute_query(supabase.table('employees').select('full_name').eq('status','approved').in_('role',OPERATIONS_MANAGER_TEAM)))]
        att_r = execute_query(supabase.table('attendance').select('*').eq('date',today).in_('full_name',team_names))
        sales_r = execute_query(supabase.table('sales').select('total_sales').eq('date',today).in_('full_name',team_names)) if show_sales_card else []
        emp_r = execute_query(supabase.table('employees').select('id').eq('status','approved').in_('role',OPERATIONS_MANAGER_TEAM))
        on_leave_count = count_employees_on_leave(team_names=team_names)
    elif role == 'Sales Manager':
        team_names = [e['full_name'] for e in safe_data(execute_query(supabase.table('employees').select('full_name').eq('status','approved').in_('role',[MARKETER_ROLE,'Telesales'])))]
        team_names.append(un)
        att_r = execute_query(supabase.table('attendance').select('*').eq('date',today).in_('full_name',team_names))
        sales_r = execute_query(supabase.table('sales').select('total_sales').eq('date',today).in_('full_name',team_names)) if show_sales_card else []
        emp_r = execute_query(supabase.table('employees').select('id').eq('status','approved').in_('full_name',team_names))
        on_leave_count = count_employees_on_leave(team_names=team_names)
    elif role == 'Branch Manager':
        team_names = [e['full_name'] for e in safe_data(execute_query(supabase.table('employees').select('full_name').eq('status','approved').eq('branch',ub)))]
        att_r = execute_query(supabase.table('attendance').select('*').eq('date',today).in_('full_name',team_names))
        sales_r = execute_query(supabase.table('sales').select('total_sales').eq('date',today).in_('full_name',team_names)) if show_sales_card else []
        emp_r = execute_query(supabase.table('employees').select('id').eq('status','approved').eq('branch',ub))
        on_leave_count = count_employees_on_leave(team_names=team_names)
    else:
        emp_r = None
        att_r = execute_query(supabase.table('attendance').select('*').eq('date',today).eq('full_name',un))
        sales_r = execute_query(supabase.table('sales').select('total_sales').eq('date',today).eq('full_name',un))
        on_leave_count = count_employees_on_leave(single_user=un)

    total_emp = len(safe_data(emp_r)) if emp_r else 0
    att_data = safe_data(att_r)
    working = sum(1 for a in att_data if a.get('check_in') and not a.get('check_out'))
    checked_out = sum(1 for a in att_data if a.get('check_out'))
    late_count = sum(1 for a in att_data if a.get('status')=='late')
    total_sales = sum(float(s.get('total_sales',0)) for s in safe_data(sales_r)) if show_sales_card else 0

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

    # target progress
    target_progress = None
    target_achieved = False
    if role in SALES_SUBMIT_ROLES:
        month_str = now_eat().date().replace(day=1).strftime('%Y-%m')
        target = safe_data(execute_query(supabase.table('sales_targets').select('target_amount').eq('full_name',un).eq('month',month_str).limit(1)))
        if target:
            target_amt = float(target[0]['target_amount'])
            month_start = datetime.strptime(month_str + '-01', '%Y-%m-%d').date()
            my_sales = safe_data(execute_query(supabase.table('sales').select('total_sales').eq('full_name',un).gte('date',str(month_start)).lte('date',today)))
            month_total = sum(float(s['total_sales']) for s in my_sales)
            remaining = max(0, target_amt - month_total)
            target_progress = {
                'target': target_amt,
                'current': month_total,
                'remaining': remaining,
                'percent': round((month_total / target_amt * 100), 1) if target_amt > 0 else 0,
                'achieved': month_total >= target_amt
            }
            if target_progress['achieved']:
                target_achieved = True

    return render_template('index.html',
        total_employees=total_emp, working=working, checked_out=checked_out,
        late_count=late_count, on_leave_count=on_leave_count,
        total_sales=total_sales, recent_records=records,
        user_checked_in=uci, user_checked_out=uco, user_status=user_status,
        pending_count=pending, show_sales_card=show_sales_card,
        target_achieved=target_achieved, target_progress=target_progress,
        leave_remaining=leave_remaining,
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

# ---------- ADMIN RESET ATTENDANCE ----------
@app.route('/admin/reset-attendance', methods=['GET','POST'])
@login_required
@admin_required
def reset_attendance():
    if request.method == 'POST':
        emp_name = request.form.get('employee_name','').strip()
        att_date = request.form.get('attendance_date','').strip()
        if emp_name and att_date:
            supabase.table('attendance').delete().eq('full_name', emp_name).eq('date', att_date).execute()
            return redirect('/admin/reset-attendance?success=1')
        return redirect('/admin/reset-attendance?error=1')
    employees = safe_data(execute_query(
        supabase.table('employees').select('full_name').eq('status','approved').order('full_name')
    ))
    return render_template('admin_reset_attendance.html', employees=employees,
                           success=request.args.get('success',''), error=request.args.get('error',''),
                           company=COMPANY_NAME)

# ---------- ADMIN DELETE LEAVE ----------
@app.route('/admin/delete-leave/<int:lid>', methods=['POST'])
@login_required
@admin_required
def admin_delete_leave(lid):
    supabase.table('leaves').delete().eq('id', lid).execute()
    return redirect(request.referrer or '/hr/leaves')

# ---------- ADMIN EDIT LEAVE ----------
@app.route('/admin/edit-leave/<int:lid>', methods=['POST'])
@login_required
@admin_required
def admin_edit_leave(lid):
    data = {
        'leave_start': request.form.get('leave_start',''),
        'leave_end': request.form.get('leave_end',''),
        'total_days': int(request.form.get('total_days',0)),
        'leave_type': request.form.get('leave_type','Annual Leave'),
        'reason': request.form.get('reason',''),
        'handover_notes': request.form.get('handover_notes',''),
        'backup_person': request.form.get('backup_person',''),
        'emergency_contact': request.form.get('emergency_contact',''),
        'standin_name': request.form.get('standin_name',''),
        'standin_dates': request.form.get('standin_dates',''),
    }
    supabase.table('leaves').update(data).eq('id', lid).execute()
    return redirect(request.referrer or '/hr/leaves')

# ---------- HR ANNUAL LEAVE MANAGER (dual override) ----------
@app.route('/hr/annual-leave')
@login_required
def hr_annual_leave():
    if session.get('role') not in ['HR','HR Assistant','admin','ceo']:
        return redirect('/')
    year = str(now_eat().year)

    leaves = safe_data(execute_query(
        supabase.table('leaves')
        .select('full_name, total_days, leave_type, status')
        .eq('leave_type', 'Annual Leave')
        .eq('status', 'approved_final')
        .gte('leave_start', f'{year}-01-01')
        .lte('leave_start', f'{year}-12-31')
        .limit(10000)
    ))

    system_used = defaultdict(int)
    for l in leaves:
        system_used[l['full_name']] += int(l['total_days'])

    employees = safe_data(execute_query(
        supabase.table('employees')
        .select('id, full_name, department, branch, role, annual_leave_remaining_override, annual_leave_days_taken_override')
        .eq('status', 'approved')
        .order('full_name')
        .limit(1000)
    ))

    for emp in employees:
        sys_used = system_used.get(emp['full_name'], 0)
        days_taken_override = emp.get('annual_leave_days_taken_override')
        if days_taken_override is not None:
            total_used = days_taken_override
            remaining = max(0, 21 - total_used)
        else:
            remaining_override = emp.get('annual_leave_remaining_override')
            if remaining_override is not None:
                remaining = max(0, remaining_override - sys_used)
                total_used = 21 - remaining
            else:
                remaining = max(0, 21 - sys_used)
                total_used = sys_used
        emp['used_days'] = total_used
        emp['remaining'] = remaining

    return render_template('hr_annual_leave.html', employees=employees, year=year, company=COMPANY_NAME)

@app.route('/hr/annual-leave/update/<int:eid>', methods=['POST'])
@login_required
def update_annual_leave_override(eid):
    if session.get('role') not in ['HR','HR Assistant','admin','ceo']:
        return redirect('/')
    remaining = request.form.get('remaining', '')
    days_taken = request.form.get('days_taken', '')
    try:
        remaining_int = int(remaining) if remaining else None
        days_taken_int = int(days_taken) if days_taken else None
    except ValueError:
        return redirect('/hr/annual-leave')
    supabase.table('employees').update({
        'annual_leave_remaining_override': remaining_int,
        'annual_leave_days_taken_override': days_taken_int
    }).eq('id', eid).execute()
    return redirect('/hr/annual-leave')

# ---------- ABSENT TODAY ----------
@app.route('/absent-today')
@login_required
def absent_today():
    allowed_roles = ['admin','ceo','HR','HR Assistant','Stock Controller','Assistant Stock Controller',
                     'Operations Manager','Sales Manager','Store Manager','Branch Manager','Procurement Officer']
    if session.get('role') not in allowed_roles:
        return redirect('/')
    today = str(now_eat().date())
    all_employees = safe_data(execute_query(
        supabase.table('employees').select('full_name, branch, department, role')
        .eq('status','approved').order('full_name')
    ))
    checked_in = safe_data(execute_query(
        supabase.table('attendance').select('full_name').eq('date', today)
    ))
    checked_in_names = set(a['full_name'] for a in checked_in)
    leaves = safe_data(execute_query(
        supabase.table('leaves').select('full_name')
        .in_('status', ['approved_final','approved_by_manager','approved_by_procurement','approved_by_ops'])
        .lte('leave_start', today).gte('leave_end', today)
    ))
    on_leave_names = set(l['full_name'] for l in leaves)
    absent = []
    for emp in all_employees:
        if emp['full_name'] not in checked_in_names and emp['full_name'] not in on_leave_names:
            absent.append(emp)
    return render_template('absent_today.html', absent=absent, today=today, company=COMPANY_NAME)

# ---------- SALES, PROFILE, REPORTS, etc. (unchanged from previous complete version) ----------
# ... include all other routes exactly as they were in the last full version ...
# (For brevity, they are omitted here but must be present in the final file.)

if __name__=='__main__':
    app.run(host='0.0.0.0',port=5000)
