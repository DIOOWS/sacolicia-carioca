from datetime import datetime, time, timezone
from decimal import Decimal, InvalidOperation
from functools import wraps
from io import BytesIO
from secrets import token_hex
from flask import Blueprint, current_app, flash, redirect, render_template, request, send_file, send_from_directory, session, url_for
from flask_login import current_user, login_required, login_user, logout_user
from openpyxl import Workbook
from sqlalchemy import func, or_
from . import db
from .cloudinary_service import delete_product_image, upload_product_image, validate_product_image
from .models import Client, Establishment, Order, OrderItem, Product, User

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
        user = User.query.filter(func.lower(User.username) == request.form.get("username", "").strip().lower()).first()
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
    username = request.form.get("username", "").strip().lower()
    email = request.form.get("email", "").strip().lower()
    role = request.form.get("role", "cliente")
    password = request.form.get("password", "")
    client_id_raw = request.form.get("client_id", "").strip()
    if not name or len(username) < 3 or not username.replace("_", "").replace("-", "").isalnum() or not _is_email(email): return None, "Informe nome, usuário e e-mail válidos."
    if role not in ("admin", "gestor", "vendedor", "cliente"): return None, "Perfil inválido."
    if not user and len(password) < 8: return None, "A senha provisória deve ter pelo menos 8 caracteres."
    if password and len(password) < 8: return None, "A nova senha deve ter pelo menos 8 caracteres."
    duplicate = User.query.filter(func.lower(User.email) == email)
    if user: duplicate = duplicate.filter(User.id != user.id)
    if duplicate.first(): return None, "Já existe um usuário com esse e-mail."
    duplicate_username = User.query.filter(func.lower(User.username) == username)
    if user: duplicate_username = duplicate_username.filter(User.id != user.id)
    if duplicate_username.first(): return None, "Esse nome de usuário já está em uso."
    client_id = int(client_id_raw) if client_id_raw.isdigit() else None
    if role == "cliente" and not client_id: return None, "Vincule o acesso a um cliente."
    if client_id and not db.session.get(Client, client_id): return None, "Cliente selecionado não existe."
    return {"name": name, "username": username, "email": email, "role": role, "client_id": client_id if role == "cliente" else None, "active": bool(request.form.get("active")), "password": password}, None

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

def _order_query(client_id=None):
    query = Order.query
    if client_id: query = query.filter(Order.client_id == client_id)
    date_from = request.args.get("date_from", "").strip()
    date_to = request.args.get("date_to", "").strip()
    establishment_id = request.args.get("establishment_id", type=int)
    selected_client = request.args.get("client_id", type=int)
    status = request.args.get("status", "").strip()
    if selected_client and not client_id: query = query.filter(Order.client_id == selected_client)
    if establishment_id: query = query.filter(Order.establishment_id == establishment_id)
    if status: query = query.filter(Order.status == status)
    try:
        if date_from: query = query.filter(Order.created_at >= datetime.combine(datetime.strptime(date_from, "%Y-%m-%d").date(), time.min, tzinfo=timezone.utc))
        if date_to: query = query.filter(Order.created_at <= datetime.combine(datetime.strptime(date_to, "%Y-%m-%d").date(), time.max, tzinfo=timezone.utc))
    except ValueError: flash("Período inválido.", "danger")
    return query

@admin_bp.route("/pedidos")
@roles_required("admin", "gestor", "vendedor")
def orders():
    items = _order_query().order_by(Order.created_at.desc()).all()
    return render_template("admin/orders.html", orders=items)

@admin_bp.route("/pedidos/<int:order_id>")
@roles_required("admin", "gestor", "vendedor")
def order_detail(order_id):
    return render_template("admin/order_detail.html", order=db.get_or_404(Order, order_id))

@admin_bp.post("/pedidos/<int:order_id>/status")
@roles_required("admin", "gestor", "vendedor")
def order_status(order_id):
    order = db.get_or_404(Order, order_id)
    action = request.form.get("action")
    if order.status != "aguardando_aprovacao":
        flash("Esse pedido já foi analisado.", "danger")
    elif action == "aprovar":
        unavailable = [item for item in order.items if item.product.stock < item.quantity]
        if unavailable:
            flash("Estoque insuficiente para: " + ", ".join(item.product.name for item in unavailable), "danger")
        else:
            for item in order.items: item.product.stock -= item.quantity
            order.status = "aprovado"; db.session.commit(); flash("Pedido aprovado e estoque atualizado.", "success")
    elif action in ("recusar", "cancelar"):
        order.status = "recusado" if action == "recusar" else "cancelado"; db.session.commit(); flash("Pedido atualizado.", "success")
    else: flash("Ação inválida.", "danger")
    return redirect(url_for("admin.order_detail", order_id=order.id))

def _report_context(client_id=None):
    orders = _order_query(client_id).order_by(Order.created_at.desc()).all()
    valid = [order for order in orders if order.status != "cancelado"]
    total = sum((order.total for order in valid), Decimal("0"))
    ranking = {}
    for order in valid:
        for item in order.items:
            ranking[item.product.name] = ranking.get(item.product.name, 0) + item.quantity
    ranking = sorted(ranking.items(), key=lambda row: row[1], reverse=True)[:10]
    return orders, total, ranking

def _orders_excel(orders, filename):
    workbook = Workbook(); sheet = workbook.active; sheet.title = "Pedidos"
    sheet.append(["Pedido", "Data", "Cliente", "Estabelecimento", "Status", "Total"])
    for order in orders: sheet.append([order.code, order.created_at.strftime("%d/%m/%Y"), order.client.trade_name, order.establishment.name, order.status.replace("_", " ").title(), float(order.total)])
    details = workbook.create_sheet("Itens")
    details.append(["Pedido", "Produto", "SKU", "Quantidade", "Preço unitário", "Subtotal"])
    for order in orders:
        for item in order.items: details.append([order.code, item.product.name, item.product.sku, item.quantity, float(item.unit_price), float(item.unit_price * item.quantity)])
    output = BytesIO(); workbook.save(output); output.seek(0)
    return send_file(output, as_attachment=True, download_name=filename, mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

@admin_bp.route("/relatorios")
@roles_required("admin", "gestor", "vendedor")
def reports():
    orders, total, ranking = _report_context()
    return render_template("admin/reports.html", orders=orders, total=total, ranking=ranking, clients=Client.query.order_by(Client.trade_name).all(), establishments=Establishment.query.order_by(Establishment.name).all())

@admin_bp.route("/relatorios/excel")
@roles_required("admin", "gestor", "vendedor")
def reports_excel():
    return _orders_excel(_order_query().order_by(Order.created_at.desc()).all(), "relatorio_sacolicia.xlsx")

@cliente_bp.route("/")
@roles_required("cliente")
def dashboard():
    establishments = Establishment.query.filter_by(client_id=current_user.client_id, active=True).all()
    orders = Order.query.filter_by(client_id=current_user.client_id).order_by(Order.created_at.desc()).limit(6).all()
    order_count = Order.query.filter_by(client_id=current_user.client_id).count()
    total = db.session.query(func.coalesce(func.sum(Order.total), 0)).filter(Order.client_id==current_user.client_id, Order.status!="cancelado").scalar()
    cart_count = sum(session.get("cart", {}).values())
    return render_template("cliente/dashboard.html", establishments=establishments, orders=orders, order_count=order_count, total=total, cart_count=cart_count, products=Product.query.filter_by(available=True).all())

@cliente_bp.post("/carrinho/adicionar/<int:product_id>")
@roles_required("cliente")
def cart_add(product_id):
    product = db.get_or_404(Product, product_id)
    if not product.available or product.stock < 1:
        flash("Produto indisponível.", "danger"); return redirect(url_for("cliente.dashboard"))
    try: quantity = max(1, int(request.form.get("quantity", 1)))
    except ValueError: quantity = 1
    cart = session.get("cart", {}); key = str(product.id)
    cart[key] = min(product.stock, cart.get(key, 0) + quantity); session["cart"] = cart
    flash("Produto adicionado ao carrinho.", "success")
    return redirect(url_for("cliente.dashboard", _anchor="catalogo"))

def _cart_items():
    cart = session.get("cart", {}); products = Product.query.filter(Product.id.in_([int(key) for key in cart] or [0])).all()
    items = [{"product": product, "quantity": cart.get(str(product.id), 0), "subtotal": product.price * cart.get(str(product.id), 0)} for product in products]
    return items, sum((item["subtotal"] for item in items), Decimal("0"))

@cliente_bp.route("/carrinho")
@roles_required("cliente")
def cart():
    items, total = _cart_items()
    establishments = Establishment.query.filter_by(client_id=current_user.client_id, active=True).order_by(Establishment.name).all()
    return render_template("cliente/cart.html", items=items, total=total, establishments=establishments)

@cliente_bp.post("/carrinho/atualizar")
@roles_required("cliente")
def cart_update():
    cart = session.get("cart", {})
    for key in list(cart):
        product = db.session.get(Product, int(key))
        try: quantity = int(request.form.get(f"quantity_{key}", 0))
        except ValueError: quantity = 0
        if not product or quantity <= 0: cart.pop(key, None)
        else: cart[key] = min(quantity, product.stock)
    session["cart"] = cart; flash("Carrinho atualizado.", "success")
    return redirect(url_for("cliente.cart"))

@cliente_bp.post("/pedido/enviar")
@roles_required("cliente")
def order_submit():
    items, total = _cart_items()
    establishment = db.session.get(Establishment, request.form.get("establishment_id", type=int))
    if not items: flash("Seu carrinho está vazio.", "danger"); return redirect(url_for("cliente.cart"))
    if not establishment or establishment.client_id != current_user.client_id or not establishment.active:
        flash("Selecione um estabelecimento válido.", "danger"); return redirect(url_for("cliente.cart"))
    if any(item["quantity"] > item["product"].stock for item in items):
        flash("Um produto não possui mais a quantidade solicitada.", "danger"); return redirect(url_for("cliente.cart"))
    order = Order(code=f"PED-{datetime.now().strftime('%y%m%d')}-{token_hex(2).upper()}", client_id=current_user.client_id, establishment_id=establishment.id, created_by_id=current_user.id, total=total, notes=request.form.get("notes", "").strip() or None)
    db.session.add(order); db.session.flush()
    for item in items: db.session.add(OrderItem(order_id=order.id, product_id=item["product"].id, quantity=item["quantity"], unit_price=item["product"].price))
    db.session.commit(); session.pop("cart", None); flash(f"Pedido {order.code} enviado para aprovação.", "success")
    return redirect(url_for("cliente.order_detail", order_id=order.id))

@cliente_bp.route("/pedidos/<int:order_id>")
@roles_required("cliente")
def order_detail(order_id):
    order = Order.query.filter_by(id=order_id, client_id=current_user.client_id).first_or_404()
    return render_template("cliente/order_detail.html", order=order)

@cliente_bp.route("/relatorios")
@roles_required("cliente")
def reports():
    orders, total, ranking = _report_context(current_user.client_id)
    establishments = Establishment.query.filter_by(client_id=current_user.client_id).order_by(Establishment.name).all()
    return render_template("cliente/reports.html", orders=orders, total=total, ranking=ranking, establishments=establishments)

@cliente_bp.route("/relatorios/excel")
@roles_required("cliente")
def reports_excel():
    return _orders_excel(_order_query(current_user.client_id).order_by(Order.created_at.desc()).all(), "minhas_compras_sacolicia.xlsx")
