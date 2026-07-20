from flask import Flask, render_template, request, redirect, url_for
from datetime import date, datetime
import os
import httpx
from postgrest import PostgrestClient

app = Flask(__name__)
app.secret_key = 'attendance-secret-2024'

SUPABASE_URL = 'https://lznqrkujlrcxcxizygzq.supabase.co'
SUPABASE_KEY = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Imx6bnFya3VqbHJjeGN4aXp5Z3pxIiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODQ1NjIwNjUsImV4cCI6MjEwMDEzODA2NX0.Jj_EW42NVMQk6zbEcNoY-IlrSe0tgW4zFiKoBSapiDA'

client = PostgrestClient(base_url=f"{SUPABASE_URL}/rest/v1", headers={"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"})


@app.route('/')
def home():
    today = str(date.today())
    
    r = client.from_('employees').select('*').execute()
    total_employees = len(r.data)
    
    r2 = client.from_('attendance').select('*').eq('date', today).execute()
    today_count = len(r2.data)
    absent_count = total_employees - today_count
    
    today_records = []
    for rec in r2.data:
        name = 'Unknown'
        r3 = client.from_('employees').select('full_name').eq('employee_id', rec['employee_id']).execute()
        if r3.data:
            name = r3.data[0]['full_name']
        today_records.append({
            'employee_id': rec['employee_id'],
            'full_name': name,
            'check_in': rec.get('check_in', '—'),
            'check_out': rec.get('check_out', '—'),
            'status': rec.get('status', 'present')
        })
    
    return render_template('index.html', total_employees=total_employees, today_count=today_count, absent_count=absent_count, today_records=today_records)


@app.route('/employees')
def employees_page():
    r = client.from_('employees').select('*').order('created_at', desc=True).execute()
    return render_template('employees.html', employees=r.data)


@app.route('/employees/add', methods=['POST'])
def add_employee():
    employee_id = request.form.get('employee_id', '').strip()
    full_name = request.form.get('full_name', '').strip()
    department = request.form.get('department', '').strip()
    
    check = client.from_('employees').select('*').eq('employee_id', employee_id).execute()
    if check.data:
        all_emp = client.from_('employees').select('*').order('created_at', desc=True).execute()
        return render_template('employees.html', employees=all_emp.data, message='Employee ID already exists!', message_type='error')
    
    client.from_('employees').insert({'employee_id': employee_id, 'full_name': full_name, 'department': department}).execute()
    return redirect(url_for('employees_page'))


@app.route('/employees/delete/<employee_id>', methods=['POST'])
def delete_employee(employee_id):
    client.from_('employees').delete().eq('employee_id', employee_id).execute()
    return redirect(url_for('employees_page'))


@app.route('/check-in')
def check_in_page():
    today = str(date.today())
    r = client.from_('attendance').select('*').eq('date', today).execute()
    today_records = build_records(r.data)
    return render_template('check_in.html', today_records=today_records)


@app.route('/check-in', methods=['POST'])
def process_attendance():
    employee_id = request.form.get('employee_id', '').strip()
    action = request.form.get('action')
    today = str(date.today())
    now = datetime.now().strftime('%H:%M:%S')
    
    emp_check = client.from_('employees').select('*').eq('employee_id', employee_id).execute()
    if not emp_check.data:
        today_data = client.from_('attendance').select('*').eq('date', today).execute()
        return render_template('check_in.html', today_records=build_records(today_data.data), message='Employee ID not found!', message_type='error')
    
    emp_name = emp_check.data[0]['full_name']
    
    if action == 'check_in':
        existing = client.from_('attendance').select('*').eq('employee_id', employee_id).eq('date', today).execute()
        if existing.data and existing.data[0].get('check_in'):
            today_data = client.from_('attendance').select('*').eq('date', today).execute()
            return render_template('check_in.html', today_records=build_records(today_data.data), message=f'{emp_name} already checked in at {existing.data[0]["check_in"]}', message_type='error')
        
        status = 'late' if now > '09:00:00' else 'present'
        if existing.data:
            client.from_('attendance').update({'check_in': now, 'status': status}).eq('employee_id', employee_id).eq('date', today).execute()
        else:
            client.from_('attendance').insert({'employee_id': employee_id, 'date': today, 'check_in': now, 'status': status}).execute()
    
    elif action == 'check_out':
        existing = client.from_('attendance').select('*').eq('employee_id', employee_id).eq('date', today).execute()
        if not existing.data or not existing.data[0].get('check_in'):
            today_data = client.from_('attendance').select('*').eq('date', today).execute()
            return render_template('check_in.html', today_records=build_records(today_data.data), message=f'{emp_name} has not checked in today!', message_type='error')
        if existing.data[0].get('check_out'):
            today_data = client.from_('attendance').select('*').eq('date', today).execute()
            return render_template('check_in.html', today_records=build_records(today_data.data), message=f'{emp_name} already checked out at {existing.data[0]["check_out"]}', message_type='error')
        
        client.from_('attendance').update({'check_out': now}).eq('employee_id', employee_id).eq('date', today).execute()
    
    return redirect(url_for('check_in_page'))


def build_records(records):
    result = []
    for rec in records:
        name = 'Unknown'
        r = client.from_('employees').select('full_name').eq('employee_id', rec['employee_id']).execute()
        if r.data:
            name = r.data[0]['full_name']
        result.append({'employee_id': rec['employee_id'], 'full_name': name, 'check_in': rec.get('check_in', '—'), 'check_out': rec.get('check_out', '—'), 'status': rec.get('status', 'present')})
    return result


@app.route('/reports')
def reports():
    from_date = request.args.get('from_date', str(date.today()))
    to_date = request.args.get('to_date', str(date.today()))
    records = None
    
    if from_date and to_date:
        r = client.from_('attendance').select('*').gte('date', from_date).lte('date', to_date).order('date', desc=True).execute()
        records = []
        for rec in r.data:
            name = 'Unknown'
            r2 = client.from_('employees').select('full_name').eq('employee_id', rec['employee_id']).execute()
            if r2.data:
                name = r2.data[0]['full_name']
            records.append({'date': rec['date'], 'employee_id': rec['employee_id'], 'full_name': name, 'check_in': rec.get('check_in', '—'), 'check_out': rec.get('check_out', '—'), 'status': rec.get('status', 'present')})
    
    return render_template('reports.html', records=records, from_date=from_date, to_date=to_date)


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
