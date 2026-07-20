import os
from datetime import date, datetime
from flask import Flask, render_template, request, redirect, url_for
from supabase import create_client

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'dev-secret-key-2024')

SUPABASE_URL = os.environ.get('SUPABASE_URL', 'https://lznqrkujlrcxcxizygzq.supabase.co')
SUPABASE_KEY = os.environ.get('SUPABASE_KEY', 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Imx6bnFya3VqbHJjeGN4aXp5Z3pxIiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODQ1NjIwNjUsImV4cCI6MjEwMDEzODA2NX0.Jj_EW42NVMQk6zbEcNoY-IlrSe0tgW4zFiKoBSapiDA')

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)


@app.route('/')
def home():
    today = str(date.today())
    
    try:
        emp_result = supabase.table('employees').select('*').execute()
        total_employees = len(emp_result.data) if emp_result.data else 0
    except Exception as e:
        return f"Database error: {str(e)}", 500
    
    try:
        att_result = supabase.table('attendance').select('*').eq('date', today).execute()
        today_count = len(att_result.data) if att_result.data else 0
    except:
        today_count = 0
    
    absent_count = total_employees - today_count
    
    today_records = []
    try:
        for record in att_result.data:
            emp = supabase.table('employees').select('full_name').eq('employee_id', record['employee_id']).execute()
            name = emp.data[0]['full_name'] if emp.data else 'Unknown'
            today_records.append({
                'employee_id': record['employee_id'],
                'full_name': name,
                'check_in': record.get('check_in'),
                'check_out': record.get('check_out'),
                'status': record.get('status', 'present')
            })
    except:
        pass
    
    return render_template('index.html',
                         total_employees=total_employees,
                         today_count=today_count,
                         absent_count=absent_count,
                         today_records=today_records)


@app.route('/employees')
def employees_page():
    try:
        result = supabase.table('employees').select('*').order('created_at', desc=True).execute()
        emp_list = result.data if result.data else []
    except Exception as e:
        return f"Database error: {str(e)}", 500
    return render_template('employees.html', employees=emp_list)


@app.route('/employees/add', methods=['POST'])
def add_employee():
    employee_id = request.form.get('employee_id', '').strip()
    full_name = request.form.get('full_name', '').strip()
    department = request.form.get('department', '').strip()
    
    try:
        existing = supabase.table('employees').select('*').eq('employee_id', employee_id).execute()
        if existing.data:
            all_employees = supabase.table('employees').select('*').order('created_at', desc=True).execute()
            return render_template('employees.html',
                                 employees=all_employees.data,
                                 message='Employee ID already exists!',
                                 message_type='error')
        
        supabase.table('employees').insert({
            'employee_id': employee_id,
            'full_name': full_name,
            'department': department
        }).execute()
    except Exception as e:
        return f"Error adding employee: {str(e)}", 500
    
    return redirect(url_for('employees_page'))


@app.route('/employees/delete/<employee_id>', methods=['POST'])
def delete_employee(employee_id):
    try:
        supabase.table('employees').delete().eq('employee_id', employee_id).execute()
    except:
        pass
    return redirect(url_for('employees_page'))


@app.route('/check-in')
def check_in_page():
    today = str(date.today())
    try:
        attendance_today = supabase.table('attendance').select('*').eq('date', today).execute()
        records = attendance_today.data if attendance_today.data else []
    except:
        records = []
    
    today_records = build_today_records(records)
    return render_template('check_in.html', today_records=today_records)


@app.route('/check-in', methods=['POST'])
def process_attendance():
    employee_id = request.form.get('employee_id', '').strip()
    action = request.form.get('action')
    today = str(date.today())
    now = datetime.now().strftime('%H:%M:%S')
    
    try:
        emp_check = supabase.table('employees').select('*').eq('employee_id', employee_id).execute()
    except:
        return "Database error", 500
    
    if not emp_check.data:
        return render_template('check_in.html',
                             today_records=[],
                             message='Employee ID not found!',
                             message_type='error')
    
    emp_name = emp_check.data[0]['full_name']
    
    try:
        if action == 'check_in':
            existing = supabase.table('attendance').select('*').eq('employee_id', employee_id).eq('date', today).execute()
            
            if existing.data and existing.data[0].get('check_in'):
                return render_template('check_in.html',
                                     today_records=build_today_records(get_today_attendance()),
                                     message=f'{emp_name} already checked in at {existing.data[0]["check_in"]}',
                                     message_type='error')
            
            status = 'late' if now > '09:00:00' else 'present'
            
            if existing.data:
                supabase.table('attendance').update({'check_in': now, 'status': status}).eq('employee_id', employee_id).eq('date', today).execute()
            else:
                supabase.table('attendance').insert({'employee_id': employee_id, 'date': today, 'check_in': now, 'status': status}).execute()
        
        elif action == 'check_out':
            existing = supabase.table('attendance').select('*').eq('employee_id', employee_id).eq('date', today).execute()
            
            if not existing.data or not existing.data[0].get('check_in'):
                return render_template('check_in.html',
                                     today_records=build_today_records(get_today_attendance()),
                                     message=f'{emp_name} has not checked in today!',
                                     message_type='error')
            
            if existing.data[0].get('check_out'):
                return render_template('check_in.html',
                                     today_records=build_today_records(get_today_attendance()),
                                     message=f'{emp_name} already checked out at {existing.data[0]["check_out"]}',
                                     message_type='error')
            
            supabase.table('attendance').update({'check_out': now}).eq('employee_id', employee_id).eq('date', today).execute()
    except Exception as e:
        return f"Error: {str(e)}", 500
    
    return redirect(url_for('check_in_page'))


def get_today_attendance():
    today = str(date.today())
    try:
        result = supabase.table('attendance').select('*').eq('date', today).execute()
        return result.data if result.data else []
    except:
        return []


def build_today_records(records):
    today_records = []
    for record in records:
        try:
            emp = supabase.table('employees').select('full_name').eq('employee_id', record['employee_id']).execute()
            name = emp.data[0]['full_name'] if emp.data else 'Unknown'
        except:
            name = 'Unknown'
        today_records.append({
            'employee_id': record['employee_id'],
            'full_name': name,
            'check_in': record.get('check_in'),
            'check_out': record.get('check_out'),
            'status': record.get('status', 'present')
        })
    return today_records


@app.route('/reports')
def reports():
    from_date = request.args.get('from_date', str(date.today()))
    to_date = request.args.get('to_date', str(date.today()))
    records = None
    
    if from_date and to_date:
        try:
            result = supabase.table('attendance').select('*').gte('date', from_date).lte('date', to_date).order('date', desc=True).execute()
            records = []
            for record in result.data:
                try:
                    emp = supabase.table('employees').select('full_name').eq('employee_id', record['employee_id']).execute()
                    name = emp.data[0]['full_name'] if emp.data else 'Unknown'
                except:
                    name = 'Unknown'
                records.append({
                    'date': record['date'],
                    'employee_id': record['employee_id'],
                    'full_name': name,
                    'check_in': record.get('check_in'),
                    'check_out': record.get('check_out'),
                    'status': record.get('status', 'present')
                })
        except:
            records = []
    
    return render_template('reports.html', records=records, from_date=from_date, to_date=to_date)


if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
