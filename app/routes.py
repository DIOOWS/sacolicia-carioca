from decimal import Decimal, InvalidOperation
from functools import wraps
from flask import Blueprint, current_app, flash, redirect, render_template, request, send_from_directory, url_for
from flask_login import current_user, login_required, login_user, logout_user
from sqlalchemy import func, or_
from . import db
from .cloudinary_service import delete_product_image, upload_product_image, validate_product_image
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

def _product_form_values(product=None):
    try:
        raw_price = request.form.get("price", "").strip()
        normalized_price = raw_price.replace(".", "").replace(",", ".") if "," in raw_price else raw_price
        price = Decimal(normalized_price)
        stock = int(request.form.get("stock", "0"))
    except (InvalidOperation, ValueError):
        return None, "Informe preço e estoque válidos."
    values = {
        "name": request.form.get("name", "").strip(),
        "sku": request.form.get("sku", "").strip().upper(),
        "category": request.form.get("category", "").strip(),
        "unit": request.form.get("unit", "").strip(),
        "price": price,
        "stock": stock,
        "available": bool(request.form.get("available")),
    }
    if not all((values["name"], values["sku"], values["category"], values["unit"])):
        return None, "Preencha todos os campos obrigatórios."
    if price < 0 or stock < 0:
        return None, "Preço e estoque não podem ser negativos."
    duplicate = Product.query.filter(func.upper(Product.sku) == values["sku"])
    if product:
        duplicate = duplicate.filter(Product.id != product.id)
    if duplicate.first():
        return None, "Já existe um produto com esse SKU."
    return values, None

@admin_bp.route("/produtos")
@roles_required("admin", "gestor", "vendedor")
def products():
    query = request.args.get("q", "").strip()
    products_query = Product.query
    if query:
        like = f"%{query}%"
        products_query = products_query.filter(
            or_(Product.name.ilike(like), Product.sku.ilike(like), Product.category.ilike(like))
        )
    return render_template("admin/products.html", products=products_query.order_by(Product.name).all(), query=query)

@admin_bp.route("/produtos/novo", methods=["GET", "POST"])
@roles_required("admin", "gestor", "vendedor")
def product_new():
    if request.method == "POST":
        values, error = _product_form_values()
        image = request.files.get("image")
        error = error or validate_product_image(image)
        if error:
            flash(error, "danger")
            return render_template("admin/product_form.html", product=None)
        product = Product(**values)
        new_public_id = None
        try:
            if image and image.filename:
                product.image_url, new_public_id = upload_product_image(image)
                product.image_public_id = new_public_id
            db.session.add(product)
            db.session.commit()
        except Exception:
            db.session.rollback()
            if new_public_id:
                try: delete_product_image(new_public_id)
                except Exception: pass
            current_app.logger.exception("Falha ao cadastrar produto")
            flash("Não foi possível cadastrar o produto. Confira a configuração do Cloudinary.", "danger")
            return render_template("admin/product_form.html", product=None)
        flash("Produto cadastrado com sucesso.", "success")
        return redirect(url_for("admin.products"))
    return render_template("admin/product_form.html", product=None)

@admin_bp.route("/produtos/<int:product_id>/editar", methods=["GET", "POST"])
@roles_required("admin", "gestor", "vendedor")
def product_edit(product_id):
    product = db.get_or_404(Product, product_id)
    if request.method == "POST":
        values, error = _product_form_values(product)
        image = request.files.get("image")
        error = error or validate_product_image(image)
        if error:
            flash(error, "danger")
            return render_template("admin/product_form.html", product=product)
        old_public_id = product.image_public_id
        new_public_id = None
        try:
            if image and image.filename:
                product.image_url, new_public_id = upload_product_image(image)
                product.image_public_id = new_public_id
            for field, value in values.items():
                setattr(product, field, value)
            db.session.commit()
            if new_public_id and old_public_id:
                try: delete_product_image(old_public_id)
                except Exception: current_app.logger.exception("Falha ao excluir imagem antiga")
        except Exception:
            db.session.rollback()
            if new_public_id:
                try: delete_product_image(new_public_id)
                except Exception: pass
            current_app.logger.exception("Falha ao editar produto")
            flash("Não foi possível atualizar o produto.", "danger")
            return render_template("admin/product_form.html", product=product)
        flash("Produto atualizado com sucesso.", "success")
        return redirect(url_for("admin.products"))
    return render_template("admin/product_form.html", product=product)

@admin_bp.post("/produtos/<int:product_id>/disponibilidade")
@roles_required("admin", "gestor", "vendedor")
def product_availability(product_id):
    product = db.get_or_404(Product, product_id)
    product.available = not product.available
    db.session.commit()
    flash("Disponibilidade do produto atualizada.", "success")
    return redirect(url_for("admin.products"))

@cliente_bp.route("/")
@roles_required("cliente")
def dashboard():
    establishments = Establishment.query.filter_by(client_id=current_user.client_id, active=True).all()
    orders = Order.query.filter_by(client_id=current_user.client_id).order_by(Order.created_at.desc()).limit(6).all()
    total = db.session.query(func.coalesce(func.sum(Order.total), 0)).filter(Order.client_id==current_user.client_id, Order.status!="cancelado").scalar()
    return render_template("cliente/dashboard.html", establishments=establishments, orders=orders, total=total, products=Product.query.filter_by(available=True).all())
