from functools import wraps
from flask import Blueprint, current_app, flash, redirect, render_template, request, send_from_directory, url_for
from flask_login import current_user, login_required, login_user, logout_user
from sqlalchemy import func
from . import db
from .models import Client, Establishment, Order, Product, User

auth_bp = Blueprint("auth", __name__)
main_bp = Blueprint("main", __name__)
admin_bp = Blueprint("admin", __name__)
cliente_bp = Blueprint("cliente", __name__)

def roles_required(*roles):
    def decorator(view):
        @wraps(view)
        @login_required
        def wrapped(*args, **kwargs):
            if current_user.role not in roles:
                flash("Você não possui permissão para acessar esta área.", "danger")
                return redirect(url_for("main.index"))
            return view(*args, **kwargs)
        return wrapped
    return decorator

@main_bp.route("/")
def index():
    if not current_user.is_authenticated: return redirect(url_for("auth.login"))
    if current_user.role in ("admin", "gestor", "vendedor"): return redirect(url_for("admin.dashboard"))
    return redirect(url_for("cliente.dashboard"))

@main_bp.route("/service-worker.js")
def service_worker():
    return send_from_directory(current_app.static_folder, "service-worker.js", mimetype="application/javascript")

@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated: return redirect(url_for("main.index"))
    if request.method == "POST":
        user = User.query.filter(func.lower(User.email) == request.form.get("email", "").strip().lower()).first()
        if user and user.active and user.check_password(request.form.get("password", "")):
            login_user(user, remember=bool(request.form.get("remember")))
            return redirect(url_for("main.index"))
        flash("E-mail ou senha inválidos.", "danger")
    return render_template("login.html")

@auth_bp.route("/logout", methods=["POST"])
@login_required
def logout():
    logout_user(); return redirect(url_for("auth.login"))

@admin_bp.route("/")
@roles_required("admin", "gestor", "vendedor")
def dashboard():
    stats = {"pending": Order.query.filter_by(status="aguardando_aprovacao").count(), "clients": Client.query.filter_by(active=True).count(), "establishments": Establishment.query.filter_by(active=True).count(), "products": Product.query.filter_by(available=True).count()}
    return render_template("admin/dashboard.html", stats=stats, orders=Order.query.order_by(Order.created_at.desc()).limit(6).all())

@cliente_bp.route("/")
@roles_required("cliente")
def dashboard():
    establishments = Establishment.query.filter_by(client_id=current_user.client_id, active=True).all()
    orders = Order.query.filter_by(client_id=current_user.client_id).order_by(Order.created_at.desc()).limit(6).all()
    total = db.session.query(func.coalesce(func.sum(Order.total), 0)).filter(Order.client_id==current_user.client_id, Order.status!="cancelado").scalar()
    return render_template("cliente/dashboard.html", establishments=establishments, orders=orders, total=total, products=Product.query.filter_by(available=True).all())
