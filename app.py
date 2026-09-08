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

@app.route('/admin/cleanup', methods=['POST'])
@login_required
@admin_required
def manual_cleanup():
    cleanup_old_records()
    return redirect('/admin?cleanup=done')

@app.route('/admin/block/<int:eid>', methods=['POST'])
@login_required
@admin_required
def block_employee(eid):
    supabase.table('employees').update({'blocked':True}).eq('id',eid).execute()
    add_audit_log('block_employee', target=str(eid))
    return redirect('/employees')

@app.route('/admin/unblock/<int:eid>', methods=['POST'])
@login_required
@admin_required
def unblock_employee(eid):
    supabase.table('employees').update({'blocked':False}).eq('id',eid).execute()
    add_audit_log('unblock_employee', target=str(eid))
    return redirect('/employees')

# ==================== APPROVALS ====================
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
    add_audit_log('approve_employee', target=str(eid))
    return redirect('/approvals')

@app.route('/approvals/reject/<int:eid>', methods=['POST'])
@login_required
@admin_required
def reject(eid):
    supabase.table('employees').delete().eq('id',eid).execute()
    add_audit_log('reject_employee', target=str(eid))
    return redirect('/approvals')

# ==================== ADMIN SALES MANAGEMENT ====================
@app.route('/admin/sales')
@login_required
@admin_required
def admin_sales():
    fd = request.args.get('from_date','')
    td = request.args.get('to_date','')
    stype = request.args.get('type','all')
    page = int(request.args.get('page',1))
    per_page = 50
    offset = (page-1)*per_page

    sales = []
    branch_sales = []

    if stype in ['individual','all']:
        q1 = supabase.table('sales').select('*').order('date',desc=True)
        if fd and td: q1 = q1.gte('date',fd).lte('date',td)
        q1 = q1.limit(per_page).offset(offset)
        sales = safe_data(execute_query(q1))
        for s in sales:
            s['_type'] = 'Individual'

    if stype in ['branch','all']:
        q2 = supabase.table('branch_sales').select('*').order('date',desc=True)
        if fd and td: q2 = q2.gte('date',fd).lte('date',td)
        q2 = q2.limit(per_page).offset(offset)
        branch_sales = safe_data(execute_query(q2))
        for s in branch_sales:
            s['_type'] = 'Branch'

    all_sales = sales + branch_sales
    all_sales.sort(key=lambda x: (x['date'], x.get('id',0)), reverse=True)

    has_next = (len(all_sales) == per_page)
    return render_template('admin_sales.html', sales=all_sales, from_date=fd, to_date=td, stype=stype,
                         page=page, has_next=has_next, company=COMPANY_NAME)

@app.route('/admin/sales/bulk-delete', methods=['POST'])
@login_required
@admin_required
def bulk_delete_sales():
    ids = request.form.getlist('sale_ids')
    stype = request.form.get('type','individual')
    if not ids:
        return redirect(request.referrer or '/admin/sales')
    try:
        for sid in ids:
            if stype == 'branch':
                supabase.table('branch_sales').delete().eq('id', int(sid)).execute()
            else:
                supabase.table('sales').delete().eq('id', int(sid)).execute()
        add_audit_log('bulk_delete_sales', target=f'{len(ids)} records', details={'type':stype})
    except Exception as e:
        print(f"Bulk delete error: {e}")
    return redirect(request.referrer or '/admin/sales')

@app.route('/admin/sales/delete/<int:sid>', methods=['POST'])
@login_required
@admin_required
def delete_sale(sid):
    stype = request.args.get('type', 'individual')
    if stype == 'branch':
        supabase.table('branch_sales').delete().eq('id', sid).execute()
    else:
        supabase.table('sales').delete().eq('id', sid).execute()
    add_audit_log('delete_sale', target=str(sid))
    return redirect(request.referrer or '/admin/sales')

@app.route('/admin/sales/edit/<int:sid>', methods=['POST'])
@login_required
@admin_required
def edit_sale(sid):
    stype = request.args.get('type', 'individual')
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

    if stype == 'branch':
        supabase.table('branch_sales').update({
            'mpesa_sales': mpesa,
            'cash_sales': cash,
            'total_sales': total,
            'notes': notes,
            'expenses': expenses
        }).eq('id', sid).execute()
    else:
        supabase.table('sales').update({
            'mpesa_sales': mpesa,
            'cash_sales': cash,
            'total_sales': total,
            'notes': notes,
            'expenses': expenses
        }).eq('id', sid).execute()
    add_audit_log('edit_sale', target=str(sid))
    return redirect(request.referrer or '/admin/sales')

# ==================== EMPLOYEES ====================
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
        'role': normalize_role(request.form.get('role','Staff').strip()),
        'password': generate_password_hash(request.form.get('password','1234').strip()),
        'status':'approved','blocked':False
    }
    if d['full_name']:
        check = execute_query(supabase.table('employees').select('id').eq('full_name',d['full_name']))
        if not safe_data(check):
            supabase.table('employees').insert(d).execute()
            add_audit_log('add_employee', target=d['full_name'])
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
        add_audit_log('delete_employee', target=n)
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
        'role': normalize_role(request.form.get('role','Staff').strip()),
        'shift_start':request.form.get('shift_start','08:00').strip(),
        'shift_end':request.form.get('shift_end','17:00').strip(),
        'updated_at':now_eat().isoformat()
    }
    new_pw = request.form.get('password','').strip()
    if new_pw: data['password'] = generate_password_hash(new_pw)
    if data['full_name']:
        supabase.table('employees').update(data).eq('id',eid).execute()
        add_audit_log('edit_employee', target=data['full_name'])
    return redirect('/employees')

# ==================== BRANCHES ====================
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
    lat = request.form.get('latitude','')
    lng = request.form.get('longitude','')
    if n:
        supabase.table('branches').insert({
            'name':n,'shift_start':ss,'shift_end':se,
            'latitude': float(lat) if lat else None,
            'longitude': float(lng) if lng else None
        }).execute()
        add_audit_log('add_branch', target=n)
    return redirect('/branches')

@app.route('/branches/edit/<int:bid>', methods=['POST'])
@login_required
@admin_required
def edit_branch(bid):
    data = {
        'name': request.form.get('name','').strip(),
        'shift_start': request.form.get('shift_start','08:00'),
        'shift_end': request.form.get('shift_end','17:00'),
    }
    lat = request.form.get('latitude','')
    lng = request.form.get('longitude','')
    data['latitude'] = float(lat) if lat else None
    data['longitude'] = float(lng) if lng else None
    supabase.table('branches').update(data).eq('id',bid).execute()
    add_audit_log('edit_branch', target=str(bid))
    return redirect('/branches')

@app.route('/branches/delete/<int:bid>', methods=['POST'])
@login_required
@admin_required
def delete_branch(bid):
    supabase.table('branches').delete().eq('id',bid).execute()
    add_audit_log('delete_branch', target=str(bid))
    return redirect('/branches')

# ==================== CONTACTS ====================
@app.route('/contacts')
@login_required
def contacts_page():
    allowed_roles = DIRECTORATE_ROLES + ['Procurement Officer']
    if session.get('role') not in allowed_roles: return redirect('/')
    contacts = safe_data(execute_query(
        supabase.table('contacts').select('*').order('full_name')
    ))
    return render_template('contacts.html', contacts=contacts, company=COMPANY_NAME)

# ==================== CHECK IN / OUT ====================
@app.route('/check-in')
@login_required
def check_in_page():
    today = str(now_eat().date())
    role = session.get('role')
    un = session.get('user')
    ub = session.get('branch','')

    marketer_pending = False; marketer_approved = False; marketer_rejected = False
    if role == MARKETER_ROLE:
        mc = safe_data(execute_query(
            supabase.table('marketer_checkins').select('*')
            .eq('full_name', un).eq('date', today)
            .order('created_at', desc=True).limit(1)
        ))
        if mc:
            if mc[0]['status'] == 'approved': marketer_approved = True
            elif mc[0]['status'] == 'pending': marketer_pending = True
            elif mc[0]['status'] == 'rejected': marketer_rejected = True

    emp = safe_data(execute_query(
        supabase.table('employees').select('shift_start,shift_end,role,department,branch')
        .eq('full_name', un)
    ))
    emp_info = emp[0] if emp else {}
    shift_start = emp_info.get('shift_start','08:00') if role not in RIDER_DRIVER_ROLES + [MARKETER_ROLE] else None
    shift_end = emp_info.get('shift_end','17:00') if role not in RIDER_DRIVER_ROLES + [MARKETER_ROLE] else None

    my_att = safe_data(execute_query(
        supabase.table('attendance').select('*').eq('full_name', un).eq('date', today)
    ))
    current_status = 'none'; check_in_time = None; geofence = None
    if my_att:
        rec = my_att[0]
        if rec.get('check_out'): current_status = 'completed'
        elif rec.get('check_in'):
            current_status = 'checked_in'
            check_in_time = rec.get('check_in')
        geofence = rec.get('check_in_geofence')

    if role == MARKETER_ROLE:
        if marketer_approved: current_status = 'approved'
        elif marketer_pending: current_status = 'pending'
        elif marketer_rejected: current_status = 'rejected'
        else: current_status = 'none'

    journeys = []
    drivers = []
    if role in RIDER_DRIVER_ROLES or role == 'General Manager':
        if role == 'General Manager':
            drivers = safe_data(execute_query(
                supabase.table('employees').select('full_name').eq('status','approved').in_('role', ['Drivers','Riders'])
            ))
            journeys = safe_data(execute_query(
                supabase.table('journeys').select('*').eq('date', today).order('journey_number')
            ))
        else:
            journeys = safe_data(execute_query(
                supabase.table('journeys').select('*').eq('full_name', un).eq('date', today).order('journey_number')
            ))

    team_names = None
    if role in FULL_ACCESS_ROLES or role in ['HR','HR Assistant']:
        pass
    elif role == 'General Manager':
        team_names = get_manager_live_team_names()
    elif role in ['Store Manager','Operations Manager','Assistant Operations Manager']:
        team_names = [e['full_name'] for e in safe_data(execute_query(
            supabase.table('employees').select('full_name').eq('status','approved')
            .in_('role', OPERATIONS_MANAGER_TEAM)
        ))]
        if un not in team_names: team_names.append(un)
    elif role == 'Sales Manager':
        team_names = [e['full_name'] for e in safe_data(execute_query(
            supabase.table('employees').select('full_name').eq('status','approved')
            .in_('role', [MARKETER_ROLE, 'Telesales'])
        ))]
        if un not in team_names: team_names.append(un)
    elif role == 'Person in Charge':
        team_names = [e['full_name'] for e in safe_data(execute_query(
            supabase.table('employees').select('full_name').eq('status','approved')
            .eq('branch', ub)
        ))]
        if un not in team_names: team_names.append(un)
    elif role in ['Stock Controller','Assistant Stock Controller']:
        pass
    else:
        team_names = [un]

    query = supabase.table('attendance').select('*').eq('date', today)
    if team_names is not None:
        query = query.in_('full_name', team_names)
    r = safe_data(execute_query(query.order('check_in', desc=True).limit(50)))

    if r:
        names = [rec['full_name'] for rec in r]
        emp_details = safe_data(execute_query(
            supabase.table('employees').select('full_name, role, department').in_('full_name', names)
        ))
        emp_map = {e['full_name']: e for e in emp_details}
    else:
        emp_map = {}

    records = []
    for rec in r:
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
            'label': label,
            'geofence': rec.get('check_in_geofence')
        })

    return render_template('check_in.html',
        records=records, user_status=current_status, today=today, company=COMPANY_NAME,
        check_in_time=check_in_time, shift_start=shift_start, shift_end=shift_end,
        journeys=journeys, role=role, drivers=drivers, geofence=geofence)

@app.route('/check-in', methods=['POST'])
@login_required
def process_attendance():
    if session.get('role') in NO_CHECKIN_ROLES: return redirect('/')
    un = session.get('user')
    action = request.form.get('action')
    today = str(now_eat().date())
    now = now_eat().strftime('%H:%M:%S')
    lat = request.form.get('lat', '') or '0'
    lng = request.form.get('lng', '') or '0'
    loc = request.form.get('location', '') or 'Location unavailable'
    emp = safe_data(execute_query(supabase.table('employees').select('department,branch,shift_start,role').eq('full_name', un)))
    if not emp: return redirect('/check-in')
    dept = emp[0].get('department', '') or ''
    branch = emp[0].get('branch', '') or ''
    role = emp[0].get('role', '') or ''
    shift_start = emp[0].get('shift_start', '08:00') or '08:00'
    shift_start = shift_start.strip()
    if len(shift_start) > 5: shift_start = shift_start[:5]
    if not shift_start or ':' not in shift_start: shift_start = '08:00'

    if role in FIELD_ROLES:
        geofence = 'field'
    else:
        branch_rec = safe_data(execute_query(supabase.table('branches').select('latitude, longitude').eq('name', branch).limit(1)))
        branch_info = branch_rec[0] if branch_rec else {}
        geofence = geofence_status(lat, lng, branch_info)

    existing = safe_data(execute_query(supabase.table('attendance').select('*').eq('full_name', un).eq('date', today)))
    exd = existing[0] if existing else None

    if action == 'check_in':
        if role == MARKETER_ROLE: return redirect('/check-in')
        if exd and exd.get('check_in'): return redirect('/check-in')
        late_threshold = (datetime.strptime(shift_start, '%H:%M') + timedelta(minutes=LATE_GRACE_MINUTES)).strftime('%H:%M')
        status = 'late' if now[:5] > late_threshold else 'present'
        d = {'check_in': now, 'status': status, 'check_in_lat': lat, 'check_in_lng': lng, 'check_in_location': loc,
             'check_in_geofence': geofence}
        if exd: supabase.table('attendance').update(d).eq('full_name', un).eq('date', today).execute()
        else:
            d.update({'full_name': un, 'department': dept, 'branch': branch, 'date': today})
            supabase.table('attendance').insert(d).execute()
    elif action == 'check_out':
        if exd and exd.get('check_in') and not exd.get('check_out'):
            supabase.table('attendance').update({
                'check_out': now, 'status': 'checked_out',
                'check_out_lat': lat, 'check_out_lng': lng, 'check_out_location': loc,
                'check_out_geofence': geofence
            }).eq('full_name', un).eq('date', today).execute()
            return redirect('/')
    return redirect('/check-in')

# ==================== JOURNEY ROUTES ====================
@app.route('/journey/start', methods=['POST'])
@login_required
def start_journey():
    role = session.get('role')
    if role not in RIDER_DRIVER_ROLES and role != 'General Manager':
        return redirect('/check-in')
    if role == 'General Manager':
        driver_name = request.form.get('driver_name','').strip()
        if not driver_name:
            return redirect('/check-in')
        un = driver_name
    else:
        un = session.get('user')
    today = str(now_eat().date())
    now = now_eat().strftime('%H:%M:%S')
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
    if session.get('role') not in RIDER_DRIVER_ROLES and session.get('role') != 'General Manager':
        return redirect('/check-in')
    now = now_eat().strftime('%H:%M:%S')
    lat = request.form.get('lat',''); lng = request.form.get('lng',''); loc = request.form.get('location','')
    supabase.table('journeys').update({
        'end_time': now, 'end_lat': lat, 'end_lng': lng, 'end_location': loc, 'status': 'completed'
    }).eq('id', jid).execute()
    return redirect('/check-in')

# ==================== ATTENDANCE HISTORY ====================
@app.route('/attendance-history')
@login_required
def attendance_history():
    role = session.get('role'); un = session.get('user'); ub = session.get('branch','')
    period = request.args.get('period','month')
    fd = request.args.get('from_date',''); td = request.args.get('to_date','')
    page = int(request.args.get('page',1))
    per_page = 50
    offset = (page-1)*per_page
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

    base_query = supabase.table('attendance').select('*').gte('date',sd).lte('date',ed)
    if role in FULL_ACCESS_ROLES or role in ['HR','HR Assistant']:
        query = base_query
    elif role == 'General Manager':
        team_names = get_manager_attendance_team_names()
        query = base_query.in_('full_name', team_names)
    elif role in ['Store Manager','Operations Manager','Assistant Operations Manager']:
        team_names = [e['full_name'] for e in safe_data(execute_query(supabase.table('employees').select('full_name').eq('status','approved').in_('role',OPERATIONS_MANAGER_TEAM)))]
        query = base_query.in_('full_name', team_names)
    elif role == 'Sales Manager':
        team_names = [e['full_name'] for e in safe_data(execute_query(supabase.table('employees').select('full_name').eq('status','approved').in_('role',[MARKETER_ROLE,'Telesales'])))]
        team_names.append(un)
        query = base_query.in_('full_name', team_names)
    elif role == 'Person in Charge':
        team_names = [e['full_name'] for e in safe_data(execute_query(supabase.table('employees').select('full_name').eq('status','approved').eq('branch',ub)))]
        query = base_query.in_('full_name', team_names)
    elif role in ['Stock Controller','Assistant Stock Controller']:
        query = base_query
    else:
        query = base_query.eq('full_name', un)
    r = safe_data(execute_query(query.order('date',desc=True).limit(per_page).offset(offset)))

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
    has_next = len(records) == per_page
    return render_template('attendance_history.html', records=records, period=period,
                         from_date=sd, to_date=ed, today=str(today), page=page, has_next=has_next, company=COMPANY_NAME)

# ==================== SALES ====================
@app.route('/sales', methods=['GET','POST'])
@login_required
def sales_page():
    role = session.get('role', '').strip()
    if role == 'General Manager':
        return redirect('/')
    if role.lower() == 'staff': role = session['role'] = 'Staff'
    elif role.lower() == 'person in charge': role = session['role'] = 'Person in Charge'

    un = session.get('user'); ub = session.get('branch','')
    today = str(now_eat().date())

    if request.method == 'POST':
        sales_type = request.form.get('sales_type','individual')
        sale_date = request.form.get('sale_date', today).strip()
        if not sale_date: sale_date = today
        if sale_date > today: sale_date = today

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

        force = request.form.get('force','0')

        if force != '1':
            if sales_type == 'individual' and role in SALES_SUBMIT_ROLES:
                existing = safe_data(execute_query(
                    supabase.table('sales').select('*').eq('full_name', un).eq('date', sale_date).limit(1)
                ))
                if existing:
                    return render_template('sales_confirm.html',
                        existing_sales=existing,
                        form_data={
                            'sales_type':'individual','sale_date':sale_date,
                            'mpesa_sales':mpesa,'cash_sales':cash,'notes':notes,
                            'expenses':expenses, 'total':total
                        },
                        company=COMPANY_NAME)
            elif sales_type == 'branch' and role == 'Person in Charge':
                existing = safe_data(execute_query(
                    supabase.table('branch_sales').select('*').eq('branch', ub).eq('date', sale_date).limit(1)
                ))
                if existing:
                    return render_template('sales_confirm.html',
                        existing_sales=existing,
                        form_data={
                            'sales_type':'branch','sale_date':sale_date,
                            'mpesa_sales':mpesa,'cash_sales':cash,'notes':notes,
                            'expenses':expenses, 'total':total
                        },
                        company=COMPANY_NAME)

        if sales_type == 'individual' and role in SALES_SUBMIT_ROLES:
            try:
                emp = safe_data(execute_query(
                    supabase.table('employees').select('department,branch').eq('full_name', un)
                ))
                if emp and total > 0:
                    supabase.table('sales').insert({
                        'full_name': un, 'department': emp[0].get('department',''),
                        'branch': emp[0].get('branch',''), 'date': sale_date,
                        'mpesa_sales': mpesa, 'cash_sales': cash, 'total_sales': total,
                        'sales_type': 'individual', 'notes': notes, 'expenses': expenses
                    }).execute()
                    add_audit_log('submit_individual_sale', target=un, details={'date':sale_date, 'total':total})
            except Exception as e: print(f"Individual sale error: {e}")
        elif sales_type == 'branch' and role == 'Person in Charge':
            try:
                if total > 0:
                    supabase.table('branch_sales').insert({
                        'branch': ub, 'date': sale_date,
                        'mpesa_sales': mpesa, 'cash_sales': cash, 'total_sales': total,
                        'submitted_by': un, 'notes': notes, 'expenses': expenses
                    }).execute()
                    add_audit_log('submit_branch_sale', target=ub, details={'date':sale_date, 'total':total})
            except Exception as e: print(f"Branch sale error: {e}")
        return redirect('/sales?success=1')

    view_type = request.args.get('view_type','individual')
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
        filter_from = str(today_date.replace(day=1))
        filter_to = str(today_date)
    if not filter_to:
        filter_to = str(today_date)

    if role == 'Staff':
        query = supabase.table('sales').select('*').eq('full_name', un)
        query = query.gte('date', filter_from).lte('date', filter_to).order('date', desc=True)
        individual_sales = safe_data(execute_query(query))
        branch_sales = []
        employees = []
        branches_for_filter = []
        filter_branch = ''
        filter_employee = ''
        total_individual = sum(float(s['total_sales']) for s in individual_sales)
        total_branch = 0
    elif role == 'Person in Charge':
        filter_branch = ub
        filter_employee = request.args.get('employee','')
        ind_query = supabase.table('sales').select('*').eq('branch', ub)
        if filter_employee:
            ind_query = ind_query.eq('full_name', filter_employee)
        ind_query = ind_query.gte('date', filter_from).lte('date', filter_to).order('date', desc=True)
        individual_sales = safe_data(execute_query(ind_query))
        br_query = supabase.table('branch_sales').select('*').eq('branch', ub)
        br_query = br_query.gte('date', filter_from).lte('date', filter_to).order('date', desc=True)
        branch_sales = safe_data(execute_query(br_query))
        employees = safe_data(execute_query(
            supabase.table('employees').select('full_name').eq('status','approved').eq('branch', ub).order('full_name')
        ))
        branches_for_filter = [ub]
        total_individual = sum(float(s['total_sales']) for s in individual_sales)
        total_branch = sum(float(s['total_sales']) for s in branch_sales)
    else:
        allowed_branches = get_branch_names()
        filter_branch = request.args.get('branch','')
        filter_employee = request.args.get('employee','')
        ind_query = supabase.table('sales').select('*')
        if filter_branch and filter_branch in allowed_branches:
            ind_query = ind_query.eq('branch', filter_branch)
        if filter_employee:
            ind_query = ind_query.eq('full_name', filter_employee)
        ind_query = ind_query.gte('date', filter_from).lte('date', filter_to).order('date', desc=True)
        individual_sales = safe_data(execute_query(ind_query))
        br_query = supabase.table('branch_sales').select('*')
        if filter_branch and filter_branch in allowed_branches:
            br_query = br_query.eq('branch', filter_branch)
        if filter_employee:
            br_query = br_query.eq('submitted_by', filter_employee)
        br_query = br_query.gte('date', filter_from).lte('date', filter_to).order('date', desc=True)
        branch_sales = safe_data(execute_query(br_query))
        if filter_branch:
            employees = safe_data(execute_query(
                supabase.table('employees').select('full_name').eq('status','approved').eq('branch', filter_branch).order('full_name')
            ))
        else:
            employees = safe_data(execute_query(
                supabase.table('employees').select('full_name').eq('status','approved').order('full_name')
            ))
        branches_for_filter = allowed_branches
        total_individual = sum(float(s['total_sales']) for s in individual_sales)
        total_branch = sum(float(s['total_sales']) for s in branch_sales)

    target_progress = None
    month_str = now_eat().date().replace(day=1).strftime('%Y-%m')
    target = safe_data(execute_query(supabase.table('sales_targets').select('target_amount').eq('full_name',un).eq('month',month_str).limit(1)))
    if target:
        target_amt = float(target[0]['target_amount'])
        month_start = datetime.strptime(month_str + '-01', '%Y-%m-%d').date()
        my_sales = safe_data(execute_query(supabase.table('sales').select('total_sales').eq('full_name',un).gte('date',str(month_start)).lte('date',today)))
        month_total = sum(float(s['total_sales']) for s in my_sales)
        remaining = max(0, target_amt - month_total)
        target_progress = {'target': target_amt, 'current': month_total, 'remaining': remaining,
                           'percent': round((month_total / target_amt * 100), 1) if target_amt > 0 else 0,
                           'achieved': month_total >= target_amt}

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
        employees=employees,
        target_progress=target_progress,
        today=today,
        company=COMPANY_NAME,
        success_msg=request.args.get('success',''),
        total_individual=total_individual,
        total_branch=total_branch)

# ==================== PROFILE ====================
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
                else: sm = 'Current password is incorrect.'
    emp = safe_data(execute_query(supabase.table('employees').select('*').eq('full_name',un)))
    ed = emp[0] if emp else {}
    today = now_eat().date(); ms = today.replace(day=1)
    dp = len(set(a['date'] for a in safe_data(execute_query(supabase.table('attendance').select('date,check_in').eq('full_name',un).gte('date',str(ms)).lte('date',str(today)))) if a.get('check_in')))
    tms = sum(float(s.get('total_sales',0)) for s in safe_data(execute_query(supabase.table('sales').select('total_sales').eq('full_name',un).gte('date',str(ms)).lte('date',str(today)))))
    last_att = safe_data(execute_query(supabase.table('attendance').select('check_in_location, check_in_geofence').eq('full_name', un).order('date', desc=True).order('check_in', desc=True).limit(1)))
    last_loc = last_att[0] if last_att else {}
    return render_template('profile.html', employee=ed, days_present=dp, total_my_sales=tms, success_msg=sm,
                           last_check_in_location=last_loc.get('check_in_location'),
                           last_check_in_geofence=last_loc.get('check_in_geofence'), company=COMPANY_NAME)

# ==================== REPORTS ====================
@app.route('/reports')
@login_required
def reports():
    if not (session.get('role') in FULL_ACCESS_ROLES + ['Stock Controller','Assistant Stock Controller','Accountant','Accountant Assistant']):
        return redirect('/')
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
    return render_template('reports.html',records=records,sales_recs=srecs,branch_recs=brecs,from_date=fd,to_date=td,report_type=rt,
                         total_sales_amount=sum(float(s.get('total_sales',0)) for s in srecs),
                         total_branch_amount=sum(float(s.get('total_sales',0)) for s in brecs),
                         company=COMPANY_NAME)

# ==================== SALES REPORT ====================
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

# ==================== EXPORT ATTENDANCE ====================
@app.route('/export-attendance')
@login_required
def export_attendance():
    if session.get('role') not in FULL_ACCESS_ROLES + ['HR','HR Assistant','Stock Controller','Assistant Stock Controller','Accountant','Accountant Assistant']:
        return redirect('/')
    from_date = request.args.get('from_date', str(now_eat().date().replace(day=1)))
    to_date   = request.args.get('to_date', str(now_eat().date()))
    records = safe_data(execute_query(
        supabase.table('attendance').select('*').gte('date', from_date).lte('date', to_date).order('date',desc=True).limit(2000)
    ))
    si = io.StringIO()
    cw = csv.writer(si)
    cw.writerow(['Date','Employee','Department','Branch','Check In','Check Out','Status','Check In Location','Geofence'])
    for r in records:
        cw.writerow([r['date'], r['full_name'], r.get('department',''), r.get('branch',''),
                     r.get('check_in',''), r.get('check_out',''), r.get('status','present'),
                     r.get('check_in_location',''), r.get('check_in_geofence','')])
    output = si.getvalue(); si.close()
    return Response(output, mimetype='text/csv',
                    headers={"Content-Disposition": "attachment;filename=attendance_report.csv"})

# ==================== EXPORT SALES ====================
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

# ==================== ATTENDANCE SUMMARY ====================
@app.route('/attendance-summary')
@login_required
def attendance_summary():
    if session.get('role') not in FULL_ACCESS_ROLES + ['HR','HR Assistant']:
        return redirect('/')
    from_date = request.args.get('from_date', str(now_eat().date().replace(day=1)))
    to_date = request.args.get('to_date', str(now_eat().date()))
    branch_filter = request.args.get('branch', '')
    employee_filter = request.args.get('employee', '')

    if branch_filter:
        emp_query = supabase.table('employees').select('full_name, branch, department, role').eq('status','approved').eq('branch', branch_filter)
        if employee_filter: emp_query = emp_query.eq('full_name', employee_filter)
        employees = safe_data(execute_query(emp_query.order('full_name').limit(10000)))
        emp_names = [e['full_name'] for e in employees]
        emp_set = set(emp_names)
        att_data = safe_data(execute_query(
            supabase.table('attendance')
                   .select('full_name, date')
                   .gte('date', from_date).lte('date', to_date)
                   .in_('full_name', emp_names)
                   .not_.is_('check_in', 'null')
                   .limit(50000)
        ))
        emp_days = defaultdict(set)
        for a in att_data:
            if a['full_name'] in emp_set:
                emp_days[a['full_name']].add(a['date'])
        summary = []
        for e in employees:
            days_present = len(emp_days.get(e['full_name'], set()))
            summary.append({**e, 'days_present': days_present})
    else:
        all_employees = []
        emp_days = defaultdict(set)
        for branch in get_branch_names():
            emp_query = supabase.table('employees').select('full_name, branch, department, role').eq('status','approved').eq('branch', branch)
            if employee_filter: emp_query = emp_query.eq('full_name', employee_filter)
            employees = safe_data(execute_query(emp_query.order('full_name').limit(10000)))
            if not employees:
                continue
            all_employees.extend(employees)
            emp_names = [e['full_name'] for e in employees]
            att_data = safe_data(execute_query(
                supabase.table('attendance')
                       .select('full_name, date')
                       .gte('date', from_date).lte('date', to_date)
                       .in_('full_name', emp_names)
                       .not_.is_('check_in', 'null')
                       .limit(50000)
            ))
            for a in att_data:
                emp_days[a['full_name']].add(a['date'])
        summary = []
        for e in all_employees:
            days_present = len(emp_days.get(e['full_name'], set()))
            summary.append({**e, 'days_present': days_present})

    branches = get_branch_names()
    all_employees_for_filter = safe_data(execute_query(
        supabase.table('employees').select('full_name').eq('status','approved').order('full_name').limit(10000)
    ))
    return render_template('attendance_summary.html', summary=summary, from_date=from_date, to_date=to_date,
                           branch_filter=branch_filter, employee_filter=employee_filter,
                           branches=branches, all_employees=all_employees_for_filter, company=COMPANY_NAME)

@app.route('/export-attendance-summary')
@login_required
def export_attendance_summary():
    if session.get('role') not in FULL_ACCESS_ROLES + ['HR','HR Assistant']:
        return redirect('/')
    from_date = request.args.get('from_date', str(now_eat().date().replace(day=1)))
    to_date = request.args.get('to_date', str(now_eat().date()))
    branch_filter = request.args.get('branch', '')
    employee_filter = request.args.get('employee', '')

    if branch_filter:
        emp_query = supabase.table('employees').select('full_name, branch, department, role').eq('status','approved').eq('branch', branch_filter)
        if employee_filter: emp_query = emp_query.eq('full_name', employee_filter)
        employees = safe_data(execute_query(emp_query.order('full_name').limit(10000)))
        emp_names = [e['full_name'] for e in employees]
        emp_set = set(emp_names)
        att_data = safe_data(execute_query(
            supabase.table('attendance')
                   .select('full_name, date')
                   .gte('date', from_date).lte('date', to_date)
                   .in_('full_name', emp_names)
                   .not_.is_('check_in', 'null')
                   .limit(50000)
        ))
        emp_days = defaultdict(set)
        for a in att_data:
            if a['full_name'] in emp_set:
                emp_days[a['full_name']].add(a['date'])
        summary = []
        for e in employees:
            days_present = len(emp_days.get(e['full_name'], set()))
            summary.append({**e, 'days_present': days_present})
    else:
        all_employees = []
        emp_days = defaultdict(set)
        for branch in get_branch_names():
            emp_query = supabase.table('employees').select('full_name, branch, department, role').eq('status','approved').eq('branch', branch)
            if employee_filter: emp_query = emp_query.eq('full_name', employee_filter)
            employees = safe_data(execute_query(emp_query.order('full_name').limit(10000)))
            if not employees:
                continue
            all_employees.extend(employees)
            emp_names = [e['full_name'] for e in employees]
            att_data = safe_data(execute_query(
                supabase.table('attendance')
                       .select('full_name, date')
                       .gte('date', from_date).lte('date', to_date)
                       .in_('full_name', emp_names)
                       .not_.is_('check_in', 'null')
                       .limit(50000)
            ))
            for a in att_data:
                emp_days[a['full_name']].add(a['date'])
        summary = []
        for e in all_employees:
            days_present = len(emp_days.get(e['full_name'], set()))
            summary.append({**e, 'days_present': days_present})

    si = io.StringIO()
    cw = csv.writer(si)
    cw.writerow(['Employee','Department','Branch','Role','Days Present'])
    for s in summary:
        cw.writerow([s['full_name'], s['department'], s['branch'], s['role'], s['days_present']])
    output = si.getvalue(); si.close()
    return Response(output, mimetype='text/csv',
                    headers={"Content-Disposition": "attachment;filename=attendance_summary.csv"})

# ==================== SHIFT CHANGE ====================
@app.route('/shift-change', methods=['GET','POST'])
@login_required
def shift_change_page():
    user_role = session.get('role')
    un = session.get('user')
    ub = session.get('branch','')
    if user_role not in ['Person in Charge','Stock Controller','Assistant Stock Controller','admin','ceo']:
        return redirect('/')

    if request.method == 'POST' and user_role == 'Person in Charge':
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
        add_audit_log('submit_shift_change', target=employee_name)
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

    employees = get_branch_employees(ub) if user_role == 'Person in Charge' else []
    return render_template('shift_change.html', requests=requests_data, employees=employees,
                           success=request.args.get('success',''), company=COMPANY_NAME)

@app.route('/shift-change/approve/<int:rid>', methods=['POST'])
@login_required
def approve_shift_change(rid):
    if session.get('role') not in ['Stock Controller','Assistant Stock Controller','admin','ceo']: return redirect('/')
    req_data = safe_data(execute_query(supabase.table('shift_change_requests').select('*').eq('id', rid).limit(1)))
    if not req_data or req_data[0]['status'] != 'pending': return redirect('/shift-change')
    rec = req_data[0]
    supabase.table('employees').update({
        'shift_start': rec['new_shift_start'], 'shift_end': rec['new_shift_end']
    }).eq('full_name', rec['employee_full_name']).execute()
    supabase.table('shift_change_requests').update({'status':'approved'}).eq('id', rid).execute()
    add_audit_log('approve_shift_change', target=rec['employee_full_name'])
    return redirect('/shift-change')

@app.route('/shift-change/reject/<int:rid>', methods=['POST'])
@login_required
def reject_shift_change(rid):
    if session.get('role') not in ['Stock Controller','Assistant Stock Controller','admin','ceo']: return redirect('/')
    supabase.table('shift_change_requests').update({'status':'rejected'}).eq('id', rid).execute()
    add_audit_log('reject_shift_change', target=str(rid))
    return redirect('/shift-change')

# ==================== LEAVES ====================
# (unchanged leaves routes, omitted for brevity – keep as in previous full code)

# ==================== MARKETER ROUTES ====================
# (unchanged marketer routes, keep as in previous full code)

# ==================== MARKETER DASHBOARD ====================
# (unchanged)

# ==================== SALES MANAGER DASHBOARD ====================
# (already includes General Manager access as modified earlier)

# ==================== TARGETS ====================
@app.route('/targets', methods=['GET','POST'])
@login_required
def targets_page():
    if session.get('role') not in TARGET_SETTER_ROLES: return redirect('/')
    user_role = session.get('role')

    # Fetch all approved employees for individual targets (no role filter)
    employees = safe_data(execute_query(
        supabase.table('employees').select('full_name').eq('status','approved').order('full_name')
    ))
    branches = get_branch_names()

    # Fetch existing individual targets
    individual_targets = safe_data(execute_query(
        supabase.table('sales_targets').select('*').order('month', desc=True).order('full_name').limit(200)
    ))
    # Fetch existing branch targets (assuming table name 'branch_targets')
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
            # Upsert into branch_targets (assuming table exists)
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

# ==================== TARGET PROGRESS ====================
# (unchanged)

# ==================== PROCUREMENT DELEGATION ====================
# (unchanged)

# ==================== HR ANNUAL LEAVE ====================
# (unchanged)

# ==================== HR LEAVES ====================
# (unchanged)

# ==================== HR ATTENDANCE REPORT ====================
# (unchanged)

# ==================== MARKETER REPORTS ====================
# (unchanged)

# ==================== ABSENT TODAY ====================
# (unchanged)

# ==================== DELETE LEAVE (ADMIN/HR) ====================
# (unchanged)

# ==================== ADMIN RESET ATTENDANCE ====================
# (unchanged)

# ==================== ERROR HANDLER ====================
@app.errorhandler(Exception)
def handle_exception(e):
    print(f"Unhandled error: {e}")
    return render_template('error.html', error=str(e)), 500

if __name__=='__main__':
    app.run(host='0.0.0.0',port=5000)
