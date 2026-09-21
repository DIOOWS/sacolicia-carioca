import os
from sqlalchemy import func, inspect, or_, text
from app import create_app, db
from app.models import Client, Establishment, Product, User

app = create_app()
with app.app_context():
    db.create_all()
    product_columns = {column["name"] for column in inspect(db.engine).get_columns("product")}
    if "image_url" not in product_columns:
        db.session.execute(text("ALTER TABLE product ADD COLUMN image_url VARCHAR(500)"))
    if "image_public_id" not in product_columns:
        db.session.execute(text("ALTER TABLE product ADD COLUMN image_public_id VARCHAR(255)"))
    user_columns = {column["name"] for column in inspect(db.engine).get_columns("user")}
    if "username" not in user_columns:
        db.session.execute(text("ALTER TABLE \"user\" ADD COLUMN username VARCHAR(60)"))
        db.session.execute(text("UPDATE \"user\" SET username = 'usuario' || id WHERE username IS NULL"))
        db.session.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ix_user_username ON \"user\" (username)"))
    db.session.commit()
    admin_email = os.getenv("ADMIN_EMAIL")
    admin_username = os.getenv("ADMIN_USERNAME", "admin").strip().lower()
    admin_password = os.getenv("ADMIN_PASSWORD")
    customer_email = os.getenv("DEMO_CLIENT_EMAIL")
    customer_username = os.getenv("DEMO_CLIENT_USERNAME", "cliente").strip().lower()
    customer_password = os.getenv("DEMO_CLIENT_PASSWORD")
    client = Client.query.first()
    if not client:
        client = Client(corporate_name="Rede Bom Preço LTDA", trade_name="Mercadinho Bom Preço", document="00.000.000/0001-00", email="cliente@exemplo.com", phone="(21) 99999-0000")
        db.session.add(client); db.session.flush()
        for name, bairro in [("Bom Preço — Centro","Centro"),("Bom Preço — Tijuca","Tijuca"),("Bom Preço — Méier","Méier")]:
            db.session.add(Establishment(client_id=client.id,name=name,street="Rua de Teste",number="100",neighborhood=bairro,city="Rio de Janeiro",state="RJ",zip_code="20000-000"))
    if admin_email and admin_password:
        admin = User.query.filter(or_(func.lower(User.email) == admin_email.lower(), User.role == "admin")).first()
        if not admin: admin=User(name="Administrador",username=admin_username,email=admin_email.lower(),role="admin",must_change_password=True); db.session.add(admin)
        admin.username=admin_username; admin.email=admin_email.lower(); admin.active=True; admin.set_password(admin_password)
    if customer_email and customer_password:
        customer = User.query.filter(func.lower(User.email) == customer_email.lower()).first()
        if not customer: customer=User(name="Cliente Demonstração",username=customer_username,email=customer_email.lower(),role="cliente",client_id=client.id,must_change_password=True); db.session.add(customer)
        customer.username=customer_username; customer.active=True; customer.set_password(customer_password)
    if not Product.query.first():
        for item in [("Sacolé Gourmet Morango","SC-MOR","Frutas","Caixa c/ 20",70,30),("Sacolé Gourmet Maracujá","SC-MAR","Frutas","Caixa c/ 20",70,24),("Sacolé Gourmet Chocolate","SC-CHO","Cremosos","Caixa c/ 20",80,18),("Sacolé Gourmet Paçoca","SC-PAC","Cremosos","Caixa c/ 20",80,12)]:
            db.session.add(Product(name=item[0],sku=item[1],category=item[2],unit=item[3],price=item[4],stock=item[5]))
    db.session.commit()
    print("Base atualizada. Os acessos são definidos somente por variáveis de ambiente.")
