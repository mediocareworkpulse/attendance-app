{% if session.role in ['admin','ceo'] %}
    <a href="/admin" class="{% if request.path == '/admin' %}active{% endif %}">⚙️ Admin Panel</a>
    <a href="/approvals" class="{% if request.path == '/approvals' %}active{% endif %}">✅ Approvals</a>
    <a href="/employees" class="{% if request.path == '/employees' %}active{% endif %}">👥 Employees</a>
    <a href="/branches" class="{% if request.path == '/branches' %}active{% endif %}">🏢 Branches</a>
    <a href="/admin/sales" class="{% if request.path == '/admin/sales' %}active{% endif %}">💰 Manage Sales</a>
{% endif %}
