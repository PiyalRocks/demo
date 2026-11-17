"""Restaurant Management System - Flask backend.
Models follow the class diagram: Customer, Admin, Category, FoodItem,
Cart, CartItem, Order, OrderItem. Data stores follow the DFD: D1 Users,
D2 Food Items, D3 Cart, D4 Orders.
"""
import secrets
from datetime import datetime
from functools import wraps

from flask import (Flask, render_template, request, redirect, url_for,
                   session, flash, abort)
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.config["SECRET_KEY"] = "change-this-secret-key"
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///restaurant.db"
db = SQLAlchemy(app)

ORDER_STATUSES = ["Pending", "Accepted", "Rejected", "Preparing",
                  "Out for Delivery", "Delivered"]

# ----------------------------- MODELS ---------------------------------
class Customer(db.Model):
    customer_id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    phone = db.Column(db.String(30), nullable=False)
    password = db.Column(db.String(255), nullable=False)
    cart = db.relationship("Cart", uselist=False, backref="customer")
    orders = db.relationship("Order", backref="customer")

    def set_password(self, raw):
        self.password = generate_password_hash(raw)

    def check_password(self, raw):
        return check_password_hash(self.password, raw)


class Admin(db.Model):
    admin_id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    password = db.Column(db.String(255), nullable=False)

    def check_password(self, raw):
        return check_password_hash(self.password, raw)


class Category(db.Model):
    category_id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(60), unique=True, nullable=False)
    foods = db.relationship("FoodItem", backref="category")


class FoodItem(db.Model):
    food_id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text, default="")
    price = db.Column(db.Float, nullable=False)
    image = db.Column(db.String(300), default="")
    is_available = db.Column(db.Boolean, default=True)
    category_id = db.Column(db.Integer, db.ForeignKey("category.category_id"))


class Cart(db.Model):
    cart_id = db.Column(db.Integer, primary_key=True)
    customer_id = db.Column(db.Integer, db.ForeignKey("customer.customer_id"),
                            unique=True, nullable=False)
    items = db.relationship("CartItem", backref="cart",
                            cascade="all, delete-orphan")

    def get_total(self):
        return sum(i.get_subtotal() for i in self.items)


class CartItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    cart_id = db.Column(db.Integer, db.ForeignKey("cart.cart_id"), nullable=False)
    food_id = db.Column(db.Integer, db.ForeignKey("food_item.food_id"), nullable=False)
    quantity = db.Column(db.Integer, default=1)
    food = db.relationship("FoodItem")

    def get_subtotal(self):
        return self.food.price * self.quantity


class Order(db.Model):
    order_id = db.Column(db.Integer, primary_key=True)
    order_code = db.Column(db.String(20), unique=True, nullable=False)  # unique order ID shown to user
    customer_id = db.Column(db.Integer, db.ForeignKey("customer.customer_id"), nullable=False)
    order_date = db.Column(db.DateTime, default=datetime.utcnow)
    total_amount = db.Column(db.Float, nullable=False)
    status = db.Column(db.String(30), default="Pending")
    delivery_address = db.Column(db.String(255), nullable=False)
    contact_name = db.Column(db.String(100))
    contact_phone = db.Column(db.String(30))
    items = db.relationship("OrderItem", backref="order", cascade="all, delete-orphan")


class OrderItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey("order.order_id"), nullable=False)
    food_id = db.Column(db.Integer, db.ForeignKey("food_item.food_id"), nullable=False)
    quantity = db.Column(db.Integer, nullable=False)
    unit_price = db.Column(db.Float, nullable=False)
    food = db.relationship("FoodItem")


# ---------------------------- HELPERS ---------------------------------
def current_customer():
    cid = session.get("customer_id")
    return db.session.get(Customer, cid) if cid else None


def customer_required(f):
    @wraps(f)
    def wrapper(*a, **kw):
        if not current_customer():
            flash("Please log in first.", "error")
            return redirect(url_for("login", next=request.path))
        return f(*a, **kw)
    return wrapper


def admin_required(f):
    @wraps(f)
    def wrapper(*a, **kw):
        if not session.get("admin_id"):
            flash("Admin login required.", "error")
            return redirect(url_for("admin_login"))
        return f(*a, **kw)
    return wrapper


def get_cart(customer):
    if not customer.cart:
        customer.cart = Cart(customer_id=customer.customer_id)
        db.session.commit()
    return customer.cart


@app.context_processor
def inject_globals():
    cust = current_customer()
    count = sum(i.quantity for i in cust.cart.items) if cust and cust.cart else 0
    return dict(me=cust, cart_count=count, is_admin=bool(session.get("admin_id")),
                statuses=ORDER_STATUSES)


# --------------------------- CUSTOMER ROUTES --------------------------
@app.route("/")
def menu():  # FR-02, FR-03
    q = request.args.get("q", "").strip()
    cat = request.args.get("category", type=int)
    min_p = request.args.get("min_price", type=float)
    max_p = request.args.get("max_price", type=float)
    query = FoodItem.query
    if q:
        query = query.filter(FoodItem.name.ilike(f"%{q}%"))
    if cat:
        query = query.filter_by(category_id=cat)
    if min_p is not None:
        query = query.filter(FoodItem.price >= min_p)
    if max_p is not None:
        query = query.filter(FoodItem.price <= max_p)
    foods = query.order_by(FoodItem.name).all()
    return render_template("menu.html", foods=foods,
                           categories=Category.query.all(),
                           q=q, cat=cat, min_p=min_p, max_p=max_p)


@app.route("/register", methods=["GET", "POST"])
def register():  # FR-01
    if request.method == "POST":
        name = request.form["name"].strip()
        email = request.form["email"].strip().lower()
        phone = request.form["phone"].strip()
        pw = request.form["password"]
        if not (name and email and phone and len(pw) >= 6):
            flash("Fill all fields (password min 6 characters).", "error")
        elif Customer.query.filter_by(email=email).first():
            flash("Email already registered.", "error")
        else:
            c = Customer(name=name, email=email, phone=phone)
            c.set_password(pw)
            db.session.add(c)
            db.session.commit()
            db.session.add(Cart(customer_id=c.customer_id))
            db.session.commit()
            flash("Account created. Please log in.", "success")
            return redirect(url_for("login"))
    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():  # FR-01
    if request.method == "POST":
        c = Customer.query.filter_by(email=request.form["email"].strip().lower()).first()
        if c and c.check_password(request.form["password"]):
            session.pop("admin_id", None)
            session["customer_id"] = c.customer_id
            flash(f"Welcome back, {c.name}!", "success")
            nxt = request.args.get("next")
            return redirect(nxt if nxt and nxt.startswith("/") else url_for("menu"))
        flash("Invalid email or password.", "error")
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.pop("customer_id", None)
    flash("Logged out.", "success")
    return redirect(url_for("menu"))


@app.route("/cart/add/<int:food_id>", methods=["POST"])
@customer_required
def cart_add(food_id):  # FR-04
    food = db.get_or_404(FoodItem, food_id)
    if not food.is_available:
        flash("Sorry, this item is unavailable.", "error")
        return redirect(request.referrer or url_for("menu"))
    cart = get_cart(current_customer())
    item = next((i for i in cart.items if i.food_id == food_id), None)
    if item:
        item.quantity += 1
    else:
        cart.items.append(CartItem(food_id=food_id, quantity=1))
    db.session.commit()
    flash(f"{food.name} added to cart.", "success")
    return redirect(request.referrer or url_for("menu"))


@app.route("/cart")
@customer_required
def cart_view():  # FR-05
    cart = get_cart(current_customer())
    return render_template("cart.html", cart=cart)


@app.route("/cart/update/<int:item_id>/<action>", methods=["POST"])
@customer_required
def cart_update(item_id, action):  # FR-05
    cart = get_cart(current_customer())
    item = CartItem.query.filter_by(id=item_id, cart_id=cart.cart_id).first_or_404()
    if action == "inc":
        item.quantity += 1
    elif action == "dec":
        item.quantity -= 1
        if item.quantity <= 0:
            db.session.delete(item)
    elif action == "remove":
        db.session.delete(item)
    db.session.commit()
    return redirect(url_for("cart_view"))


@app.route("/checkout", methods=["GET", "POST"])
@customer_required
def checkout():  # FR-06, FR-07
    cust = current_customer()
    cart = get_cart(cust)
    if not cart.items:
        flash("Your cart is empty.", "error")
        return redirect(url_for("menu"))
    if request.method == "POST":
        name = request.form["name"].strip()
        phone = request.form["phone"].strip()
        address = request.form["address"].strip()
        if not (name and phone and address):
            flash("Please fill in all delivery details.", "error")
            return render_template("checkout.html", cart=cart)
        unavailable = [i.food.name for i in cart.items if not i.food.is_available]
        if unavailable:
            flash("Unavailable now: " + ", ".join(unavailable) + ". Remove them to continue.", "error")
            return redirect(url_for("cart_view"))
        code = "ORD-" + secrets.token_hex(3).upper()
        while Order.query.filter_by(order_code=code).first():
            code = "ORD-" + secrets.token_hex(3).upper()
        order = Order(order_code=code, customer_id=cust.customer_id,
                      total_amount=cart.get_total(), delivery_address=address,
                      contact_name=name, contact_phone=phone)
        for i in cart.items:
            order.items.append(OrderItem(food_id=i.food_id, quantity=i.quantity,
                                         unit_price=i.food.price))
        db.session.add(order)
        for i in list(cart.items):   # clear cart (DFD: "Clear cart")
            db.session.delete(i)
        db.session.commit()
        return redirect(url_for("order_confirmation", code=code))
    return render_template("checkout.html", cart=cart)


@app.route("/order/<code>")
@customer_required
def order_confirmation(code):  # FR-07
    order = Order.query.filter_by(order_code=code,
                                  customer_id=current_customer().customer_id).first_or_404()
    return render_template("confirmation.html", order=order)


@app.route("/my-orders")
@customer_required
def my_orders():
    orders = (Order.query.filter_by(customer_id=current_customer().customer_id)
              .order_by(Order.order_date.desc()).all())
    return render_template("my_orders.html", orders=orders)


# ----------------------------- ADMIN ROUTES ---------------------------
@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():  # FR-08
    if request.method == "POST":
        a = Admin.query.filter_by(username=request.form["username"].strip()).first()
        if a and a.check_password(request.form["password"]):
            session.pop("customer_id", None)
            session["admin_id"] = a.admin_id
            return redirect(url_for("admin_orders"))
        flash("Invalid admin credentials.", "error")
    return render_template("admin/login.html")


@app.route("/admin/logout")
def admin_logout():
    session.pop("admin_id", None)
    return redirect(url_for("admin_login"))


@app.route("/admin")
@admin_required
def admin_orders():  # FR-10
    status = request.args.get("status")
    query = Order.query
    if status in ORDER_STATUSES:
        query = query.filter_by(status=status)
    orders = query.order_by(Order.order_date.desc()).all()
    return render_template("admin/orders.html", orders=orders, current=status)


@app.route("/admin/orders/<int:order_id>/status", methods=["POST"])
@admin_required
def admin_update_status(order_id):  # FR-10
    order = db.get_or_404(Order, order_id)
    new = request.form["status"]
    if new in ORDER_STATUSES:
        order.status = new
        db.session.commit()
        flash(f"{order.order_code} marked {new}.", "success")
    return redirect(url_for("admin_orders"))


@app.route("/admin/foods")
@admin_required
def admin_foods():  # FR-09
    return render_template("admin/foods.html",
                           foods=FoodItem.query.order_by(FoodItem.name).all())


def _save_food(food):
    food.name = request.form["name"].strip()
    food.description = request.form.get("description", "").strip()
    food.price = float(request.form["price"])
    food.image = request.form.get("image", "").strip()
    food.category_id = int(request.form["category_id"])
    food.is_available = "is_available" in request.form


@app.route("/admin/foods/new", methods=["GET", "POST"])
@admin_required
def admin_food_new():
    if request.method == "POST":
        try:
            food = FoodItem()
            _save_food(food)
            db.session.add(food)
            db.session.commit()
            flash("Food item added.", "success")
            return redirect(url_for("admin_foods"))
        except (ValueError, KeyError):
            flash("Invalid input.", "error")
    return render_template("admin/food_form.html", food=None, categories=Category.query.all())


@app.route("/admin/foods/<int:food_id>/edit", methods=["GET", "POST"])
@admin_required
def admin_food_edit(food_id):
    food = db.get_or_404(FoodItem, food_id)
    if request.method == "POST":
        try:
            _save_food(food)
            db.session.commit()
            flash("Food item updated.", "success")
            return redirect(url_for("admin_foods"))
        except (ValueError, KeyError):
            flash("Invalid input.", "error")
    return render_template("admin/food_form.html", food=food, categories=Category.query.all())


@app.route("/admin/foods/<int:food_id>/toggle", methods=["POST"])
@admin_required
def admin_food_toggle(food_id):
    food = db.get_or_404(FoodItem, food_id)
    food.is_available = not food.is_available
    db.session.commit()
    return redirect(url_for("admin_foods"))


@app.route("/admin/foods/<int:food_id>/delete", methods=["POST"])
@admin_required
def admin_food_delete(food_id):
    food = db.get_or_404(FoodItem, food_id)
    if OrderItem.query.filter_by(food_id=food_id).first():
        food.is_available = False   # keep order history intact
        db.session.commit()
        flash("Item is in past orders, so it was marked unavailable instead of deleted.", "error")
    else:
        CartItem.query.filter_by(food_id=food_id).delete()
        db.session.delete(food)
        db.session.commit()
        flash("Food item deleted.", "success")
    return redirect(url_for("admin_foods"))


# ------------------------------- SEED ---------------------------------
def seed():
    if not Admin.query.first():
        db.session.add(Admin(username="admin", password=generate_password_hash("admin123")))
    if not Category.query.first():
        cats = {n: Category(name=n) for n in ["Burgers", "Pizza", "Drinks", "Desserts"]}
        db.session.add_all(cats.values())
        db.session.flush()
        data = [
            ("Classic Beef Burger", "Juicy beef patty, cheese, lettuce, tomato.", 8.50, "Burgers"),
            ("Chicken Burger", "Crispy chicken fillet with mayo.", 7.25, "Burgers"),
            ("Margherita Pizza", "Tomato sauce, mozzarella, fresh basil.", 11.00, "Pizza"),
            ("Pepperoni Pizza", "Loaded with pepperoni and cheese.", 13.50, "Pizza"),
            ("Cola", "Chilled 330ml can.", 1.50, "Drinks"),
            ("Fresh Lemonade", "Freshly squeezed with mint.", 2.75, "Drinks"),
            ("Chocolate Brownie", "Warm brownie with chocolate sauce.", 4.25, "Desserts"),
            ("Vanilla Ice Cream", "Two scoops of creamy vanilla.", 3.50, "Desserts"),
        ]
        for n, d, p, c in data:
            db.session.add(FoodItem(name=n, description=d, price=p,
                                    category_id=cats[c].category_id))
    db.session.commit()


with app.app_context():
    db.create_all()
    seed()

if __name__ == "__main__":
    app.run(debug=True)
