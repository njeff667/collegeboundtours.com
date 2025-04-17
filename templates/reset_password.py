{% extends 'base.html' %}
{% block title %}Choose a New Password{% endblock %}

{% block content %}
<div class="container mt-5" style="max-width: 500px;">
  <h3 class="text-center mb-4">Set a New Password</h3>
  <form method="POST" action="{{ url_for('auth.reset_password', token=token) }}">
    <div class="mb-3">
      <label for="password" class="form-label">New Password</label>
      <input type="password" class="form-control" id="password" name="password" required>
    </div>
    <button type="submit" class="btn btn-success w-100">Update Password</button>
  </form>
</div>
{% endblock %}
