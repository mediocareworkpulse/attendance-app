from flask import Flask, render_template, request, redirect, url_for, session
from datetime import date, datetime, timedelta
from supabase import create_client
from functools import wraps
from collections import defaultdict

app = Flask(__name__)
app.secret_key = 'attendance-secret-key-2024'

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

STATUS_LABELS = {'present':'Present','late':'Arrived Late','absent':'Absent','half-day':'Half Day','excused':'Excused'}
STATUS_CLASSES = {'present':'badge-success','late':'badge-warning','absent':'badge-danger','half-day':'badge-info','excused':'badge-secondary'}

def login_required(f):
    @wraps(f)
    def decorated(*args,**kwargs):
        if 'user' not in session:
            return redirect(url_for('login'))
        return f(*args,**kwargs)
    return decorated

def admin_required(f):
    @wraps(f)
    def decorated(*args,**kwargs):
        if session.get('role') not in ['admin','ceo']:
            return redirect(url_for('home'))
        return f(*args,**kwargs)
    return decorated

def get_branches():
    r = supabase.table('branches').select('*').order('name').execute()
    return [b['name'] for b in r.data] if r.data else []

# LOGIN
@app.route('/login', methods=['GET','POST'])
def login():
    if request.method == 'POST':
        name = request.form.get('full_name','').strip()
        password = request.form.get('password','').strip()
        r = supabase.table('employees').select('*').eq('full_name', name).execute()
        if r.data and r.data[0].get('password','1234') == password:
            emp = r.data[0]
            session['user'] = emp['full_name']
            session['role'] = emp.get('role','staff')
            session['department'] = emp.get('department','')
            session['branch'] = emp.get('branch','')
            session['emp_id'] = emp['id']
            return redirect(url_for('home'))
        return render_template('login.html', error='Invalid credentials')
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

# DASHBOARD
@app.route('/')
@login_required
def home():
    today = str(date.today())
    role = session.get('role','staff')
    user_branch = session.get('branch','')
    user_name = session.get('user','')

    if role in ['admin','ceo']:
        emp_r = supabase.table('employees').select('*').execute()
        att_r = supabase.table('attendance').select('*').eq('date',today).execute()
        sales_r = supabase.table('sales').select('*').eq('date',today).execute()
        branch_r = supabase.table('branch_sales').select('*').eq('date',today).execute()
    elif role == 'manager':
        emp_r = supabase.table('employees').select('*').eq('branch',user_branch).execute()
        att_r = supabase.table('attendance').select('*').eq('date',today).eq('branch',user_branch).execute()
        sales_r = supabase.table('sales').select('*').eq('date',today).eq('branch',user_branch).execute()
        branch_r = supabase.table('branch_sales').select('*').eq('date',today).eq('branch',user_branch).execute()
    else:
        emp_r = supabase.table('employees').select('*').eq('full_name',user_name).execute()
        att_r = supabase.table('attendance').select('*').eq('date',today).eq('full_name',user_name).execute()
        sales_r = supabase.table('sales').select('*').eq('date',today).eq('full_name',user_name).execute()
        branch_r = {'data':[]}

    total_employees = len(emp_r.data) if emp_r.data else 0
    present_count = len([a for a in (att_r.data or []) if a.get('check_in')])
    late_count = len([a for a in (att_r.data or []) if a.get('status')=='late'])
    total_sales = sum(float(s.get('amount',0)) for s in (sales_r.data or []))
    branch_total = sum(float(s.get('total_amount',0)) for s in (branch_r.data or []))

    user_checked_in = False
    user_checked_out = False
    if role not in ['admin','ceo']:
        my_att = supabase.table('attendance').select('*').eq('full_name',user_name).eq('date',today).execute()
        if my_att.data:
            user_checked_in = bool(my_att.data[0].get('check_in'))
            user_checked_out = bool(my_att.data[0].get('check_out'))

    recent_records = []
    for rec in (att_r.data or [])[:10]:
        s = rec.get('status','present')
        recent_records.append({
            'full_name':rec.get('full_name',''),'department':rec.get('department','—'),
            'branch':rec.get('branch','—'),'check_in':rec.get('check_in','—'),
            'check_out':rec.get('check_out','—'),'status':s,
            'status_label':STATUS_LABELS.get(s,s),'status_class':STATUS_CLASSES.get(s,'')
        })

    month_start = date.today().replace(day=1)
    month_att = supabase.table('attendance').select('*').eq('full_name',user_name).gte('date',str(month_start)).lte('date',today).execute() if role not in ['admin','ceo'] else {'data':[]}
    days_worked = len(set(a['date'] for a in (month_att.data or []) if a.get('check_in')))

    return render_template('index.html',total_employees=total_employees,present_count=present_count,late_count=late_count,total_sales=total_sales,branch_total=branch_total,user_checked_in=user_checked_in,user_checked_out=user_checked_out,recent_records=recent_records,days_worked=days_worked,today=today)

# EMPLOYEES
@app.route('/employees')
@login_required
@admin_required
def employees_page():
    dept_filter = request.args.get('department','')
    branch_filter = request.args.get('branch','')
    query = supabase.table('employees').select('*')
    if dept_filter: query = query.eq('department',dept_filter)
    if branch_filter: query = query.eq('branch',branch_filter)
    r = query.order('full_name').execute()
    return render_template('employees.html',employees=r.data or [],branches=get_branches(),departments=DEPARTMENTS,roles=ROLES,current_department=dept_filter,current_branch=branch_filter)

@app.route('/employees/add', methods=['POST'])
@login_required
@admin_required
def add_employee():
    d = {
        'full_name':request.form.get('full_name','').strip(),
        'department':request.form.get('department','').strip(),
        'branch':request.form.get('branch','').strip(),
        'role':request.form.get('role','staff').strip(),
        'password':request.form.get('password','1234').strip(),
        'email':request.form.get('email','').strip(),
        'phone':request.form.get('phone','').strip()
    }
    if d['full_name']:
        check = supabase.table('employees').select('*').eq('full_name',d['full_name']).execute()
        if not check.data:
            supabase.table('employees').insert(d).execute()
    return redirect(url_for('employees_page'))

@app.route('/employees/edit/<int:emp_id>', methods=['POST'])
@login_required
@admin_required
def edit_employee(emp_id):
    supabase.table('employees').update({
        'full_name':request.form.get('full_name','').strip(),
        'department':request.form.get('department','').strip(),
        'branch':request.form.get('branch','').strip(),
        'role':request.form.get('role','staff').strip(),
        'password':request.form.get('password','1234').strip(),
        'email':request.form.get('email','').strip(),
        'phone':request.form.get('phone','').strip(),
        'updated_at':datetime.now().isoformat()
    }).eq('id',emp_id).execute()
    return redirect(url_for('employees_page'))

@app.route('/employees/delete/<int:emp_id>', methods=['POST'])
@login_required
@admin_required
def delete_employee(emp_id):
    emp = supabase.table('employees').select('full_name').eq('id',emp_id).execute()
    if emp.data:
        n = emp.data[0]['full_name']
        supabase.table('attendance').delete().eq('full_name',n).execute()
        supabase.table('sales').delete().eq('full_name',n).execute()
    supabase.table('employees').delete().eq('id',emp_id).execute()
    return redirect(url_for('employees_page'))

# BRANCHES
@app.route('/branches')
@login_required
@admin_required
def branches_page():
    r = supabase.table('branches').select('*').order('name').execute()
    return render_template('branches.html',branches=r.data or [])

@app.route('/branches/add', methods=['POST'])
@login_required
@admin_required
def add_branch():
    n = request.form.get('name','').strip()
    a = request.form.get('address','').strip()
    if n:
        ex = supabase.table('branches').select('*').eq('name',n).execute()
        if not ex.data:
            supabase.table('branches').insert({'name':n,'address':a}).execute()
    return redirect(url_for('branches_page'))

@app.route('/branches/edit/<int:bid>', methods=['POST'])
@login_required
@admin_required
def edit_branch(bid):
    supabase.table('branches').update({'name':request.form.get('name','').strip(),'address':request.form.get('address','').strip()}).eq('id',bid).execute()
    return redirect(url_for('branches_page'))

@app.route('/branches/delete/<int:bid>', methods=['POST'])
@login_required
@admin_required
def delete_branch(bid):
    supabase.table('branches').delete().eq('id',bid).execute()
    return redirect(url_for('branches_page'))

# CHECK IN/OUT
@app.route('/check-in')
@login_required
def check_in_page():
    today = str(date.today())
    role = session.get('role')
    user_name = session.get('user')
    user_branch = session.get('branch','')
    if role in ['admin','ceo']:
        r = supabase.table('attendance').select('*').eq('date',today).order('check_in',desc=True).execute()
    elif role == 'manager':
        r = supabase.table('attendance').select('*').eq('date',today).eq('branch',user_branch).order('check_in',desc=True).execute()
    else:
        r = supabase.table('attendance').select('*').eq('date',today).eq('full_name',user_name).execute()
    records = []
    for rec in (r.data or []):
        s = rec.get('status','present')
        records.append({'full_name':rec.get('full_name',''),'department':rec.get('department','—'),'branch':rec.get('branch','—'),'check_in':rec.get('check_in','—'),'check_out':rec.get('check_out','—'),'status':s,'status_label':STATUS_LABELS.get(s,s),'status_class':STATUS_CLASSES.get(s,''),'check_in_location':rec.get('check_in_location','—')})
    user_status = 'none'
    if role not in ['admin','ceo']:
        my = supabase.table('attendance').select('*').eq('full_name',user_name).eq('date',today).execute()
        if my.data:
            if my.data[0].get('check_out'): user_status = 'completed'
            elif my.data[0].get('check_in'): user_status = 'checked_in'
    return render_template('check_in.html',records=records,user_status=user_status,today=today)

@app.route('/check-in', methods=['POST'])
@login_required
def process_attendance():
    if session.get('role') in ['admin','ceo']: return redirect(url_for('home'))
    user_name = session.get('user')
    action = request.form.get('action')
    lat = request.form.get('lat','')
    lng = request.form.get('lng','')
    loc = request.form.get('location','')
    today = str(date.today())
    now = datetime.now().strftime('%H:%M:%S')
    emp = supabase.table('employees').select('*').eq('full_name',user_name).execute()
    if not emp.data: return redirect(url_for('check_in_page'))
    dept = emp.data[0].get('department','')
    branch = emp.data[0].get('branch','')
    existing = supabase.table('attendance').select('*').eq('full_name',user_name).eq('date',today).execute()
    if action == 'check_in':
        if existing.data and existing.data[0].get('check_in'): return redirect(url_for('check_in_page'))
        status = 'late' if now > '09:00:00' else 'present'
        d = {'check_in':now,'status':status,'check_in_lat':lat,'check_in_lng':lng,'check_in_location':loc}
        if existing.data:
            supabase.table('attendance').update(d).eq('full_name',user_name).eq('date',today).execute()
        else:
            d.update({'full_name':user_name,'department':dept,'branch':branch,'date':today})
            supabase.table('attendance').insert(d).execute()
    elif action == 'check_out':
        if existing.data and existing.data[0].get('check_in') and not existing.data[0].get('check_out'):
            supabase.table('attendance').update({'check_out':now,'check_out_lat':lat,'check_out_lng':lng,'check_out_location':loc}).eq('full_name',user_name).eq('date',today).execute()
    return redirect(url_for('check_in_page'))

# ATTENDANCE HISTORY
@app.route('/attendance-history')
@login_required
def attendance_history():
    role = session.get('role')
    user_name = session.get('user')
    user_branch = session.get('branch','')
    period = request.args.get('period','month')
    cf = request.args.get('from_date','')
    ct = request.args.get('to_date','')
    today = date.today()
    if cf and ct: sd, ed = cf, ct
    elif period=='week': sd, ed = str(today-timedelta(days=7)), str(today)
    elif period=='month': sd, ed = str(today.replace(day=1)), str(today)
    elif period=='last_month':
        lm = today.replace(day=1)-timedelta(days=1)
        sd, ed = str(lm.replace(day=1)), str(lm)
    else: sd, ed = str(today-timedelta(days=30)), str(today)
    if role in ['admin','ceo']:
        r = supabase.table('attendance').select('*').gte('date',sd).lte('date',ed).order('date',desc=True).execute()
    elif role=='manager':
        r = supabase.table('attendance').select('*').gte('date',sd).lte('date',ed).eq('branch',user_branch).order('date',desc=True).execute()
    else:
        r = supabase.table('attendance').select('*').gte('date',sd).lte('date',ed).eq('full_name',user_name).order('date',desc=True).execute()
    records = []
    for rec in (r.data or []):
        s = rec.get('status','present')
        records.append({'full_name':rec.get('full_name',''),'department':rec.get('department','—'),'branch':rec.get('branch','—'),'date':rec.get('date',''),'check_in':rec.get('check_in','—'),'check_out':rec.get('check_out','—'),'status':s,'status_label':STATUS_LABELS.get(s,s),'status_class':STATUS_CLASSES.get(s,''),'check_in_location':rec.get('check_in_location','—')})
    dates = defaultdict(list)
    for rec in records: dates[rec['date']].append(rec)
    total_days = len(dates)
    present_days = sum(1 for d in dates.values() if any(r['status'] in ['present','late'] for r in d))
    late_days = sum(1 for d in dates.values() if any(r['status']=='late' for r in d))
    return render_template('attendance_history.html',records=records,period=period,start_date=sd,end_date=ed,total_days=total_days,present_days=present_days,late_days=late_days,today=str(today))

# SALES
@app.route('/sales', methods=['GET','POST'])
@login_required
def sales_page():
    role = session.get('role')
    user_name = session.get('user')
    user_branch = session.get('branch','')
    today = str(date.today())
    if request.method == 'POST':
        amt = request.form.get('amount','0')
        st = request.form.get('sales_type','individual')
        notes = request.form.get('notes','')
        emp = supabase.table('employees').select('*').eq('full_name',user_name).execute()
        if emp.data:
            dept = emp.data[0].get('department','')
            branch = emp.data[0].get('branch','')
            try:
                a = float(amt)
                if a > 0:
                    supabase.table('sales').insert({'full_name':user_name,'department':dept,'branch':branch,'date':today,'amount':a,'sales_type':st,'notes':notes}).execute()
                    if st == 'branch_total' and role == 'manager':
                        exb = supabase.table('branch_sales').select('*').eq('branch',branch).eq('date',today).execute()
                        if exb.data:
                            supabase.table('branch_sales').update({'total_amount':a,'submitted_by':user_name}).eq('branch',branch).eq('date',today).execute()
                        else:
                            supabase.table('branch_sales').insert({'branch':branch,'date':today,'total_amount':a,'submitted_by':user_name}).execute()
            except: pass
        return redirect(url_for('sales_page'))
    if role in ['admin','ceo']:
        sr = supabase.table('sales').select('*').eq('date',today).order('created_at',desc=True).execute()
        br = supabase.table('branch_sales').select('*').eq('date',today).execute()
        hr = supabase.table('sales').select('*').gte('date',str(date.today()-timedelta(days=7))).lte('date',today).order('date',desc=True).execute()
    elif role=='manager':
        sr = supabase.table('sales').select('*').eq('date',today).eq('branch',user_branch).order('created_at',desc=True).execute()
        br = supabase.table('branch_sales').select('*').eq('date',today).eq('branch',user_branch).execute()
        hr = supabase.table('sales').select('*').gte('date',str(date.today()-timedelta(days=7))).lte('date',today).eq('branch',user_branch).order('date',desc=True).execute()
    else:
        sr = supabase.table('sales').select('*').eq('date',today).eq('full_name',user_name).order('created_at',desc=True).execute()
        br = {'data':[]}
        hr = supabase.table('sales').select('*').gte('date',str(date.today()-timedelta(days=7))).lte('date',today).eq('full_name',user_name).order('date',desc=True).execute()
    btot = defaultdict(float)
    for s in (sr.data or []): btot[s.get('branch','Unknown')] += float(s.get('amount',0))
    mt = sum(float(s.get('amount',0)) for s in (sr.data or []) if s.get('full_name')==user_name)
    return render_template('sales.html',sales=sr.data or [],branch_sales=br.data or [],history=hr.data or [],branch_totals=dict(btot),my_total=mt,today=today)

# REPORTS
@app.route('/reports')
@login_required
def reports():
    role = session.get('role')
    if role not in ['admin','ceo','manager']: return redirect(url_for('home'))
    user_branch = session.get('branch','')
    fd = request.args.get('from_date',str(date.today().replace(day=1)))
    td = request.args.get('to_date',str(date.today()))
    rt = request.args.get('type','attendance')
    att_recs, sales_recs, bs_recs = [], [], []
    if rt == 'attendance':
        if role in ['admin','ceo']:
            r = supabase.table('attendance').select('*').gte('date',fd).lte('date',td).order('date',desc=True).execute()
        else:
            r = supabase.table('attendance').select('*').gte('date',fd).lte('date',td).eq('branch',user_branch).order('date',desc=True).execute()
        for rec in (r.data or []):
            s = rec.get('status','present')
            att_recs.append({'full_name':rec.get('full_name',''),'department':rec.get('department','—'),'branch':rec.get('branch','—'),'date':rec.get('date',''),'check_in':rec.get('check_in','—'),'check_out':rec.get('check_out','—'),'status':s,'status_label':STATUS_LABELS.get(s,s),'status_class':STATUS_CLASSES.get(s,'')})
    elif rt == 'sales':
        if role in ['admin','ceo']:
            sales_recs = (supabase.table('sales').select('*').gte('date',fd).lte('date',td).order('date',desc=True).execute()).data or []
            bs_recs = (supabase.table('branch_sales').select('*').gte('date',fd).lte('date',td).order('date',desc=True).execute()).data or []
        else:
            sales_recs = (supabase.table('sales').select('*').gte('date',fd).lte('date',td).eq('branch',user_branch).order('date',desc=True).execute()).data or []
            bs_recs = (supabase.table('branch_sales').select('*').gte('date',fd).lte('date',td).eq('branch',user_branch).order('date',desc=True).execute()).data or []
    tsa = sum(float(s.get('amount',0)) for s in sales_recs)
    tba = sum(float(s.get('total_amount',0)) for s in bs_recs)
    return render_template('reports.html',attendance_records=att_recs,sales_records=sales_recs,branch_sales_records=bs_recs,from_date=fd,to_date=td,report_type=rt,total_sales_amount=tsa,total_branch_amount=tba)

# PROFILE
@app.route('/profile', methods=['GET','POST'])
@login_required
def profile():
    user_name = session.get('user')
    if request.method == 'POST':
        np = request.form.get('new_password','').strip()
        if np: supabase.table('employees').update({'password':np}).eq('full_name',user_name).execute()
        return redirect(url_for('profile'))
    emp = supabase.table('employees').select('*').eq('full_name',user_name).execute()
    ed = emp.data[0] if emp.data else {}
    today = date.today()
    ms = today.replace(day=1)
    ma = supabase.table('attendance').select('*').eq('full_name',user_name).gte('date',str(ms)).lte('date',str(today)).execute()
    dp = len(set(a['date'] for a in (ma.data or []) if a.get('check_in')))
    my = supabase.table('sales').select('*').eq('full_name',user_name).gte('date',str(ms)).lte('date',str(today)).execute()
    tms = sum(float(s.get('amount',0)) for s in (my.data or []))
    return render_template('profile.html',employee=ed,days_present=dp,total_my_sales=tms)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
