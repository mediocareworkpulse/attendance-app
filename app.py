from flask import Flask, render_template, request, redirect, url_for
from datetime import date, datetime
from supabase import create_client

app = Flask(__name__)
app.secret_key = 'attendance-secret-2024'

SUPABASE_URL = 'https://lznqrkujlrcxcxizygzq.supabase.co'
SUPABASE_KEY = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Imx6bnFya3VqbHJjeGN4aXp5Z3pxIiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODQ1NjIwNjUsImV4cCI6MjEwMDEzODA2NX0.Jj_EW42NVMQk6zbEcNoY-IlrSe0tgW4zFiKoBSapiDA'

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)


def get_branches():
    r = supabase.table('branches').select('*').order('name').execute()
    return [b['name'] for b in r.data] if r.data else []


# ─── DASHBOARD ───────────────────────────────────────────
@app.route('/')
def home():
    today = str(date.today())
    branches = get_branches()

    r = supabase.table('employees').select('*').execute()
    total_employees = len(r.data)

    r2 = supabase.table('attendance').select('*').eq('date', today).execute()
    today_count = len(r2.data)
    absent_count = total_employees - today_count

    today_records = []
    for rec in r2.data:
        name, branch = 'Unknown', ''
        r3 = supabase.table('employees').select('full_name,branch').eq('employee_id', rec['employee_id']).execute()
        if r3.data:
            name = r3.data[0]['full_name']
            branch = r3.data[0].get('branch', '')
        today_records.append({
            'employee_id': rec['employee_id'], 'full_name': name, 'branch': branch,
            'check_in': rec.get('check_in', '—'), 'check_out': rec.get('check_out', '—'),
            'status': rec.get('status', 'present'), 'check_in_location': rec.get('check_in_location', '—')
        })

    return render_template('index.html', total_employees=total_employees, today_count=today_count,
                           absent_count=absent_count, today_records=today_records, branches=branches)


# ─── EMPLOYEES ───────────────────────────────────────────
@app.route('/employees')
def employees_page():
    branches = get_branches()
    branch_filter = request.args.get('branch', '')
    if branch_filter:
        r = supabase.table('employees').select('*').eq('branch', branch_filter).order('created_at', desc=True).execute()
    else:
        r = supabase.table('employees').select('*').order('created_at', desc=True).execute()
    return render_template('employees.html', employees=r.data, branches=branches, current_branch=branch_filter)


@app.route('/employees/add', methods=['POST'])
def add_employee():
    branches = get_branches()
    employee_id = request.form.get('employee_id', '').strip()
    full_name = request.form.get('full_name', '').strip()
    department = request.form.get('department', '').strip()
    branch = request.form.get('branch', '').strip()

    check = supabase.table('employees').select('*').eq('employee_id', employee_id).execute()
    if check.data:
        all_emp = supabase.table('employees').select('*').order('created_at', desc=True).execute()
        return render_template('employees.html', employees=all_emp.data, branches=branches,
                               message='Employee ID already exists!', message_type='error')

    supabase.table('employees').insert({
        'employee_id': employee_id, 'full_name': full_name,
        'department': department, 'branch': branch
    }).execute()
    return redirect(url_for('employees_page'))


@app.route('/employees/delete/<employee_id>', methods=['POST'])
def delete_employee(employee_id):
    supabase.table('employees').delete().eq('employee_id', employee_id).execute()
    return redirect(url_for('employees_page'))


# ─── BRANCHES ────────────────────────────────────────────
@app.route('/branches')
def branches_page():
    branches = get_branches()
    r = supabase.table('branches').select('*').order('name').execute()
    return render_template('branches.html', branches=r.data if r.data else [])


@app.route('/branches/add', methods=['POST'])
def add_branch():
    name = request.form.get('name', '').strip()
    if name:
        existing = supabase.table('branches').select('*').eq('name', name).execute()
        if not existing.data:
            supabase.table('branches').insert({'name': name}).execute()
    return redirect(url_for('branches_page'))


@app.route('/branches/delete/<int:branch_id>', methods=['POST'])
def delete_branch(branch_id):
    supabase.table('branches').delete().eq('id', branch_id).execute()
    return redirect(url_for('branches_page'))


# ─── CHECK IN / OUT ──────────────────────────────────────
@app.route('/check-in')
def check_in_page():
    today = str(date.today())
    branches = get_branches()
    r = supabase.table('attendance').select('*').eq('date', today).execute()
    today_records = build_records(r.data)
    return render_template('check_in.html', today_records=today_records, branches=branches)


@app.route('/check-in', methods=['POST'])
def process_attendance():
    employee_id = request.form.get('employee_id', '').strip()
    action = request.form.get('action')
    lat = request.form.get('lat', '')
    lng = request.form.get('lng', '')
    location = request.form.get('location', '')
    today = str(date.today())
    now = datetime.now().strftime('%H:%M:%S')
    branches = get_branches()

    emp_check = supabase.table('employees').select('*').eq('employee_id', employee_id).execute()
    if not emp_check.data:
        today_data = supabase.table('attendance').select('*').eq('date', today).execute()
        return render_template('check_in.html', today_records=build_records(today_data.data), branches=branches,
                               message='Employee ID not found!', message_type='error')

    emp_name = emp_check.data[0]['full_name']

    if action == 'check_in':
        existing = supabase.table('attendance').select('*').eq('employee_id', employee_id).eq('date', today).execute()
        if existing.data and existing.data[0].get('check_in'):
            today_data = supabase.table('attendance').select('*').eq('date', today).execute()
            return render_template('check_in.html', today_records=build_records(today_data.data), branches=branches,
                                   message=f'{emp_name} already checked in at {existing.data[0]["check_in"]}', message_type='error')

        status = 'late' if now > '09:00:00' else 'present'
        data = {'check_in': now, 'status': status, 'check_in_lat': lat, 'check_in_lng': lng, 'check_in_location': location}
        if existing.data:
            supabase.table('attendance').update(data).eq('employee_id', employee_id).eq('date', today).execute()
        else:
            data.update({'employee_id': employee_id, 'date': today})
            supabase.table('attendance').insert(data).execute()

    elif action == 'check_out':
        existing = supabase.table('attendance').select('*').eq('employee_id', employee_id).eq('date', today).execute()
        if not existing.data or not existing.data[0].get('check_in'):
            today_data = supabase.table('attendance').select('*').eq('date', today).execute()
            return render_template('check_in.html', today_records=build_records(today_data.data), branches=branches,
                                   message=f'{emp_name} has not checked in today!', message_type='error')
        if existing.data[0].get('check_out'):
            today_data = supabase.table('attendance').select('*').eq('date', today).execute()
            return render_template('check_in.html', today_records=build_records(today_data.data), branches=branches,
                                   message=f'{emp_name} already checked out at {existing.data[0]["check_out"]}', message_type='error')

        supabase.table('attendance').update({
            'check_out': now, 'check_out_lat': lat, 'check_out_lng': lng, 'check_out_location': location
        }).eq('employee_id', employee_id).eq('date', today).execute()

    return redirect(url_for('check_in_page'))


def build_records(records):
    result = []
    for rec in records:
        name, branch = 'Unknown', ''
        r = supabase.table('employees').select('full_name,branch').eq('employee_id', rec['employee_id']).execute()
        if r.data:
            name = r.data[0]['full_name']
            branch = r.data[0].get('branch', '')
        result.append({
            'employee_id': rec['employee_id'], 'full_name': name, 'branch': branch,
            'check_in': rec.get('check_in', '—'), 'check_out': rec.get('check_out', '—'),
            'status': rec.get('status', 'present'),
            'check_in_location': rec.get('check_in_location', '—'),
            'check_out_location': rec.get('check_out_location', '—')
        })
    return result


# ─── REPORTS ─────────────────────────────────────────────
@app.route('/reports')
def reports():
    branches = get_branches()
    from_date = request.args.get('from_date', str(date.today()))
    to_date = request.args.get('to_date', str(date.today()))
    branch_filter = request.args.get('branch', '')
    records = None

    if from_date and to_date:
        r = supabase.table('attendance').select('*').gte('date', from_date).lte('date', to_date).order('date', desc=True).execute()
        records = []
        for rec in r.data:
            name, emp_branch = 'Unknown', ''
            r2 = supabase.table('employees').select('full_name,branch').eq('employee_id', rec['employee_id']).execute()
            if r2.data:
                name = r2.data[0]['full_name']
                emp_branch = r2.data[0].get('branch', '')
            if branch_filter and emp_branch != branch_filter:
                continue
            records.append({
                'date': rec['date'], 'employee_id': rec['employee_id'], 'full_name': name, 'branch': emp_branch,
                'check_in': rec.get('check_in', '—'), 'check_out': rec.get('check_out', '—'),
                'status': rec.get('status', 'present'),
                'check_in_location': rec.get('check_in_location', '—'),
                'check_out_location': rec.get('check_out_location', '—')
            })

    return render_template('reports.html', records=records, from_date=from_date, to_date=to_date,
                           branches=branches, current_branch=branch_filter)


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
