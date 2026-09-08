from flask import Flask, render_template, request, redirect, url_for, session, Response
from datetime import date, datetime, timedelta, timezone
from supabase import create_client
from functools import wraps
from collections import defaultdict
from werkzeug.security import generate_password_hash, check_password_hash
import pytz, time, csv, io, math
import re
from apscheduler.schedulers.background import BackgroundScheduler
import atexit

def strip_emojis(text):
    emoji_pattern = re.compile(
        "["
        "\U0001F600-\U0001F64F"
        "\U0001F300-\U0001F5FF"
        "\U0001F680-\U0001F6FF"
        "\U0001F1E0-\U0001F1FF"
        "\U00002702-\U000027B0"
        "\U000024C2-\U0001F251"
        "\U0001f900-\U0001f9ff"
        "\U0001fa70-\U0001fa73"
        "\U0001fa78-\U0001fa7a"
        "\U0001fa80-\U0001fa82"
        "\U0001fa90-\U0001fa95"
        "\U0001fa00-\U0001fa53"
        "\U0001fae0-\U0001fae8"
        "\U0001faf0-\U0001faf6"
        "\U00002600-\U000027BF"
        "\U0001F000-\U0001F02F"
        "\U0001F0A0-\U0001F0FF"
        "\U0001F300-\U0001F5FF"
        "\U0001F600-\U0001F64F"
        "\U0001F680-\U0001F6FF"
        "\U0001F700-\U0001F77F"
        "\U0001F780-\U0001F7FF"
        "\U0001F800-\U0001F8FF"
        "\U0001F900-\U0001F9FF"
        "\U0001FA00-\U0001FA6F"
        "\U0001FA70-\U0001FAFF"
        "\U0000231A-\U0000231B"
        "\U000023E9-\U000023EC"
        "\U000023F0"
        "\U000023F3"
        "\U000025AA-\U000025FE"
        "\U00002B50"
        "\U00002B55"
        "\U00002764"
        "\U00002705"
        "\U00002753"
        "\U00002754"
        "\U00002795"
        "\U00002796"
        "\U00002797"
        "\U000027A1"
        "\U000027B0"
        "\U000027BF"
        "\U0001F1E6-\U0001F1FF"
        "]+",
        flags=re.UNICODE,
    )
    return emoji_pattern.sub("", text)

app = Flask(__name__)
app.secret_key = 'mediocare-attendance-secret-2024'

app.config.update(
    SESSION_COOKIE_HTTPONLY = True,
    SESSION_COOKIE_SECURE = True,
    SESSION_COOKIE_SAMESITE = 'Lax'
)

@app.after_request
def remove_emoji_from_response(response):
    if response.content_type and 'text/html' in response.content_type:
        response.set_data(strip_emojis(response.get_data(as_text=True)))
    return response

SUPABASE_URL = 'https://lznqrkujlrcxcxizygzq.supabase.co'
SUPABASE_KEY = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Imx6bnFya3VqbHJjeGN4aXp5Z3pxIiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc4NDU2MjA2NSwiZXhwIjoyMTAwMTM4MDY1fQ.XmMAGB1G8hOOLr7PTnn100cifWMkja2gcZfKRSBI5Ec'

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
EAT = timezone(timedelta(hours=3))

# ==================== CONSTANTS ====================
DEPARTMENTS = ['Staff','Store','Dispatch','Sales','Stock Control','Procurement','Accounts Office','Operations','Branch Management','Management']
ALL_ROLES = [
    'Staff','Person in Charge','Branch Order Processor','Stock Controller','Assistant Stock Controller',
    'Procurement Officer','Accountant','Accountant Assistant','Cashier',
    'HR','HR Assistant','Sales Manager','Marketers','Telesales','Dispatch Personnel',
    'Operations Manager','Assistant Operations Manager','Store Manager','Storekeeper',
    'Store Personnel','Dispatch Supervisor','Dispatch Assistant','Cleaner',
    'Riders','Drivers','Security','General Manager','admin','ceo'
]
NO_CHECKIN_ROLES = ['admin','ceo']
FULL_ACCESS_ROLES = ['admin','ceo']
SALES_SUBMIT_ROLES = ['Staff','Person in Charge']
SALES_VIEW_ROLES = ['admin','ceo','Stock Controller','Assistant Stock Controller','Accountant','Accountant Assistant']
STORE_MANAGER_TEAM = ['Store Assistant','Store Personnel','Storekeeper']
OPERATIONS_MANAGER_TEAM = [
    'Branch Order Processor',
    'Store Manager','Store Assistant','Store Personnel','Storekeeper',
    'Dispatch Supervisor','Dispatch Assistant','Dispatch Personnel',
    'Riders','Drivers','Security','Cleaner'
]
RIDER_DRIVER_ROLES = ['Riders','Drivers']
MARKETER_ROLE = 'Marketers'
SALES_MANAGER_ROLE = 'Sales Manager'
TARGET_SETTER_ROLES = ['Stock Controller','Assistant Stock Controller','Sales Manager','admin','ceo']

MANAGER_LIVE_BRANCHES = ['Kisumu HQ', 'Kisumu Retail']
MANAGER_ATTENDANCE_ROLES = [
    'Person in Charge','Operations Manager','Assistant Operations Manager','Store Manager',
    'Sales Manager','Procurement Officer','Stock Controller','Assistant Stock Controller',
    'Accountant','Accountant Assistant','HR','HR Assistant','Cashier','General Manager',
    'Branch Order Processor'
]

DIRECTORATE_ROLES = ['admin','ceo','HR','HR Assistant','Stock Controller','Assistant Stock Controller','Operations Manager','Sales Manager','Assistant Operations Manager']

COMPANY_NAME = 'Mediocare Pharmaceuticals Ltd'
LATE_GRACE_MINUTES = 20

ATTENDANCE_RETENTION_DAYS = 60
INDIVIDUAL_SALES_RETENTION_DAYS = 120
BRANCH_SALES_RETENTION_DAYS = 180

# ==================== HELPERS ====================
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
    if role_lower == 'branch manager':
        return 'Person in Charge'
    if role_lower == 'manager':
        return 'General Manager'
    for r in ALL_ROLES:
        if r.lower() == role_lower:
            return r
    return role

@app.before_request
def normalize_session_role():
    if 'role' in session:
        session['role'] = normalize_role(session['role'])

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

def get_manager_live_team_names():
    employees = safe_data(execute_query(
        supabase.table('employees').select('full_name').eq('status','approved')
        .or_('branch.in.("Kisumu HQ","Kisumu Retail"),department.eq.Telesales')
    ))
    return [e['full_name'] for e in employees]

def get_manager_attendance_team_names():
    employees = safe_data(execute_query(
        supabase.table('employees').select('full_name').eq('status','approved')
        .in_('role', MANAGER_ATTENDANCE_ROLES)
    ))
    return [e['full_name'] for e in employees]

def add_audit_log(action, target=None, details=None):
    try:
        supabase.table('audit_logs').insert({
            'action': action,
            'performed_by': session.get('user','Unknown'),
            'target': target,
            'details': details or {}
        }).execute()
    except Exception as e:
        print(f"Audit log failed: {e}")

# ==================== GEOFENCE ====================
def haversine(lat1, lon1, lat2, lon2):
    R = 6371000
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)
    a = math.sin(delta_phi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(delta_lambda/2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
    return R * c

def geofence_status(lat, lng, branch):
    if not lat or not lng or not branch:
        return 'unknown'
    branch_lat = branch.get('latitude')
    branch_lng = branch.get('longitude')
    if branch_lat is None or branch_lng is None:
        return 'unknown'
    try:
        distance = haversine(float(lat), float(lng), float(branch_lat), float(branch_lng))
    except:
        return 'unknown'
    return 'in_branch' if distance <= 150 else 'out_of_branch'

FIELD_ROLES = ['Marketers', 'Drivers']

# ==================== LEAVE HELPERS ====================
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

def get_approval_chain(employee_role):
    role_lower = employee_role.strip().lower()
    chain = []
    if role_lower in ['drivers','riders','dispatch personnel','security','cleaner']:
        chain = [
            {'from_status': 'pending', 'to_status': 'approved_by_manager',
             'allowed_roles': ['Operations Manager','Assistant Operations Manager','General Manager']},
            {'from_status': 'approved_by_manager', 'to_status': 'approved_final',
             'allowed_roles': ['HR','HR Assistant']}
        ]
    elif role_lower == 'store manager':
        chain = [
            {'from_status': 'pending', 'to_status': 'approved_by_manager',
             'allowed_roles': ['Operations Manager','Assistant Operations Manager','General Manager']},
            {'from_status': 'approved_by_manager', 'to_status': 'approved_by_procurement',
             'allowed_roles': ['Procurement Officer']},
            {'from_status': 'approved_by_procurement', 'to_status': 'approved_final',
             'allowed_roles': ['HR','HR Assistant']}
        ]
    elif role_lower == 'person in charge':
        chain = [
            {'from_status': 'pending', 'to_status': 'approved_by_manager',
             'allowed_roles': ['Stock Controller','Assistant Stock Controller']},
            {'from_status': 'approved_by_manager', 'to_status': 'approved_final',
             'allowed_roles': ['CEO','HR','HR Assistant']}
        ]
    elif role_lower == 'assistant operations manager':
        chain = [
            {'from_status': 'pending', 'to_status': 'approved_by_manager',
             'allowed_roles': ['Operations Manager','General Manager']},
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
             'allowed_roles': ['Operations Manager','Assistant Operations Manager','General Manager']},
            {'from_status': 'approved_by_manager', 'to_status': 'approved_final',
             'allowed_roles': ['HR','HR Assistant']}
        ]
    elif role_lower in ['store personnel','storekeeper','store assistant']:
        chain = [
            {'from_status': 'pending', 'to_status': 'approved_by_manager',
             'allowed_roles': ['Store Manager']},
            {'from_status': 'approved_by_manager', 'to_status': 'approved_by_ops',
             'allowed_roles': ['Operations Manager','Assistant Operations Manager','General Manager']},
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
             'allowed_roles': ['Person in Charge']},
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

# ==================== SCHEDULER ====================
def cleanup_old_records():
    try:
        today = now_eat().date()
        att_cutoff = today - timedelta(days=ATTENDANCE_RETENTION_DAYS)
        ind_sales_cutoff = today - timedelta(days=INDIVIDUAL_SALES_RETENTION_DAYS)
        branch_sales_cutoff = today - timedelta(days=BRANCH_SALES_RETENTION_DAYS)

        att_result = supabase.table('attendance').delete().lt('date', str(att_cutoff)).execute()
        deleted_att = len(safe_data(att_result)) if hasattr(att_result, 'data') else 0

        ind_result = supabase.table('sales').delete().lt('date', str(ind_sales_cutoff)).execute()
        deleted_ind = len(safe_data(ind_result)) if hasattr(ind_result, 'data') else 0

        branch_result = supabase.table('branch_sales').delete().lt('date', str(branch_sales_cutoff)).execute()
        deleted_branch = len(safe_data(branch_result)) if hasattr(branch_result, 'data') else 0

        loc_result = supabase.table('marketer_locations').delete().lt('date', str(att_cutoff)).execute()
        deleted_loc = len(safe_data(loc_result)) if hasattr(loc_result, 'data') else 0
        rep_result = supabase.table('customer_reports').delete().lt('date', str(ind_sales_cutoff)).execute()
        deleted_rep = len(safe_data(rep_result)) if hasattr(rep_result, 'data') else 0

        supabase.table('audit_logs').insert({
            'action': 'auto_cleanup',
            'performed_by': 'SYSTEM',
            'details': {
                'attendance_cutoff': str(att_cutoff),
                'individual_sales_cutoff': str(ind_sales_cutoff),
                'branch_sales_cutoff': str(branch_sales_cutoff),
                'deleted_attendance': deleted_att,
                'deleted_individual_sales': deleted_ind,
                'deleted_branch_sales': deleted_branch,
                'deleted_locations': deleted_loc,
                'deleted_reports': deleted_rep
            }
        }).execute()
        print(f"Cleanup done: att={deleted_att}, ind_sales={deleted_ind}, branch_sales={deleted_branch}, loc={deleted_loc}, reports={deleted_rep}")
    except Exception as e:
        print(f"Cleanup failed: {e}")

scheduler = BackgroundScheduler()
scheduler.add_job(cleanup_old_records, 'cron', hour=3, minute=0)
scheduler.start()
atexit.register(lambda: scheduler.shutdown())

# ==================== FORCE LOGOUT BLOCKED USERS ====================
@app.before_request
def block_check():
    if 'user' in session and request.path not in ['/login','/logout','/static','/favicon.ico']:
        emp = safe_data(execute_query(
            supabase.table('employees').select('blocked').eq('full_name', session['user']).limit(1)
        ))
        if emp and emp[0].get('blocked'):
            session.clear()
            return redirect('/login')

# ==================== AUTH ====================
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

# ==================== TRUST ROUTES ====================
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

# ==================== SIGNUP ====================
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

# ==================== DASHBOARD ====================
@app.route('/')
@login_required
def home():
    today = str(now_eat().date())
    role = session.get('role','Staff')
    ub = session.get('branch','')
    un = session.get('user','')

    if role == MARKETER_ROLE:
        return redirect('/marketer')

    if role == 'General Manager':
        return redirect('/manager-dashboard')

    show_sales_card = (
        role in ['Staff','Person in Charge','admin','ceo'] or
        session.get('department','') in ['Stock Control','Stock Assistant','Accounts Office','Accountant','Accountant Assistant']
    )

    team_names = None
    if role in FULL_ACCESS_ROLES or role in ['HR','HR Assistant'] or can_view_all():
        team_names = None
    elif role == 'General Manager':
        team_names = get_manager_attendance_team_names()
    elif role in ['Store Manager','Operations Manager','Assistant Operations Manager']:
        team_names = [e['full_name'] for e in safe_data(execute_query(
            supabase.table('employees').select('full_name').eq('status','approved').in_('role', OPERATIONS_MANAGER_TEAM)
        ))]
        if un not in team_names: team_names.append(un)
    elif role == 'Sales Manager':
        team_names = [e['full_name'] for e in safe_data(execute_query(
            supabase.table('employees').select('full_name').eq('status','approved').in_('role', [MARKETER_ROLE, 'Telesales'])
        ))]
        if un not in team_names: team_names.append(un)
    elif role == 'Person in Charge':
        team_names = [e['full_name'] for e in safe_data(execute_query(
            supabase.table('employees').select('full_name').eq('status','approved').eq('branch', ub)
        ))]
        if un not in team_names: team_names.append(un)
    else:
        team_names = [un]

    def apply_team(query):
        if team_names is not None:
            return query.in_('full_name', team_names)
        return query

    if role in FULL_ACCESS_ROLES or role in ['HR','HR Assistant'] or can_view_all():
        emp_query = supabase.table('employees').select('id', count='exact').eq('status','approved').eq('blocked',False)
        total_emp = execute_query(emp_query).count
    elif role in ['Store Manager','Operations Manager','Assistant Operations Manager','Sales Manager','Person in Charge','General Manager']:
        emp_query = supabase.table('employees').select('id', count='exact').eq('status','approved').in_('full_name', team_names)
        total_emp = execute_query(emp_query).count
    else:
        total_emp = 0

    working_query = apply_team(
        supabase.table('attendance').select('id', count='exact')
        .eq('date', today)
        .not_.is_('check_in', 'null')
        .is_('check_out', 'null')
    )
    working = execute_query(working_query).count

    checked_out_query = apply_team(
        supabase.table('attendance').select('id', count='exact')
        .eq('date', today)
        .not_.is_('check_out', 'null')
    )
    checked_out = execute_query(checked_out_query).count

    late_query = apply_team(
        supabase.table('attendance').select('id', count='exact')
        .eq('date', today)
        .eq('status', 'late')
    )
    late_count = execute_query(late_query).count

    on_leave_count = count_employees_on_leave(team_names=team_names)

    if show_sales_card:
        # Individual sales
        sales_query = apply_team(
            supabase.table('sales').select('total_sales').eq('date', today)
        )
        sales_data = safe_data(execute_query(sales_query))
        total_sales = sum(float(s.get('total_sales',0)) for s in sales_data)

        # Branch sales
        branch_sales_total = 0
        if role == 'Staff':
            branch_sales_total = 0
        elif role == 'Person in Charge':
            branch_sales_query = supabase.table('branch_sales').select('total_sales').eq('date', today).eq('branch', ub)
            branch_data = safe_data(execute_query(branch_sales_query))
            branch_sales_total = sum(float(s.get('total_sales',0)) for s in branch_data)
        elif can_view_all() or role in FULL_ACCESS_ROLES:
            branch_sales_query = supabase.table('branch_sales').select('total_sales').eq('date', today)
            branch_data = safe_data(execute_query(branch_sales_query))
            branch_sales_total = sum(float(s.get('total_sales',0)) for s in branch_data)

        total_sales_combined = total_sales + branch_sales_total
    else:
        total_sales = 0
        branch_sales_total = 0
        total_sales_combined = 0

    recent_query = apply_team(
        supabase.table('attendance').select('*').eq('date', today).order('check_in', desc=True).limit(10)
    )
    att_data = safe_data(execute_query(recent_query))

    if att_data:
        names = [rec['full_name'] for rec in att_data]
        emp_details = safe_data(execute_query(
            supabase.table('employees').select('full_name, role, department').in_('full_name', names)
        ))
        emp_map = {e['full_name']: e for e in emp_details}
    else:
        emp_map = {}

    records = []
    for rec in att_data:
        st = rec.get('status','present')
        if rec.get('check_out'): label = 'Checked Out'
        elif st == 'late': label = 'Arrived Late'
        else: label = 'Working'
        emp = emp_map.get(rec['full_name'], {})
        records.append({
            'full_name': rec['full_name'],
            'department': emp.get('department', rec.get('department','')),
            'role': emp.get('role',''),
            'check_in': rec.get('check_in','—'),
            'check_out': rec.get('check_out','—'),
            'status': st,
            'label': label
        })

    uci=uco=False; user_status=''
    if role not in NO_CHECKIN_ROLES:
        my = safe_data(execute_query(
            supabase.table('attendance').select('*').eq('full_name', un).eq('date', today)
        ))
        if my:
            uci = bool(my[0].get('check_in'))
            uco = bool(my[0].get('check_out'))
            if uco: user_status = 'Checked Out'
            elif uci: user_status = 'Working'
            else: user_status = 'Not Checked In'

    pending = 0
    if role in FULL_ACCESS_ROLES:
        pending = execute_query(
            supabase.table('employees').select('id', count='exact').eq('status','pending')
        ).count

    target_progress = None
    target_achieved = False
    if role in SALES_SUBMIT_ROLES:
        month_str = now_eat().date().replace(day=1).strftime('%Y-%m')
        target = safe_data(execute_query(
            supabase.table('sales_targets').select('target_amount').eq('full_name', un).eq('month', month_str).limit(1)
        ))
        if target:
            target_amt = float(target[0]['target_amount'])
            month_start = datetime.strptime(month_str + '-01', '%Y-%m-%d').date()
            my_sales = safe_data(execute_query(
                supabase.table('sales').select('total_sales').eq('full_name', un)
                .gte('date', str(month_start)).lte('date', today)
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
            if target_progress['achieved']:
                target_achieved = True

    return render_template('index.html',
        total_employees=total_emp, working=working, checked_out=checked_out,
        late_count=late_count, on_leave_count=on_leave_count,
        total_sales=total_sales_combined,
        individual_sales_total=total_sales,
        branch_sales_total=branch_sales_total,
        recent_records=records,
        user_checked_in=uci, user_checked_out=uco, user_status=user_status,
        pending_count=pending, show_sales_card=show_sales_card,
        target_achieved=target_achieved, target_progress=target_progress,
        leave_remaining=leave_remaining if 'leave_remaining' in locals() else None,
        company=COMPANY_NAME)

# ==================== MANAGER DASHBOARD (General Manager) ====================
@app.route('/manager-dashboard')
@login_required
def manager_dashboard():
    if session.get('role') != 'General Manager':
        return redirect('/')
    today = str(now_eat().date())
    un = session.get('user')
    team_names = get_manager_attendance_team_names()

    total_emp = len(team_names)
    working = execute_query(
        supabase.table('attendance').select('id', count='exact')
        .eq('date', today).in_('full_name', team_names)
        .not_.is_('check_in', 'null').is_('check_out', 'null')
    ).count
    checked_out = execute_query(
        supabase.table('attendance').select('id', count='exact')
        .eq('date', today).in_('full_name', team_names)
        .not_.is_('check_out', 'null')
    ).count
    late_count = execute_query(
        supabase.table('attendance').select('id', count='exact')
        .eq('date', today).in_('full_name', team_names)
        .eq('status', 'late')
    ).count
    on_leave_count = count_employees_on_leave(team_names=team_names)

    recent_query = supabase.table('attendance').select('*').eq('date', today).in_('full_name', team_names).order('check_in', desc=True).limit(10)
    att_data = safe_data(execute_query(recent_query))
    emp_details = safe_data(execute_query(
        supabase.table('employees').select('full_name, role, department').in_('full_name', team_names)
    ))
    emp_map = {e['full_name']: e for e in emp_details}
    records = []
    for rec in att_data:
        st = rec.get('status','present')
        if rec.get('check_out'): label = 'Checked Out'
        elif st == 'late': label = 'Arrived Late'
        else: label = 'Working'
        emp = emp_map.get(rec['full_name'], {})
        records.append({
            'full_name': rec['full_name'],
            'department': emp.get('department', rec.get('department','')),
            'role': emp.get('role',''),
            'check_in': rec.get('check_in','—'),
            'check_out': rec.get('check_out','—'),
            'status': st,
            'label': label
        })

    # Marketer management data
    marketers = safe_data(execute_query(
        supabase.table('employees').select('full_name').eq('status','approved').eq('role','Marketers').order('full_name')
    ))
    pending_checkins = safe_data(execute_query(
        supabase.table('marketer_checkins').select('*').eq('date',today).eq('status','pending').order('created_at',desc=True).limit(50)
    ))
    approved_checkins = safe_data(execute_query(
        supabase.table('marketer_checkins').select('*').eq('date',today).eq('status','approved').order('check_in_time').limit(50)
    ))
    assigned = safe_data(execute_query(
        supabase.table('assigned_places').select('*').order('date_assigned',desc=True).limit(100)
    ))
    reports = safe_data(execute_query(
        supabase.table('customer_reports').select('*').eq('date',today).order('created_at',desc=True).limit(50)
    ))

    return render_template('manager_dashboard.html',
        total_employees=total_emp, working=working, checked_out=checked_out,
        late_count=late_count, on_leave_count=on_leave_count,
        recent_records=records, today=today, company=COMPANY_NAME,
        marketers=marketers, pending_checkins=pending_checkins,
        approved_checkins=approved_checkins, assigned=assigned, reports=reports)

# ==================== ADMIN PANEL ====================
# (all other routes unchanged, but include the target route with fix)
@app.route('/targets', methods=['GET','POST'])
@login_required
def targets_page():
    if session.get('role') not in TARGET_SETTER_ROLES: return redirect('/')
    user_role = session.get('role')

    # Only Staff and Person in Charge
    employees = safe_data(execute_query(
        supabase.table('employees')
        .select('full_name')
        .eq('status','approved')
        .in_('role', ['Staff','Person in Charge'])
        .order('full_name')
    ))
    branches = get_branch_names()

    individual_targets = safe_data(execute_query(
        supabase.table('sales_targets').select('*').order('month', desc=True).order('full_name').limit(200)
    ))
    branch_targets = []
    try:
        branch_targets = safe_data(execute_query(
            supabase.table('branch_targets').select('*').order('month', desc=True).order('branch').limit(200)
        ))
    except:
        print("branch_targets table may not exist")

    if request.method == 'POST':
        target_type = request.form.get('target_type')
        month = request.form.get('month','')
        amount = request.form.get('amount','0')
        try:
            amt = float(amount)
            if amt <= 0: raise ValueError
        except:
            return redirect('/targets?error=1')

        if target_type == 'individual':
            employee = request.form.get('employee_name','').strip()
            if not employee or not month:
                return redirect('/targets?error=1')
            supabase.table('sales_targets').upsert({
                'full_name': employee, 'month': month,
                'target_amount': amt, 'set_by': session.get('user')
            }, on_conflict='full_name,month').execute()
            add_audit_log('set_individual_target', target=employee, details={'month':month,'amount':amt})
        elif target_type == 'branch':
            branch = request.form.get('branch_name','').strip()
            if not branch or not month:
                return redirect('/targets?error=1')
            supabase.table('branch_targets').upsert({
                'branch': branch, 'month': month,
                'target_amount': amt, 'set_by': session.get('user')
            }, on_conflict='branch,month').execute()
            add_audit_log('set_branch_target', target=branch, details={'month':month,'amount':amt})
        return redirect('/targets')

    return render_template('targets.html',
                           employees=employees,
                           branches=branches,
                           individual_targets=individual_targets,
                           branch_targets=branch_targets,
                           today=str(now_eat().date()),
                           company=COMPANY_NAME)

# ==================== MARKETER SUBMIT LOCATION (success redirect) ====================
@app.route('/marketer/submit-location', methods=['POST'])
@login_required
def submit_marketer_location():
    if session.get('role') != MARKETER_ROLE: return redirect('/check-in')
    un = session.get('user'); today = str(now_eat().date()); now = now_eat().strftime('%H:%M:%S')
    lat = request.form.get('lat',''); lng = request.form.get('lng',''); loc = request.form.get('location','')
    supabase.table('marketer_locations').insert({
        'full_name': un, 'date': today, 'time': now, 'lat': lat, 'lng': lng, 'location': loc
    }).execute()
    return redirect('/marketer?location=ok')

# ==================== ERROR HANDLER ====================
@app.errorhandler(Exception)
def handle_exception(e):
    print(f"Unhandled error: {e}")
    return render_template('error.html', error=str(e)), 500

if __name__=='__main__':
    app.run(host='0.0.0.0',port=5000)
