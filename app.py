from flask import Flask, render_template, request, redirect, url_for, session
from datetime import date, datetime, timedelta
from supabase import create_client
from functools import wraps
from collections import defaultdict
import calendar

app = Flask(__name__)
app.secret_key = 'attendance-secret-key-2024-secure'

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

STATUS_LABELS = {
    'present': 'Present',
    'late': 'Arrived Late',
    'absent': 'Absent',
    'half-day': 'Half Day',
    'excused': 'Excused'
}

STATUS_CLASSES = {
    'present': 'badge badge-success',
    'late': 'badge badge-warning',
    'absent': 'badge badge-danger',
    'half-day': 'badge badge-info',
    'excused': 'badge badge-secondary'
}


def get_branches():
    r = supabase.table('branches').select('*').order('name').execute()
    return r.data if r.data else []


def get_branch_names():
    return [b['name'] for b in get_branches()]


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated


def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if session.get('role') not in ['admin', 'ceo']:
            return redirect(url_for('home'))
        return f(*args, **kwargs)
    return decorated


# ═══════════════════════════════════════════════════════════
# AUTHENTICATION
# ═══════════════════════════════════════════════════════════

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        name = request.form.get('full_name', '').strip()
        password = request.form.get('password', '').strip()

        r = supabase.table('employees').select('*').eq('full_name', name).execute()
        if r.data and r.data[0].get('password', '1234') == password:
            emp = r.data[0]
            session['user'] = emp['full_name']
            session['role'] = emp.get('role', 'staff')
            session['department'] = emp.get('department', '')
            session['branch'] = emp.get('branch', '')
            session['emp_id'] = emp['id']
            return redirect(url_for('home'))

        return render_template('login.html', error='Invalid credentials. Please try again.')

    return render_template('login.html')


@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))


# ═══════════════════════════════════════════════════════════
# DASHBOARD
# ═══════════════════════════════════════════════════════════

@app.route('/')
@login_required
def home():
    today = str(date.today())
    role = session.get('role', 'staff')
    user_branch = session.get('branch', '')
    user_name = session.get('user', '')

    # Employee count
    if role in ['admin', 'ceo']:
        emp_r = supabase.table('employees').select('*').execute()
    elif role == 'manager':
        emp_r = supabase.table('employees').select('*').eq('branch', user_branch).execute()
    else:
        emp_r = supabase.table('employees').select('*').eq('full_name', user_name).execute()

    total_employees = len(emp_r.data) if emp_r.data else 0

    # Today's attendance
    if role in ['admin', 'ceo']:
        att_r = supabase.table('attendance').select('*').eq('date', today).execute()
    elif role == 'manager':
        att_r = supabase.table('attendance').select('*').eq('date', today).eq('branch', user_branch).execute()
    else:
        att_r = supabase.table('attendance').select('*').eq('date', today).eq('full_name', user_name).execute()

    present_count = len([a for a in att_r.data if a.get('check_in')]) if att_r.data else 0
    late_count = len([a for a in att_r.data if a.get('status') == 'late']) if att_r.data else 0

    # Today's sales
    if role in ['admin', 'ceo']:
        sales_r = supabase.table('sales').select('*').eq('date', today).execute()
        branch_r = supabase.table('branch_sales').select('*').eq('date', today).execute()
    elif role == 'manager':
        sales_r = supabase.table('sales').select('*').eq('date', today).eq('branch', user_branch).execute()
        branch_r = supabase.table('branch_sales').select('*').eq('date', today).eq('branch', user_branch).execute()
    else:
        sales_r = supabase.table('sales').select('*').eq('date', today).eq('full_name', user_name).execute()
        branch_r = {'data': []}

    total_sales = sum(float(s.get('amount', 0)) for s in sales_r.data) if sales_r.data else 0
    branch_total = sum(float(s.get('total_amount', 0)) for s in branch_r.data) if branch_r.data else 0

    # User check-in status
    user_checked_in = False
    user_checked_out = False
    if role not in ['admin', 'ceo']:
        my_att = supabase.table('attendance').select('*').eq('full_name', user_name).eq('date', today).execute()
        if my_att.data:
            user_checked_in = bool(my_att.data[0].get('check_in'))
            user_checked_out = bool(my_att.data[0].get('check_out'))

    # Recent attendance records
    recent_records = []
    for rec in (att_r.data or [])[:10]:
        status = rec.get('status', 'present')
        recent_records.append({
            'full_name': rec.get('full_name', ''),
            'department': rec.get('department', '—'),
            'branch': rec.get('branch', '—'),
            'check_in': rec.get('check_in', '—'),
            'check_out': rec.get('check_out', '—'),
            'status': status,
            'status_label': STATUS_LABELS.get(status, status),
            'status_class': STATUS_CLASSES.get(status, ''),
            'location': rec.get('check_in_location', '—')
        })

    # Monthly attendance summary for charts
    month_start = date.today().replace(day=1)
    if role in ['admin', 'ceo']:
        month_att = supabase.table('attendance').select('*').gte('date', str(month_start)).lte('date', today).execute()
    elif role == 'manager':
        month_att = supabase.table('attendance').select('*').gte('date', str(month_start)).lte('date', today).eq('branch', user_branch).execute()
    else:
        month_att = supabase.table('attendance').select('*').gte('date', str(month_start)).lte('date', today).eq('full_name', user_name).execute()

    # Count days worked this month
    days_worked = len(set(a['date'] for a in (month_att.data or []) if a.get('check_in')))

    return render_template('index.html',
                         total_employees=total_employees,
                         present_count=present_count,
                         late_count=late_count,
                         total_sales=total_sales,
                         branch_total=branch_total,
                         user_checked_in=user_checked_in,
                         user_checked_out=user_checked_out,
                         recent_records=recent_records,
                         days_worked=days_worked,
                         today=today)


# ═══════════════════════════════════════════════════════════
# EMPLOYEES MANAGEMENT
# ═══════════════════════════════════════════════════════════

@app.route('/employees')
@login_required
@admin_required
def employees_page():
    branches = get_branch_names()
    dept_filter = request.args.get('department', '')
    branch_filter = request.args.get('branch', '')

    query = supabase.table('employees').select('*')
    if dept_filter:
        query = query.eq('department', dept_filter)
    if branch_filter:
        query = query.eq('branch', branch_filter)

    r = query.order('full_name').execute()
    return render_template('employees.html',
                         employees=r.data if r.data else [],
                         branches=branches,
                         departments=DEPARTMENTS,
                         roles=ROLES,
                         current_department=dept_filter,
                         current_branch=branch_filter)


@app.route('/employees/add', methods=['POST'])
@login_required
@admin_required
def add_employee():
    full_name = request.form.get('full_name', '').strip()
    department = request.form.get('department', '').strip()
    branch = request.form.get('branch', '').strip()
    role = request.form.get('role', 'staff').strip()
    password = request.form.get('password', '1234').strip()
    email = request.form.get('email', '').strip()
    phone = request.form.get('phone', '').strip()

    if not full_name:
        return redirect(url_for('employees_page'))

    check = supabase.table('employees').select('*').eq('full_name', full_name).execute()
    if check.data:
        all_emp = supabase.table('employees').select('*').order('full_name').execute()
        return render_template('employees.html',
                             employees=all_emp.data,
                             branches=get_branch_names(),
                             departments=DEPARTMENTS,
                             roles=ROLES,
                             message='An employee with this name already exists.',
                             message_type='error')

    supabase.table('employees').insert({
        'full_name': full_name,
        'department': department,
        'branch': branch,
        'role': role,
        'password': password,
        'email': email,
        'phone': phone
    }).execute()

    return redirect(url_for('employees_page'))


@app.route('/employees/edit/<int:emp_id>', methods=['POST'])
@login_required
@admin_required
def edit_employee(emp_id):
    supabase.table('employees').update({
        'full_name': request.form.get('full_name', '').strip(),
        'department': request.form.get('department', '').strip(),
        'branch': request.form.get('branch', '').strip(),
        'role': request.form.get('role', 'staff').strip(),
        'password': request.form.get('password', '1234').strip(),
        'email': request.form.get('email', '').strip(),
        'phone': request.form.get('phone', '').strip(),
        'updated_at': datetime.now().isoformat()
    }).eq('id', emp_id).execute()

    return redirect(url_for('employees_page'))


@app.route('/employees/delete/<int:emp_id>', methods=['POST'])
@login_required
@admin_required
def delete_employee(emp_id):
    emp = supabase.table('employees').select('full_name').eq('id', emp_id).execute()
    if emp.data:
        name = emp.data[0]['full_name']
        supabase.table('attendance').delete().eq('full_name', name).execute()
        supabase.table('sales').delete().eq('full_name', name).execute()
    supabase.table('employees').delete().eq('id', emp_id).execute()
    return redirect(url_for('employees_page'))


# ═══════════════════════════════════════════════════════════
# BRANCHES MANAGEMENT
# ═══════════════════════════════════════════════════════════

@app.route('/branches')
@login_required
@admin_required
def branches_page():
    r = supabase.table('branches').select('*').order('name').execute()
    return render_template('branches.html', branches=r.data if r.data else [])


@app.route('/branches/add', methods=['POST'])
@login_required
@admin_required
def add_branch():
    name = request.form.get('name', '').strip()
    address = request.form.get('address', '').strip()
    if name:
        existing = supabase.table('branches').select('*').eq('name', name).execute()
        if not existing.data:
            supabase.table('branches').insert({'name': name, 'address': address}).execute()
    return redirect(url_for('branches_page'))


@app.route('/branches/edit/<int:branch_id>', methods=['POST'])
@login_required
@admin_required
def edit_branch(branch_id):
    supabase.table('branches').update({
        'name': request.form.get('name', '').strip(),
        'address': request.form.get('address', '').strip()
    }).eq('id', branch_id).execute()
    return redirect(url_for('branches_page'))


@app.route('/branches/delete/<int:branch_id>', methods=['POST'])
@login_required
@admin_required
def delete_branch(branch_id):
    supabase.table('branches').delete().eq('id', branch_id).execute()
    return redirect(url_for('branches_page'))


# ═══════════════════════════════════════════════════════════
# CHECK IN / CHECK OUT
# ═══════════════════════════════════════════════════════════

@app.route('/check-in')
@login_required
def check_in_page():
    today = str(date.today())
    role = session.get('role')
    user_branch = session.get('branch', '')
    user_name = session.get('user', '')

    if role in ['admin', 'ceo']:
        r = supabase.table('attendance').select('*').eq('date', today).order('check_in', desc=True).execute()
    elif role == 'manager':
        r = supabase.table('attendance').select('*').eq('date', today).eq('branch', user_branch).order('check_in', desc=True).execute()
    else:
        r = supabase.table('attendance').select('*').eq('date', today).eq('full_name', user_name).execute()

    records = []
    for rec in (r.data or []):
        status = rec.get('status', 'present')
        records.append({
            'full_name': rec.get('full_name', ''),
            'department': rec.get('department', '—'),
            'branch': rec.get('branch', '—'),
            'date': rec.get('date', ''),
            'check_in': rec.get('check_in', '—'),
            'check_out': rec.get('check_out', '—'),
            'status': status,
            'status_label': STATUS_LABELS.get(status, status),
            'status_class': STATUS_CLASSES.get(status, ''),
            'check_in_location': rec.get('check_in_location', '—'),
            'check_out_location': rec.get('check_out_location', '—')
        })

    # Check user status
    user_status = 'none'
    if role not in ['admin', 'ceo']:
        my_att = supabase.table('attendance').select('*').eq('full_name', user_name).eq('date', today).execute()
        if my_att.data:
            if my_att.data[0].get('check_out'):
                user_status = 'completed'
            elif my_att.data[0].get('check_in'):
                user_status = 'checked_in'

    return render_template('check_in.html', records=records, user_status=user_status, today=today)


@app.route('/check-in', methods=['POST'])
@login_required
def process_attendance():
    if session.get('role') in ['admin', 'ceo']:
        return redirect(url_for('home'))

    user_name = session.get('user')
    action = request.form.get('action')
    lat = request.form.get('lat', '')
    lng = request.form.get('lng', '')
    location = request.form.get('location', '')
    today = str(date.today())
    now = datetime.now().strftime('%H:%M:%S')

    emp = supabase.table('employees').select('*').eq('full_name', user_name).execute()
    if not emp.data:
        return redirect(url_for('check_in_page'))

    department = emp.data[0].get('department', '')
    branch = emp.data[0].get('branch', '')

    if action == 'check_in':
        existing = supabase.table('attendance').select('*').eq('full_name', user_name).eq('date', today).execute()
        if existing.data and existing.data[0].get('check_in'):
            return redirect(url_for('check_in_page'))

        status = 'late' if now > '09:00:00' else 'present'
        data = {
            'check_in': now,
            'status': status,
            'check_in_lat': lat,
            'check_in_lng': lng,
            'check_in_location': location
        }

        if existing.data:
            supabase.table('attendance').update(data).eq('full_name', user_name).eq('date', today).execute()
        else:
            data.update({
                'full_name': user_name,
                'department': department,
                'branch': branch,
                'date': today
            })
            supabase.table('attendance').insert(data).execute()

    elif action == 'check_out':
        existing = supabase.table('attendance').select('*').eq('full_name', user_name).eq('date', today).execute()
        if existing.data and existing.data[0].get('check_in') and not existing.data[0].get('check_out'):
            supabase.table('attendance').update({
                'check_out': now,
                'check_out_lat': lat,
                'check_out_lng': lng,
                'check_out_location': location
            }).eq('full_name', user_name).eq('date', today).execute()

    return redirect(url_for('check_in_page'))


# ═══════════════════════════════════════════════════════════
# ATTENDANCE HISTORY
# ═══════════════════════════════════════════════════════════

@app.route('/attendance-history')
@login_required
def attendance_history():
    role = session.get('role')
    user_name = session.get('user')
    user_branch = session.get('branch', '')
    period = request.args.get('period', 'month')
    custom_from = request.args.get('from_date', '')
    custom_to = request.args.get('to_date', '')

    today = date.today()

    if custom_from and custom_to:
        start_date = custom_from
        end_date = custom_to
    elif period == 'week':
        start_date = str(today - timedelta(days=7))
        end_date = str(today)
    elif period == 'month':
        start_date = str(today.replace(day=1))
        end_date = str(today)
    elif period == 'last_month':
        first_of_month = today.replace(day=1)
        last_month_end = first_of_month - timedelta(days=1)
        last_month_start = last_month_end.replace(day=1)
        start_date = str(last_month_start)
        end_date = str(last_month_end)
    else:
        start_date = str(today - timedelta(days=30))
        end_date = str(today)

    # Build query
    if role in ['admin', 'ceo']:
        r = supabase.table('attendance').select('*').gte('date', start_date).lte('date', end_date).order('date', desc=True).order('check_in', desc=True).execute()
    elif role == 'manager':
        r = supabase.table('attendance').select('*').gte('date', start_date).lte('date', end_date).eq('branch', user_branch).order('date', desc=True).order('check_in', desc=True).execute()
    else:
        r = supabase.table('attendance').select('*').gte('date', start_date).lte('date', end_date).eq('full_name', user_name).order('date', desc=True).execute()

    records = []
    for rec in (r.data or []):
        status = rec.get('status', 'present')
        records.append({
            'id': rec.get('id'),
            'full_name': rec.get('full_name', ''),
            'department': rec.get('department', '—'),
            'branch': rec.get('branch', '—'),
            'date': rec.get('date', ''),
            'check_in': rec.get('check_in', '—'),
            'check_out': rec.get('check_out', '—'),
            'status': status,
            'status_label': STATUS_LABELS.get(status, status),
            'status_class': STATUS_CLASSES.get(status, ''),
            'check_in_location': rec.get('check_in_location', '—'),
            'check_out_location': rec.get('check_out_location', '—')
        })

    # Group by date for summary
    dates = defaultdict(list)
    for rec in records:
        dates[rec['date']].append(rec)

    # Summary stats
    total_days = len(dates)
    present_days = sum(1 for d in dates.values() if any(r['status'] in ['present', 'late'] for r in d))
    late_days = sum(1 for d in dates.values() if any(r['status'] == 'late' for r in d))

    return render_template('attendance_history.html',
                         records=records,
                         period=period,
                         start_date=start_date,
                         end_date=end_date,
                         total_days=total_days,
                         present_days=present_days,
                         late_days=late_days,
                         today=str(today))


# ═══════════════════════════════════════════════════════════
# SALES MANAGEMENT
# ═══════════════════════════════════════════════════════════

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
        if emp.data:
            dept = emp.data[0].get('department', '')
            branch = emp.data[0].get('branch', '')

            try:
                amt = float(amount)
                if amt > 0:
                    supabase.table('sales').insert({
                        'full_name': user_name,
                        'department': dept,
                        'branch': branch,
                        'date': today,
                        'amount': amt,
                        'sales_type': sales_type,
                        'notes': notes
                    }).execute()

                    # Branch total for managers
                    if sales_type == 'branch_total' and role == 'manager':
                        existing_bs = supabase.table('branch_sales').select('*').eq('branch', branch).eq('date', today).execute()
                        if existing_bs.data:
                            supabase.table('branch_sales').update({
                                'total_amount': amt,
                                'submitted_by': user_name
                            }).eq('branch', branch).eq('date', today).execute()
                        else:
                            supabase.table('branch_sales').insert({
                                'branch': branch,
                                'date': today,
                                'total_amount': amt,
                                'submitted_by': user_name
                            }).execute()
            except ValueError:
                pass

        return redirect(url_for('sales_page'))

    # Get today's sales
    if role in ['admin', 'ceo']:
        sales_r = supabase.table('sales').select('*').eq('date', today).order('created_at', desc=True).execute()
        branch_r = supabase.table('branch_sales').select('*').eq('date', today).execute()
    elif role == 'manager':
        sales_r = supabase.table('sales').select('*').eq('date', today).eq('branch', user_branch).order('created_at', desc=True).execute()
        branch_r = supabase.table('branch_sales').select('*').eq('date', today).eq('branch', user_branch).execute()
    else:
        sales_r = supabase.table('sales').select('*').eq('date', today).eq('full_name', user_name).order('created_at', desc=True).execute()
        branch_r = {'data': []}

    # Weekly history
    week_ago = str(date.today() - timedelta(days=7))
    if role in ['admin', 'ceo']:
        history_r = supabase.table('sales').select('*').gte('date', week_ago).lte('date', today).order('date', desc=True).execute()
    elif role == 'manager':
        history_r = supabase.table('sales').select('*').gte('date', week_ago).lte('date', today).eq('branch', user_branch).order('date', desc=True).execute()
    else:
        history_r = supabase.table('sales').select('*').gte('date', week_ago).lte('date', today).eq('full_name', user_name).order('date', desc=True).execute()

    # Branch totals for today
    branch_totals = defaultdict(float)
    for s in (sales_r.data or []):
        br = s.get('branch', 'Unknown')
        branch_totals[br] += float(s.get('amount', 0))

    # Individual total
    my_total = sum(float(s.get('amount', 0)) for s in (sales_r.data or []) if s.get('full_name') == user_name)

    return render_template('sales.html',
                         sales=sales_r.data if sales_r.data else [],
                         branch_sales=branch_r.data if branch_r.data else [],
                         history=history_r.data if history_r.data else [],
                         branch_totals=dict(branch_totals),
                         my_total=my_total,
                         today=today)


# ═══════════════════════════════════════════════════════════
# REPORTS (Admin/Manager)
# ═══════════════════════════════════════════════════════════

@app.route('/reports')
@login_required
def reports():
    role = session.get('role')
    if role not in ['admin', 'ceo', 'manager', 'accountant']:
        return redirect(url_for('home'))

    user_branch = session.get('branch', '')
    from_date = request.args.get('from_date', str(date.today().replace(day=1)))
    to_date = request.args.get('to_date', str(date.today()))
    report_type = request.args.get('type', 'attendance')

    attendance_records = []
    sales_records = []
    branch_sales_records = []

    if report_type == 'attendance':
        if role in ['admin', 'ceo']:
            r = supabase.table('attendance').select('*').gte('date', from_date).lte('date', to_date).order('date', desc=True).execute()
        else:
            r = supabase.table('attendance').select('*').gte('date', from_date).lte('date', to_date).eq('branch', user_branch).order('date', desc=True).execute()

        for rec in (r.data or []):
            status = rec.get('status', 'present')
            attendance_records.append({
                'full_name': rec.get('full_name', ''),
                'department': rec.get('department', '—'),
                'branch': rec.get('branch', '—'),
                'date': rec.get('date', ''),
                'check_in': rec.get('check_in', '—'),
                'check_out': rec.get('check_out', '—'),
                'status': status,
                'status_label': STATUS_LABELS.get(status, status),
                'status_class': STATUS_CLASSES.get(status, ''),
                'check_in_location': rec.get('check_in_location', '—')
            })

    elif report_type == 'sales':
        if role in ['admin', 'ceo']:
            r = supabase.table('sales').select('*').gte('date', from_date).lte('date', to_date).order('date', desc=True).execute()
            br = supabase.table('branch_sales').select('*').gte('date', from_date).lte('date', to_date).order('date', desc=True).execute()
        else:
            r = supabase.table('sales').select('*').gte('date', from_date).lte('date', to_date).eq('branch', user_branch).order('date', desc=True).execute()
            br = supabase.table('branch_sales').select('*').gte('date', from_date).lte('date', to_date).eq('branch', user_branch).order('date', desc=True).execute()

        sales_records = r.data if r.data else []
        branch_sales_records = br.data if br.data else []

    # Totals
    total_sales_amount = sum(float(s.get('amount', 0)) for s in sales_records)
    total_branch_amount = sum(float(s.get('total_amount', 0)) for s in branch_sales_records)

    return render_template('reports.html',
                         attendance_records=attendance_records,
                         sales_records=sales_records,
                         branch_sales_records=branch_sales_records,
                         from_date=from_date,
                         to_date=to_date,
                         report_type=report_type,
                         total_sales_amount=total_sales_amount,
                         total_branch_amount=total_branch_amount)


# ═══════════════════════════════════════════════════════════
# PROFILE
# ═══════════════════════════════════════════════════════════

@app.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    user_name = session.get('user')
    if request.method == 'POST':
        new_password = request.form.get('new_password', '').strip()
        if new_password:
            supabase.table('employees').update({'password': new_password}).eq('full_name', user_name).execute()
        return redirect(url_for('profile'))

    emp = supabase.table('employees').select('*').eq('full_name', user_name).execute()
    emp_data = emp.data[0] if emp.data else {}

    # My attendance stats
    today = date.today()
    month_start = today.replace(day=1)
    my_att = supabase.table('attendance').select('*').eq('full_name', user_name).gte('date', str(month_start)).lte('date', str(today)).execute()
    days_present = len(set(a['date'] for a in (my_att.data or []) if a.get('check_in')))

    # My sales this month
    my_sales = supabase.table('sales').select('*').eq('full_name', user_name).gte('date', str(month_start)).lte('date', str(today)).execute()
    total_my_sales = sum(float(s.get('amount', 0)) for s in (my_sales.data or []))

    return render_template('profile.html',
                         employee=emp_data,
                         days_present=days_present,
                         total_my_sales=total_my_sales)


# ═══════════════════════════════════════════════════════════
# RUN
# ═══════════════════════════════════════════════════════════

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
