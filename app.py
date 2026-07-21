from flask import Flask, render_template, request, redirect, url_for, session
from datetime import date, datetime, timedelta
from supabase import create_client
from functools import wraps

app = Flask(__name__)
app.secret_key = 'attendance-secret-key-2024'

SUPABASE_URL = 'https://lznqrkujlrcxcxizygzq.supabase.co'
SUPABASE_KEY = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Imx6bnFya3VqbHJjeGN4aXp5Z3pxIiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODQ1NjIwNjUsImV4cCI6MjEwMDEzODA2NX0.Jj_EW42NVMQk6zbEcNoY-IlrSe0tgW4zFiKoBSapiDA'

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

DEPARTMENTS = ['Staff','Branch Manager','Assistant Branch Manager','Stock Controller','Stock Assistant','HR','HR Assistant','Accountant','Accountant Assistant','Procurement','Store Manager','Store Assistant','Store Person','Telesales','Dispatch','Operations Manager','Operations Assistant','Sales Manager','Cashier','IT','CEO']
ROLES = ['staff','manager','admin','ceo']

def login_required(f):
    @wraps(f)
    def d(*a,**k):
        if 'user' not in session: return redirect('/login')
        return f(*a,**k)
    return d

def get_branches():
    r = supabase.table('branches').select('*').order('name').execute()
    return [b['name'] for b in (r.data or [])]

# ─── LOGIN ──────────────────────────────
@app.route('/login', methods=['GET','POST'])
def login():
    if request.method == 'POST':
        name = request.form.get('full_name','').strip()
        pw = request.form.get('password','').strip()
        r = supabase.table('employees').select('*').eq('full_name',name).execute()
        if r.data:
            emp = r.data[0]
            if emp.get('password','') == pw:
                if emp.get('status','pending') != 'approved':
                    return render_template('login.html', error='Account pending approval.')
                session['user'] = emp['full_name']
                session['role'] = emp.get('role','staff')
                session['department'] = emp.get('department','')
                session['branch'] = emp.get('branch','')
                return redirect('/')
        return render_template('login.html', error='Invalid credentials')
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect('/login')

# ─── SIGNUP ─────────────────────────────
@app.route('/signup', methods=['GET','POST'])
def signup():
    if request.method == 'POST':
        name = request.form.get('full_name','').strip()
        phone = request.form.get('phone','').strip()
        pw = request.form.get('password','').strip()
        dept = request.form.get('department','').strip()
        branch = request.form.get('branch','').strip()
        if not name or not phone or not pw:
            return render_template('signup.html', branches=get_branches(), departments=DEPARTMENTS, error='All fields required')
        check = supabase.table('employees').select('*').eq('full_name',name).execute()
        if check.data:
            return render_template('signup.html', branches=get_branches(), departments=DEPARTMENTS, error='Name already exists')
        supabase.table('employees').insert({'full_name':name,'phone':phone,'password':pw,'department':dept,'branch':branch,'role':'staff','status':'pending'}).execute()
        return render_template('signup.html', branches=get_branches(), departments=DEPARTMENTS, success='Registered! Wait for admin approval.')
    return render_template('signup.html', branches=get_branches(), departments=DEPARTMENTS)

# ─── DASHBOARD ──────────────────────────
@app.route('/')
@login_required
def home():
    today = str(date.today())
    role = session.get('role','staff')
    ub = session.get('branch','')
    un = session.get('user','')

    if role in ['admin','ceo']:
        emp_r = supabase.table('employees').select('*').eq('status','approved').execute()
        att_r = supabase.table('attendance').select('*').eq('date',today).execute()
        sales_r = supabase.table('sales').select('*').eq('date',today).execute()
    elif role == 'manager':
        emp_r = supabase.table('employees').select('*').eq('branch',ub).eq('status','approved').execute()
        att_r = supabase.table('attendance').select('*').eq('date',today).eq('branch',ub).execute()
        sales_r = supabase.table('sales').select('*').eq('date',today).eq('branch',ub).execute()
    else:
        emp_r = {'data':[]}
        att_r = supabase.table('attendance').select('*').eq('date',today).eq('full_name',un).execute()
        sales_r = supabase.table('sales').select('*').eq('date',today).eq('full_name',un).execute()

    total_emp = len(emp_r.data) if emp_r.data else 0
    present = len([a for a in (att_r.data or []) if a.get('check_in')])
    late = len([a for a in (att_r.data or []) if a.get('status')=='late'])
    total_sales = sum(float(s.get('amount',0)) for s in (sales_r.data or []))

    records = []
    for rec in (att_r.data or [])[:10]:
        st = rec.get('status','present')
        records.append({'full_name':rec.get('full_name',''),'department':rec.get('department','—'),'branch':rec.get('branch','—'),'check_in':rec.get('check_in','—'),'check_out':rec.get('check_out','—'),'status':st,'label':{'present':'Present','late':'Arrived Late','absent':'Absent'}.get(st,st)})

    uci, uco = False, False
    if role not in ['admin','ceo']:
        my = supabase.table('attendance').select('*').eq('full_name',un).eq('date',today).execute()
        if my.data:
            uci = bool(my.data[0].get('check_in'))
            uco = bool(my.data[0].get('check_out'))

    pending = 0
    if role in ['admin','ceo']:
        pr = supabase.table('employees').select('*').eq('status','pending').execute()
        pending = len(pr.data) if pr.data else 0

    return render_template('index.html',total_employees=total_emp,present_count=present,late_count=late,total_sales=total_sales,branch_total=0,recent_records=records,user_checked_in=uci,user_checked_out=uco,pending_count=pending,days_worked=0,today=today)

# ─── APPROVALS ──────────────────────────
@app.route('/approvals')
@login_required
def approvals_page():
    if session.get('role') not in ['admin','ceo']: return redirect('/')
    r = supabase.table('employees').select('*').eq('status','pending').order('created_at',desc=True).execute()
    return render_template('approvals.html', pending=r.data or [])

@app.route('/approvals/approve/<int:eid>', methods=['POST'])
@login_required
def approve(eid):
    if session.get('role') not in ['admin','ceo']: return redirect('/')
    supabase.table('employees').update({'status':'approved'}).eq('id',eid).execute()
    return redirect('/approvals')

@app.route('/approvals/reject/<int:eid>', methods=['POST'])
@login_required
def reject(eid):
    if session.get('role') not in ['admin','ceo']: return redirect('/')
    supabase.table('employees').delete().eq('id',eid).execute()
    return redirect('/approvals')

# ─── EMPLOYEES ──────────────────────────
@app.route('/employees')
@login_required
def employees_page():
    if session.get('role') not in ['admin','ceo']: return redirect('/')
    r = supabase.table('employees').select('*').eq('status','approved').order('full_name').execute()
    return render_template('employees.html', employees=r.data or [], branches=get_branches(), departments=DEPARTMENTS, roles=ROLES)

@app.route('/employees/add', methods=['POST'])
@login_required
def add_employee():
    if session.get('role') not in ['admin','ceo']: return redirect('/')
    d = {'full_name':request.form.get('full_name','').strip(),'department':request.form.get('department','').strip(),'branch':request.form.get('branch','').strip(),'role':request.form.get('role','staff').strip(),'password':request.form.get('password','1234').strip(),'status':'approved'}
    if d['full_name']:
        supabase.table('employees').insert(d).execute()
    return redirect('/employees')

@app.route('/employees/delete/<int:eid>', methods=['POST'])
@login_required
def delete_employee(eid):
    if session.get('role') not in ['admin','ceo']: return redirect('/')
    emp = supabase.table('employees').select('full_name').eq('id',eid).execute()
    if emp.data:
        n = emp.data[0]['full_name']
        supabase.table('attendance').delete().eq('full_name',n).execute()
        supabase.table('sales').delete().eq('full_name',n).execute()
    supabase.table('employees').delete().eq('id',eid).execute()
    return redirect('/employees')

# ─── BRANCHES ───────────────────────────
@app.route('/branches')
@login_required
def branches_page():
    if session.get('role') not in ['admin','ceo']: return redirect('/')
    r = supabase.table('branches').select('*').order('name').execute()
    return render_template('branches.html', branches=r.data or [])

@app.route('/branches/add', methods=['POST'])
@login_required
def add_branch():
    if session.get('role') not in ['admin','ceo']: return redirect('/')
    n = request.form.get('name','').strip()
    if n:
        supabase.table('branches').insert({'name':n}).execute()
    return redirect('/branches')

@app.route('/branches/delete/<int:bid>', methods=['POST'])
@login_required
def delete_branch(bid):
    if session.get('role') in ['admin','ceo']:
        supabase.table('branches').delete().eq('id',bid).execute()
    return redirect('/branches')

# ─── CHECK IN/OUT ───────────────────────
@app.route('/check-in')
@login_required
def check_in_page():
    today = str(date.today())
    role = session.get('role')
    un = session.get('user')
    ub = session.get('branch','')
    if role in ['admin','ceo']:
        r = supabase.table('attendance').select('*').eq('date',today).execute()
    elif role == 'manager':
        r = supabase.table('attendance').select('*').eq('date',today).eq('branch',ub).execute()
    else:
        r = supabase.table('attendance').select('*').eq('date',today).eq('full_name',un).execute()
    records = []
    for rec in (r.data or []):
        st = rec.get('status','present')
        records.append({'full_name':rec.get('full_name',''),'department':rec.get('department','—'),'check_in':rec.get('check_in','—'),'check_out':rec.get('check_out','—'),'status':st,'label':{'present':'Present','late':'Arrived Late'}.get(st,st),'loc':rec.get('check_in_location','—')})
    us = 'none'
    if role not in ['admin','ceo']:
        my = supabase.table('attendance').select('*').eq('full_name',un).eq('date',today).execute()
        if my.data:
            if my.data[0].get('check_out'): us = 'completed'
            elif my.data[0].get('check_in'): us = 'checked_in'
    return render_template('check_in.html', records=records, user_status=us, today=today)

@app.route('/check-in', methods=['POST'])
@login_required
def process_attendance():
    if session.get('role') in ['admin','ceo']: return redirect('/')
    un = session.get('user')
    action = request.form.get('action')
    lat = request.form.get('lat','')
    lng = request.form.get('lng','')
    loc = request.form.get('location','')
    today = str(date.today())
    now = datetime.now().strftime('%H:%M:%S')
    emp = supabase.table('employees').select('*').eq('full_name',un).execute()
    if not emp.data: return redirect('/check-in')
    dept = emp.data[0].get('department','')
    branch = emp.data[0].get('branch','')
    ex = supabase.table('attendance').select('*').eq('full_name',un).eq('date',today).execute()
    if action == 'check_in':
        if ex.data and ex.data[0].get('check_in'): return redirect('/check-in')
        status = 'late' if now > '09:00:00' else 'present'
        d = {'check_in':now,'status':status,'check_in_lat':lat,'check_in_lng':lng,'check_in_location':loc}
        if ex.data: supabase.table('attendance').update(d).eq('full_name',un).eq('date',today).execute()
        else:
            d.update({'full_name':un,'department':dept,'branch':branch,'date':today})
            supabase.table('attendance').insert(d).execute()
    elif action == 'check_out':
        if ex.data and ex.data[0].get('check_in') and not ex.data[0].get('check_out'):
            supabase.table('attendance').update({'check_out':now}).eq('full_name',un).eq('date',today).execute()
    return redirect('/check-in')

# ─── ATTENDANCE HISTORY ─────────────────
@app.route('/attendance-history')
@login_required
def attendance_history():
    role = session.get('role')
    un = session.get('user')
    ub = session.get('branch','')
    period = request.args.get('period','month')
    today = date.today()
    if period == 'week': sd, ed = str(today-timedelta(days=7)), str(today)
    else: sd, ed = str(today.replace(day=1)), str(today)
    if role in ['admin','ceo']:
        r = supabase.table('attendance').select('*').gte('date',sd).lte('date',ed).order('date',desc=True).execute()
    elif role == 'manager':
        r = supabase.table('attendance').select('*').gte('date',sd).lte('date',ed).eq('branch',ub).order('date',desc=True).execute()
    else:
        r = supabase.table('attendance').select('*').gte('date',sd).lte('date',ed).eq('full_name',un).order('date',desc=True).execute()
    records = []
    for rec in (r.data or []):
        st = rec.get('status','present')
        records.append({'date':rec.get('date',''),'full_name':rec.get('full_name',''),'department':rec.get('department','—'),'check_in':rec.get('check_in','—'),'check_out':rec.get('check_out','—'),'status':st,'label':{'present':'Present','late':'Arrived Late'}.get(st,st)})
    return render_template('attendance_history.html', records=records, period=period, today=str(today))

# ─── SALES ──────────────────────────────
@app.route('/sales', methods=['GET','POST'])
@login_required
def sales_page():
    role = session.get('role')
    un = session.get('user')
    ub = session.get('branch','')
    today = str(date.today())
    if request.method == 'POST':
        try:
            amt = float(request.form.get('amount','0'))
            notes = request.form.get('notes','')
            if amt > 0:
                emp = supabase.table('employees').select('*').eq('full_name',un).execute()
                if emp.data:
                    supabase.table('sales').insert({'full_name':un,'department':emp.data[0].get('department',''),'branch':emp.data[0].get('branch',''),'date':today,'amount':amt,'notes':notes}).execute()
        except: pass
        return redirect('/sales')
    if role in ['admin','ceo']:
        sr = supabase.table('sales').select('*').eq('date',today).execute()
    elif role == 'manager':
        sr = supabase.table('sales').select('*').eq('date',today).eq('branch',ub).execute()
    else:
        sr = supabase.table('sales').select('*').eq('date',today).eq('full_name',un).execute()
    return render_template('sales.html', sales=sr.data or [], today=today)

# ─── PROFILE ────────────────────────────
@app.route('/profile')
@login_required
def profile():
    emp = supabase.table('employees').select('*').eq('full_name',session.get('user')).execute()
    return render_template('profile.html', employee=emp.data[0] if emp.data else {})

# ─── REPORTS ────────────────────────────
@app.route('/reports')
@login_required
def reports():
    if session.get('role') not in ['admin','ceo','manager']: return redirect('/')
    fd = request.args.get('from_date',str(date.today().replace(day=1)))
    td = request.args.get('to_date',str(date.today()))
    att = supabase.table('attendance').select('*').gte('date',fd).lte('date',td).order('date',desc=True).execute()
    records = []
    for rec in (att.data or []):
        st = rec.get('status','present')
        records.append({'date':rec.get('date',''),'full_name':rec.get('full_name',''),'department':rec.get('department','—'),'check_in':rec.get('check_in','—'),'check_out':rec.get('check_out','—'),'status':st,'label':{'present':'Present','late':'Arrived Late'}.get(st,st)})
    return render_template('reports.html', records=records, from_date=fd, to_date=td)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
