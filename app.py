from flask import Flask, render_template, request, redirect, url_for, session
from datetime import date, datetime, timedelta
from supabase import create_client
from functools import wraps

app = Flask(__name__)
app.secret_key = 'attendance-secret-2024'

SUPABASE_URL = 'https://lznqrkujlrcxcxizygzq.supabase.co'
SUPABASE_KEY = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Imx6bnFya3VqbHJjeGN4aXp5Z3pxIiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODQ1NjIwNjUsImV4cCI6MjEwMDEzODA2NX0.Jj_EW42NVMQk6zbEcNoY-IlrSe0tgW4zFiKoBSapiDA'

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

DEPARTMENTS = [
    'Staff', 'Branch Manager', 'Assistant Branch Manager',
    'Stock Controller', 'Stock Assistant', 'HR', 'HR Assistant',
    'Accountant', 'Accountant Assistant', 'Procurement',
    'Store Manager', 'Store Assistant', 'Store Person',
    'Telesales', 'Dispatch', 'Operations Manager', 'Operations Assistant',
    'Sales Manager', 'Cashier', 'IT', 'CEO'
]

ROLES = ['staff', 'manager', 'admin', 'ceo']

STATUS_LABELS = {'present': 'Present', 'late': 'Arrived Late', 'absent': 'Absent', 'half-day': 'Half Day', 'excused': 'Excused'}
STATUS_CLASSES = {'present': 'badge-success', 'late': 'badge-warning', 'absent': 'badge-danger', 'half-day': 'badge-info', 'excused': 'badge-secondary'}


def get_branches():
    r = supabase.table('branches').select('*').order('name').execute()
    return [b['name'] for b in r.data] if r.data else []


# ─── LOGIN ───────────────────────────────────────────────
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        name = request.form.get('full_name', '').strip()
        password = request.form.get('password', '').strip()
        r = supabase.table('employees').select('*').eq('full_name', name).execute()
        if r.data and r.data[0].get('password', '1234') == password:
            session['user'] = name
            session['role'] = r.data[0].get('role', 'staff')
            session['department'] = r.data[0].get('department', '')
            session['branch'] = r.data[0].get('branch', '')
            return redirect(url_for('home'))
        return render_template('login.html', error='Invalid name or password')
    return render_template('login.html')


@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated


# ─── DASHBOARD ───────────────────────────────────────────
@app.route('/')
@login_required
def home():
    today = str(date.today())
    role = session.get('role', 'staff')
    user_branch = session.get('branch', '')
    user_name = session.get('user', '')

    # Attendance stats
    if role in ['admin', 'ceo']:
        emp_r = supabase.table('employees').select('*').execute()
        att_r = supabase.table('attendance').select('*').eq('date', today).execute()
    elif role == 'manager':
        emp_r = supabase.table('employees').select('*').eq('branch', user_branch).execute()
        att_r = supabase.table('attendance').select('*').eq('date', today).eq('branch', user_branch).execute()
    else:
        emp_r = supabase.table('employees').select('*').eq('full_name', user_name).execute()
        att_r = supabase.table('attendance').select('*').eq('date', today).eq('full_name', user_name).execute()

    total_employees = len(emp_r.data)
    today_count = len(att_r.data)

    # Today's records
    today_records = []
    for rec in att_r.data:
        status = rec.get('status', 'present')
        today_records.append({
            'full_name': rec['full_name'], 'department': rec.get('department', '—'),
            'branch': rec.get('branch', '—'),
            'check_in': rec.get('check_in', '—'), 'check_out': rec.get('check_out', '—'),
            'status': status, 'status_label': STATUS_LABELS.get(status, status),
            'status_class': STATUS_CLASSES.get(status, ''),
            'check_in_location': rec.get('check_in_location', '—')
        })

    # Sales today
    if role in ['admin', 'ceo']:
        sales_r = supabase.table('sales').select('*').eq('date', today).execute()
        branch_sales_r = supabase.table('branch_sales').select('*').eq('date', today).execute()
    elif role == 'manager':
        sales_r = supabase.table('sales').select('*').eq('date', today).eq('branch', user_branch).execute()
        branch_sales_r = supabase.table('branch_sales').select('*').eq('date', today).eq('branch', user_branch).execute()
    else:
        sales_r = supabase.table('sales').select('*').eq('date', today).eq('full_name', user_name).execute()
        branch_sales_r = {'data': []}

    total_sales = sum(s['amount'] for s in sales_r.data) if sales_r.data else 0
    branch_total = sum(s['total_amount'] for s in branch_sales_r.data) if branch_sales_r.data else 0

    # Check if user checked in today
    user_checked_in = False
    user_checked_out = False
    if role not in ['admin', 'ceo']:
        my_att = supabase.table('attendance').select('*').eq('full_name', user_name).eq('date', today).execute()
        if my_att.data:
            user_checked_in = bool(my_att.data[0].get('check_in'))
            user_checked_out = bool(my_att.data[0].get('check_out'))

    return render_template('index.html', total_employees=total_employees, today_count=today_count,
                           today_records=today_records, total_sales=total_sales, branch_total=branch_total,
                           user_checked_in=user_checked_in, user_checked_out=user_checked_out)


# ─── EMPLOYEES ───────────────────────────────────────────
@app.route('/employees')
@login_required
def employees_page():
    if session.get('role') not in ['admin', 'ceo']:
        return redirect(url_for('home'))
    branches = get_branches()
    dept_filter = request.args.get('department', '')
    if dept_filter:
        r = supabase.table('employees').select('*').eq('department', dept_filter).order('full_name').execute()
    else:
        r = supabase.table('employees').select('*').order('full_name').execute()
    return render_template('employees.html', employees=r.data, branches=branches,
                           departments=DEPARTMENTS, roles=ROLES, current_department=dept_filter)


@app.route('/employees/add', methods=['POST'])
@login_required
def add_employee():
    if session.get('role') not in ['admin', 'ceo']:
        return redirect(url_for('home'))
    full_name = request.form.get('full_name', '').strip()
    department = request.form.get('department', '').strip()
    branch = request.form.get('branch', '').strip()
    role = request.form.get('role', 'staff').strip()
    password = request.form.get('password', '1234').strip()

    check = supabase.table('employees').select('*').eq('full_name', full_name).execute()
    if check.data:
        all_emp = supabase.table('employees').select('*').order('full_name').execute()
        return render_template('employees.html', employees=all_emp.data, branches=get_branches(),
                               departments=DEPARTMENTS, roles=ROLES,
                               message='Employee with this name already exists!', message_type='error')

    supabase.table('employees').insert({
        'full_name': full_name, 'department': department, 'branch': branch, 'role': role, 'password': password
    }).execute()
    return redirect(url_for('employees_page'))


@app.route('/employees/edit/<int:emp_id>', methods=['POST'])
@login_required
def edit_employee(emp_id):
    if session.get('role') not in ['admin', 'ceo']:
        return redirect(url_for('home'))
    supabase.table('employees').update({
        'full_name': request.form.get('full_name', '').strip(),
        'department': request.form.get('department', '').strip(),
        'branch': request.form.get('branch', '').strip(),
        'role': request.form.get('role', 'staff').strip(),
        'password': request.form.get('password', '1234').strip(),
        'updated_at': datetime.now().isoformat()
    }).eq('id', emp_id).execute()
    return redirect(url_for('employees_page'))


@app.route('/employees/delete/<int:emp_id>', methods=['POST'])
@login_required
def delete_employee(emp_id):
    if session.get('role') not in ['admin', 'ceo']:
        return redirect(url_for('home'))
    supabase.table('employees').delete().eq('id', emp_id).execute()
    return redirect(url_for('employees_page'))


# ─── BRANCHES ────────────────────────────────────────────
@app.route('/branches')
@login_required
def branches_page():
    if session.get('role') not in ['admin', 'ceo']:
        return redirect(url_for('home'))
    r = supabase.table('branches').select('*').order('name').execute()
    return render_template('branches.html', branches=r.data if r.data else [])


@app.route('/branches/add', methods=['POST'])
@login_required
def add_branch():
    name = request.form.get('name', '').strip()
    if name:
        existing = supabase.table('branches').select('*').eq('name', name).execute()
        if not existing.data:
            supabase.table('branches').insert({'name': name}).execute()
    return redirect(url_for('branches_page'))


@app.route('/branches/delete/<int:branch_id>', methods=['POST'])
@login_required
def delete_branch(branch_id):
    supabase.table('branches').delete().eq('id', branch_id).execute()
    return redirect(url_for('branches_page'))


# ─── CHECK IN / OUT ──────────────────────────────────────
@app.route('/check-in')
@login_required
def check_in_page():
    today = str(date.today())
    role = session.get('role')
    user_branch = session.get('branch', '')
    if role in ['admin', 'ceo']:
        r = supabase.table('attendance').select('*').eq('date', today).order('check_in', desc=True).execute()
    elif role == 'manager':
        r = supabase.table('attendance').select('*').eq('date', today).eq('branch', user_branch).order('check_in', desc=True).execute()
    else:
        r = supabase.table('attendance').select('*').eq('date', today).eq('full_name', session.get('user')).execute()
    today_records = build_records(r.data)
    return render_template('check_in.html', today_records=today_records)


@app.route('/check-in', methods=['POST'])
@login_required
def process_attendance():
    if session.get('role') in ['admin', 'ceo']:
        return redirect(url_for('home'))
    full_name = session.get('user')
    action = request.form.get('action')
    lat = request.form.get('lat', '')
    lng = request.form.get('lng', '')
    location = request.form.get('location', '')
    today = str(date.today())
    now = datetime.now().strftime('%H:%M:%S')

    emp = supabase.table('employees').select('*').eq('full_name', full_name).execute()
    department = emp.data[0].get('department', '') if emp.data else ''
    branch = emp.data[0].get('branch', '') if emp.data else ''

    if action == 'check_in':
        existing = supabase.table('attendance').select('*').eq('full_name', full_name).eq('date', today).execute()
        if existing.data and existing.data[0].get('check_in'):
            return redirect(url_for('check_in_page'))
        status = 'late' if now > '09:00:00' else 'present'
        data = {'check_in': now, 'status': status, 'check_in_lat': lat, 'check_in_lng': lng, 'check_in_location': location}
        if existing.data:
            supabase.table('attendance').update(data).eq('full_name', full_name).eq('date', today).execute()
        else:
            data.update({'full_name': full_name, 'department': department, 'branch': branch, 'date': today})
            supabase.table('attendance').insert(data).execute()

    elif action == 'check_out':
        existing = supabase.table('attendance').select('*').eq('full_name', full_name).eq('date', today).execute()
        if existing.data and existing.data[0].get('check_in') and not existing.data[0].get('check_out'):
            supabase.table('attendance').update({
                'check_out': now, 'check_out_lat': lat, 'check_out_lng': lng, 'check_out_location': location
            }).eq('full_name', full_name).eq('date', today).execute()

    return redirect(url_for('check_in_page'))


def build_records(records):
    result = []
    for rec in records:
        status = rec.get('status', 'present')
        result.append({
            'full_name': rec['full_name'], 'department': rec.get('department', '—'),
            'branch': rec.get('branch', '—'),
            'check_in': rec.get('check_in', '—'), 'check_out': rec.get('check_out', '—'),
            'status': status, 'status_label': STATUS_LABELS.get(status, status),
            'status_class': STATUS_CLASSES.get(status, ''),
            'check_in_location': rec.get('check_in_location', '—')
        })
    return result


# ─── ATTENDANCE HISTORY ──────────────────────────────────
@app.route('/attendance-history')
@login_required
def attendance_history():
    role = session.get('role')
    user_name = session.get('user')
    user_branch = session.get('branch', '')
    period = request.args.get('period', 'week')

    today = date.today()
    if period == 'week':
        start = today - timedelta(days=7)
    elif period == 'month':
        start = today - timedelta(days=30)
    elif period == 'last_month':
        start = today.replace(day=1) - timedelta(days=1)
        start = start.replace(day=1)
        today = start.replace(day=28) + timedelta(days=4)
        today = today - timedelta(days=today.day)
    else:
        start = today - timedelta(days=30)

    if role in ['admin', 'ceo']:
        r = supabase.table('attendance').select('*').gte('date', str(start)).lte('date', str(today)).order('date', desc=True).execute()
    elif role == 'manager':
        r = supabase.table('attendance').select('*').gte('date', str(start)).lte('date', str(today)).eq('branch', user_branch).order('date', desc=True).execute()
    else:
        r = supabase.table('attendance').select('*').gte('date', str(start)).lte('date', str(today)).eq('full_name', user_name).order('date', desc=True).execute()

    records = build_records(r.data)
    return render_template('attendance_history.html', records=records, period=period)


# ─── SALES ───────────────────────────────────────────────
@app.route('/sales', methods=['GET', 'POST'])
@login_required
def sales_page():
    role = session.get('role')
    user_name = session.get('user')
    user_branch = session.get('branch', '')
    today = str(date.today())

    if request.method == 'POST':
        amount = request.form.get('amount', '0')
        sales_type = request.form.get('sales_type', 'individual')
        notes = request.form.get('notes', '')
        emp = supabase.table('employees').select('*').eq('full_name', user_name).execute()
        dept = emp.data[0].get('department', '') if emp.data else ''
        branch = emp.data[0].get('branch', '') if emp.data else ''

        try:
            amt = float(amount)
            supabase.table('sales').insert({
                'full_name': user_name, 'department': dept, 'branch': branch,
                'date': today, 'amount': amt, 'sales_type': sales_type, 'notes': notes
            }).execute()

            # If manager submitting branch total
            if sales_type == 'branch_total' and role == 'manager':
                supabase.table('branch_sales').insert({
                    'branch': branch, 'date': today, 'total_amount': amt, 'submitted_by': user_name
                }).execute()
        except:
            pass
        return redirect(url_for('sales_page'))

    # Get sales records
    if role in ['admin', 'ceo']:
        sales_r = supabase.table('sales').select('*').eq('date', today).order('created_at', desc=True).execute()
        branch_r = supabase.table('branch_sales').select('*').eq('date', today).execute()
    elif role == 'manager':
        sales_r = supabase.table('sales').select('*').eq('date', today).eq('branch', user_branch).order('created_at', desc=True).execute()
        branch_r = supabase.table('branch_sales').select('*').eq('date', today).eq('branch', user_branch).execute()
    else:
        sales_r = supabase.table('sales').select('*').eq('date', today).eq('full_name', user_name).order('created_at', desc=True).execute()
        branch_r = {'data': []}

    # Sales history
    week_ago = str(date.today() - timedelta(days=7))
    if role in ['admin', 'ceo']:
        history_r = supabase.table('sales').select('*').gte('date', week_ago).lte('date', today).order('date', desc=True).execute()
    elif role == 'manager':
        history_r = supabase.table('sales').select('*').gte('date', week_ago).lte('date', today).eq('branch', user_branch).order('date', desc=True).execute()
    else:
        history_r = supabase.table('sales').select('*').gte('date', week_ago).lte('date', today).eq('full_name', user_name).order('date', desc=True).execute()

    # Branch totals
    branch_totals = {}
    for s in sales_r.data:
        br = s.get('branch', 'Unknown')
        branch_totals[br] = branch_totals.get(br, 0) + s['amount']

    return render_template('sales.html',
                           sales=sales_r.data, branch_sales=branch_r.data,
                           history=history_r.data, branch_totals=branch_totals,
                           today=today, role=role)


@app.route('/reports')
@login_required
def reports():
    if session.get('role') not in ['admin', 'ceo', 'manager']:
        return redirect(url_for('home'))
    role = session.get('role')
    user_branch = session.get('branch', '')
    from_date = request.args.get('from_date', str(date.today()))
    to_date = request.args.get('to_date', str(date.today()))

    # Attendance
    if role in ['admin', 'ceo']:
        att_r = supabase.table('attendance').select('*').gte('date', from_date).lte('date', to_date).order('date', desc=True).execute()
        sales_r = supabase.table('sales').select('*').gte('date', from_date).lte('date', to_date).order('date', desc=True).execute()
    else:
        att_r = supabase.table('attendance').select('*').gte('date', from_date).lte('date', to_date).eq('branch', user_branch).order('date', desc=True).execute()
        sales_r = supabase.table('sales').select('*').gte('date', from_date).lte('date', to_date).eq('branch', user_branch).order('date', desc=True).execute()

    records = build_records(att_r.data)
    return render_template('reports.html', records=records, sales=sales_r.data, from_date=from_date, to_date=to_date)


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
