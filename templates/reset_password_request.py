{% extends 'base.html' %}
{% block title %}Reset Password{% endblock %}

{% block content %}
<div class="container mt-5 main-content" style="max-width: 500px;">
  <h3 class="text-center mb-4">Reset Your Password</h3>
  <form method="POST" action="{{ url_for('auth.reset_password_request') }}">
    <div class="mb-3">
      <label for="email" class="form-label">Email</label>
      <input type="email" class="form-control" id="email" name="email" required>
    </div>
    <button type="submit" class="btn btn-primary w-100">Send Reset Link</button>
  </form>
</div>
{% endblock %}
