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

def _is_email(value):
    return bool(value and "@" in value and "." in value.rsplit("@", 1)[-1])

def _client_form_values(client=None):
    values = {
        "corporate_name": request.form.get("corporate_name", "").strip(),
        "trade_name": request.form.get("trade_name", "").strip(),
        "document": request.form.get("document", "").strip(),
        "email": request.form.get("email", "").strip().lower() or None,
        "phone": request.form.get("phone", "").strip() or None,
        "active": bool(request.form.get("active")),
    }
    if not all((values["corporate_name"], values["trade_name"], values["document"])):
        return None, "Preencha razão social, nome fantasia e CPF/CNPJ."
    if values["email"] and not _is_email(values["email"]):
        return None, "Informe um e-mail válido."
    duplicate = Client.query.filter(func.lower(Client.document) == values["document"].lower())
    if client:
        duplicate = duplicate.filter(Client.id != client.id)
    if duplicate.first():
        return None, "Já existe um cliente com esse CPF/CNPJ."
    return values, None

@admin_bp.route("/clientes")
@roles_required("admin", "gestor", "vendedor")
def clients():
    query = request.args.get("q", "").strip()
    clients_query = Client.query
    if query:
        like = f"%{query}%"
        clients_query = clients_query.filter(or_(Client.trade_name.ilike(like), Client.corporate_name.ilike(like), Client.document.ilike(like)))
    return render_template("admin/clients.html", clients=clients_query.order_by(Client.trade_name).all(), query=query)

@admin_bp.route("/clientes/novo", methods=["GET", "POST"])
@roles_required("admin", "gestor", "vendedor")
def client_new():
    if request.method == "POST":
        values, error = _client_form_values()
        if error:
            flash(error, "danger")
            return render_template("admin/client_form.html", client=None)
        client = Client(**values)
        db.session.add(client); db.session.commit()
        flash("Cliente cadastrado. Agora adicione os estabelecimentos e o acesso.", "success")
        return redirect(url_for("admin.establishment_new", client_id=client.id))
    return render_template("admin/client_form.html", client=None)

@admin_bp.route("/clientes/<int:client_id>/editar", methods=["GET", "POST"])
@roles_required("admin", "gestor", "vendedor")
def client_edit(client_id):
    client = db.get_or_404(Client, client_id)
    if request.method == "POST":
        values, error = _client_form_values(client)
        if error:
            flash(error, "danger")
            return render_template("admin/client_form.html", client=client)
        for field, value in values.items(): setattr(client, field, value)
        db.session.commit(); flash("Cliente atualizado com sucesso.", "success")
        return redirect(url_for("admin.clients"))
    return render_template("admin/client_form.html", client=client)

@admin_bp.post("/clientes/<int:client_id>/situacao")
@roles_required("admin", "gestor")
def client_status(client_id):
    client = db.get_or_404(Client, client_id)
    client.active = not client.active
    if not client.active:
        Establishment.query.filter_by(client_id=client.id).update({"active": False})
        User.query.filter_by(client_id=client.id).update({"active": False})
    db.session.commit(); flash("Situação do cliente atualizada.", "success")
    return redirect(url_for("admin.clients"))

def _establishment_form_values():
    try: client_id = int(request.form.get("client_id", ""))
    except ValueError: return None, "Selecione um cliente."
    client = db.session.get(Client, client_id)
    values = {
        "client_id": client_id,
        "name": request.form.get("name", "").strip(),
        "document": request.form.get("document", "").strip() or None,
        "phone": request.form.get("phone", "").strip() or None,
        "street": request.form.get("street", "").strip(),
        "number": request.form.get("number", "").strip(),
        "complement": request.form.get("complement", "").strip() or None,
        "neighborhood": request.form.get("neighborhood", "").strip(),
        "city": request.form.get("city", "").strip(),
        "state": request.form.get("state", "").strip().upper(),
        "zip_code": request.form.get("zip_code", "").strip(),
        "active": bool(request.form.get("active")),
    }
    required = (client, values["name"], values["street"], values["number"], values["neighborhood"], values["city"], values["state"], values["zip_code"])
    if not all(required): return None, "Preencha o cliente e todo o endereço obrigatório."
    if len(values["state"]) != 2: return None, "Informe a UF com duas letras."
    return values, None

@admin_bp.route("/estabelecimentos")
@roles_required("admin", "gestor", "vendedor")
def establishments():
    query = request.args.get("q", "").strip()
    items = Establishment.query.join(Client)
    if query:
        like = f"%{query}%"
        items = items.filter(or_(Establishment.name.ilike(like), Establishment.city.ilike(like), Client.trade_name.ilike(like)))
    return render_template("admin/establishments.html", establishments=items.order_by(Client.trade_name, Establishment.name).all(), query=query)

@admin_bp.route("/estabelecimentos/novo", methods=["GET", "POST"])
@roles_required("admin", "gestor", "vendedor")
def establishment_new():
    selected_client_id = request.args.get("client_id", type=int)
    if request.method == "POST":
        values, error = _establishment_form_values()
        if error:
            flash(error, "danger")
            return render_template("admin/establishment_form.html", establishment=None, clients=Client.query.order_by(Client.trade_name).all(), selected_client_id=selected_client_id)
        establishment = Establishment(**values); db.session.add(establishment); db.session.commit()
        flash("Estabelecimento cadastrado com sucesso.", "success")
        return redirect(url_for("admin.establishments"))
    return render_template("admin/establishment_form.html", establishment=None, clients=Client.query.order_by(Client.trade_name).all(), selected_client_id=selected_client_id)

@admin_bp.route("/estabelecimentos/<int:establishment_id>/editar", methods=["GET", "POST"])
@roles_required("admin", "gestor", "vendedor")
def establishment_edit(establishment_id):
    establishment = db.get_or_404(Establishment, establishment_id)
    if request.method == "POST":
        values, error = _establishment_form_values()
        if error:
            flash(error, "danger")
            return render_template("admin/establishment_form.html", establishment=establishment, clients=Client.query.order_by(Client.trade_name).all(), selected_client_id=None)
        for field, value in values.items(): setattr(establishment, field, value)
        db.session.commit(); flash("Estabelecimento atualizado com sucesso.", "success")
        return redirect(url_for("admin.establishments"))
    return render_template("admin/establishment_form.html", establishment=establishment, clients=Client.query.order_by(Client.trade_name).all(), selected_client_id=None)

@admin_bp.post("/estabelecimentos/<int:establishment_id>/situacao")
@roles_required("admin", "gestor", "vendedor")
def establishment_status(establishment_id):
    establishment = db.get_or_404(Establishment, establishment_id)
    if not establishment.active and not establishment.client.active:
        flash("Ative o cliente antes de ativar o estabelecimento.", "danger")
    else:
        establishment.active = not establishment.active; db.session.commit()
        flash("Situação do estabelecimento atualizada.", "success")
    return redirect(url_for("admin.establishments"))

def _user_form_values(user=None):
    name = request.form.get("name", "").strip()
    email = request.form.get("email", "").strip().lower()
    role = request.form.get("role", "cliente")
    password = request.form.get("password", "")
    client_id_raw = request.form.get("client_id", "").strip()
    if not name or not _is_email(email): return None, "Informe nome e e-mail válidos."
    if role not in ("admin", "gestor", "vendedor", "cliente"): return None, "Perfil inválido."
    if not user and len(password) < 8: return None, "A senha provisória deve ter pelo menos 8 caracteres."
    if password and len(password) < 8: return None, "A nova senha deve ter pelo menos 8 caracteres."
    duplicate = User.query.filter(func.lower(User.email) == email)
    if user: duplicate = duplicate.filter(User.id != user.id)
    if duplicate.first(): return None, "Já existe um usuário com esse e-mail."
    client_id = int(client_id_raw) if client_id_raw.isdigit() else None
    if role == "cliente" and not client_id: return None, "Vincule o acesso a um cliente."
    if client_id and not db.session.get(Client, client_id): return None, "Cliente selecionado não existe."
    return {"name": name, "email": email, "role": role, "client_id": client_id if role == "cliente" else None, "active": bool(request.form.get("active")), "password": password}, None

@admin_bp.route("/usuarios")
@roles_required("admin", "gestor")
def users():
    query = request.args.get("q", "").strip(); items = User.query
    if query:
        like = f"%{query}%"; items = items.filter(or_(User.name.ilike(like), User.email.ilike(like), User.role.ilike(like)))
    return render_template("admin/users.html", users=items.order_by(User.name).all(), query=query)

@admin_bp.route("/usuarios/novo", methods=["GET", "POST"])
@roles_required("admin", "gestor")
def user_new():
    if request.method == "POST":
        values, error = _user_form_values()
        if error:
            flash(error, "danger"); return render_template("admin/user_form.html", user=None, clients=Client.query.filter_by(active=True).order_by(Client.trade_name).all())
        password = values.pop("password"); user = User(**values, must_change_password=True); user.set_password(password)
        db.session.add(user); db.session.commit(); flash("Acesso criado com sucesso.", "success")
        return redirect(url_for("admin.users"))
    return render_template("admin/user_form.html", user=None, clients=Client.query.filter_by(active=True).order_by(Client.trade_name).all())

@admin_bp.route("/usuarios/<int:user_id>/editar", methods=["GET", "POST"])
@roles_required("admin", "gestor")
def user_edit(user_id):
    user = db.get_or_404(User, user_id)
    if request.method == "POST":
        values, error = _user_form_values(user)
        if error:
            flash(error, "danger"); return render_template("admin/user_form.html", user=user, clients=Client.query.filter_by(active=True).order_by(Client.trade_name).all())
        password = values.pop("password")
        for field, value in values.items(): setattr(user, field, value)
        if password: user.set_password(password); user.must_change_password = True
        db.session.commit(); flash("Usuário atualizado com sucesso.", "success")
        return redirect(url_for("admin.users"))
    return render_template("admin/user_form.html", user=user, clients=Client.query.filter_by(active=True).order_by(Client.trade_name).all())

@admin_bp.post("/usuarios/<int:user_id>/situacao")
@roles_required("admin", "gestor")
def user_status(user_id):
    user = db.get_or_404(User, user_id)
    if user.id == current_user.id:
        flash("Você não pode desativar o próprio acesso.", "danger")
    elif not user.active and user.client and not user.client.active:
        flash("Ative o cliente antes de ativar esse usuário.", "danger")
    else:
        user.active = not user.active; db.session.commit(); flash("Situação do usuário atualizada.", "success")
    return redirect(url_for("admin.users"))

@cliente_bp.route("/")
@roles_required("cliente")
def dashboard():
    establishments = Establishment.query.filter_by(client_id=current_user.client_id, active=True).all()
    orders = Order.query.filter_by(client_id=current_user.client_id).order_by(Order.created_at.desc()).limit(6).all()
    total = db.session.query(func.coalesce(func.sum(Order.total), 0)).filter(Order.client_id==current_user.client_id, Order.status!="cancelado").scalar()
    return render_template("cliente/dashboard.html", establishments=establishments, orders=orders, total=total, products=Product.query.filter_by(available=True).all())
