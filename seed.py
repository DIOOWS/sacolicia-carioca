import os
from app import create_app, db
from app.models import Client, Establishment, Product, User

app = create_app()
with app.app_context():
    db.create_all()
    admin_email = os.getenv("ADMIN_EMAIL")
    admin_password = os.getenv("ADMIN_PASSWORD")
    customer_email = os.getenv("DEMO_CLIENT_EMAIL")
    customer_password = os.getenv("DEMO_CLIENT_PASSWORD")
    if not Client.query.first():
        client = Client(corporate_name="Rede Bom Preço LTDA", trade_name="Mercadinho Bom Preço", document="00.000.000/0001-00", email="cliente@exemplo.com", phone="(21) 99999-0000")
        db.session.add(client); db.session.flush()
        for name, bairro in [("Bom Preço — Centro","Centro"),("Bom Preço — Tijuca","Tijuca"),("Bom Preço — Méier","Méier")]:
            db.session.add(Establishment(client_id=client.id,name=name,street="Rua de Teste",number="100",neighborhood=bairro,city="Rio de Janeiro",state="RJ",zip_code="20000-000"))
        if admin_email and admin_password:
            admin=User(name="Administrador",email=admin_email,role="admin",must_change_password=True); admin.set_password(admin_password); db.session.add(admin)
        if customer_email and customer_password:
            customer=User(name="Cliente Demonstração",email=customer_email,role="cliente",client_id=client.id,must_change_password=True); customer.set_password(customer_password); db.session.add(customer)
        for item in [("Sacolé Gourmet Morango","SC-MOR","Frutas","Caixa c/ 20",70,30),("Sacolé Gourmet Maracujá","SC-MAR","Frutas","Caixa c/ 20",70,24),("Sacolé Gourmet Chocolate","SC-CHO","Cremosos","Caixa c/ 20",80,18),("Sacolé Gourmet Paçoca","SC-PAC","Cremosos","Caixa c/ 20",80,12)]:
            db.session.add(Product(name=item[0],sku=item[1],category=item[2],unit=item[3],price=item[4],stock=item[5]))
        db.session.commit()
        print("Base criada. Os acessos são definidos somente por variáveis de ambiente.")
    else: print("A base já foi criada.")
