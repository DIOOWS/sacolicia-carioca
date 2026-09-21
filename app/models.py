from datetime import datetime, timezone
from flask_login import UserMixin
from werkzeug.security import check_password_hash, generate_password_hash
from . import db

def now(): return datetime.now(timezone.utc)

class Client(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    corporate_name = db.Column(db.String(160), nullable=False)
    trade_name = db.Column(db.String(120), nullable=False)
    document = db.Column(db.String(20), unique=True, nullable=False)
    email = db.Column(db.String(120))
    phone = db.Column(db.String(30))
    active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), default=now, nullable=False)
    establishments = db.relationship("Establishment", backref="client", lazy=True, cascade="all, delete-orphan")

class Establishment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    client_id = db.Column(db.Integer, db.ForeignKey("client.id"), nullable=False, index=True)
    name = db.Column(db.String(120), nullable=False)
    document = db.Column(db.String(20))
    phone = db.Column(db.String(30))
    street = db.Column(db.String(160), nullable=False)
    number = db.Column(db.String(20), nullable=False)
    complement = db.Column(db.String(80))
    neighborhood = db.Column(db.String(80), nullable=False)
    city = db.Column(db.String(80), nullable=False)
    state = db.Column(db.String(2), nullable=False)
    zip_code = db.Column(db.String(10), nullable=False)
    active = db.Column(db.Boolean, default=True, nullable=False)

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    username = db.Column(db.String(60), unique=True, nullable=False, index=True)
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), nullable=False, default="cliente")
    client_id = db.Column(db.Integer, db.ForeignKey("client.id"), index=True)
    active = db.Column(db.Boolean, default=True, nullable=False)
    must_change_password = db.Column(db.Boolean, default=True, nullable=False)
    client = db.relationship("Client", backref="users")
    def set_password(self, password): self.password_hash = generate_password_hash(password)
    def check_password(self, password): return check_password_hash(self.password_hash, password)
    @property
    def is_active(self): return self.active

class Product(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(140), nullable=False)
    sku = db.Column(db.String(40), unique=True, nullable=False)
    category = db.Column(db.String(80), nullable=False)
    unit = db.Column(db.String(60), nullable=False)
    price = db.Column(db.Numeric(10, 2), nullable=False)
    stock = db.Column(db.Integer, default=0, nullable=False)
    available = db.Column(db.Boolean, default=True, nullable=False)
    image_url = db.Column(db.String(500))
    image_public_id = db.Column(db.String(255))

class Order(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(20), unique=True, nullable=False)
    client_id = db.Column(db.Integer, db.ForeignKey("client.id"), nullable=False, index=True)
    establishment_id = db.Column(db.Integer, db.ForeignKey("establishment.id"), nullable=False, index=True)
    created_by_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    status = db.Column(db.String(30), default="aguardando_aprovacao", nullable=False, index=True)
    total = db.Column(db.Numeric(12, 2), default=0, nullable=False)
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime(timezone=True), default=now, nullable=False)
    client = db.relationship("Client")
    establishment = db.relationship("Establishment")
    items = db.relationship("OrderItem", backref="order", lazy=True, cascade="all, delete-orphan")

class OrderItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey("order.id"), nullable=False, index=True)
    product_id = db.Column(db.Integer, db.ForeignKey("product.id"), nullable=False)
    quantity = db.Column(db.Integer, nullable=False)
    unit_price = db.Column(db.Numeric(10, 2), nullable=False)
    product = db.relationship("Product")
