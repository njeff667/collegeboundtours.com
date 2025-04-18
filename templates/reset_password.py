{% extends 'base.html' %}
{% block title %}Choose a New Password{% endblock %}

{% block content %}
<div class="container" style="max-width: 500px;">
  <h1 class="mb-4">Set a New Password</h1>
  <form method="POST" action="{{ url_for('auth.reset_password', token=token) }}">
    <div class="mb-3">
      <label for="password" class="form-label">New Password</label>
      <input type="password" class="form-control" id="password" name="password" required>
    </div>
    <button type="submit" class="btn btn-success w-100">Update Password</button>
  </form>
</div>
{% endblock %}
