from flask import Flask, app, render_template, request, redirect, url_for, session, flash
import firebase_admin
from functools import wraps
from firebase_admin import credentials,firestore
from matplotlib.pylab import sort
import matplotlib.pyplot as plt
import io
import base64
from datetime import timedelta, datetime
import os
import json
import os
from firebase_admin import credentials, firestore, initialize_app


#creates a Flask application instance and assigns it to the variable 'app'. This instance will be used to define routes and handle requests in the web application.
app = Flask(__name__)
# for session
app.secret_key = os.environ.get('FLASK_SECRET_KEY', 'fallback-secret')
app.permanent_session_lifetime = timedelta(minutes=10)

#loads the service account key JSON file and initializes the Firebase Admin SDK with the provided credentials. This allows the application to interact with Firebase services, such as Firestore.
cred_dict = json.loads(os.environ['FIREBASE_KEY'])
cred = credentials.Certificate(cred_dict)
firebase_admin.initialize_app(cred)
db = firestore.client()

# for login page
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'username' not in session:
            return redirect(url_for('Login'))
        return f(*args, **kwargs)
    return decorated_function

@app.route('/')
def home():
    if 'username' in session:
        return redirect(url_for('dashboard'))
    return redirect(url_for('Login'))
    
@app.route('/register', methods=['GET', 'POST'])
def register():
    error = None
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        
        user_ref = db.collection('users').document(username)
        if user_ref.get().exists:
            error = "Username already exists. Please try another username."
            return render_template('register.html', error=error)
        
        user_ref.set({
            'username': username,
            'password': password})
        flash('Registration successful! Please login.', 'success')
        return redirect(url_for('Login'))
    
    return render_template('register.html', error=error)

@app.route('/ForgotPassword', methods=['GET', 'POST'])
def ForgotPassword():
    error = None
    if request.method == 'POST':
        username = request.form['username']
        new_password = request.form['password']
        user_ref = db.collection('users').document(username)
        user_doc = user_ref.get()

        if user_doc.exists:
            # Update the password in the database
            user_ref.update({'password': new_password})
            flash('Password reset successfully! You can now login with your new password.', 'success')
            return redirect(url_for('Login'))
        else:
            error = "Username does not exist."
    return render_template('Password.html', error=error)

@app.route('/Login', methods=['GET', 'POST'])
def Login():
    error = None
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        user_ref = db.collection('users').document(username)
        user_doc = user_ref.get()

        if user_doc.exists:
            user_data = user_doc.to_dict()

            if user_data['password'] == password:
                session.permanent = True   # ADD THIS
                session['username'] = username
                return redirect(url_for('dashboard'))

            else:
                error = "Invalid username or password. Please try again."
        else:
            error = "Username does not exist. Please register first."

    return render_template('login.html', error=error)

@app.route('/dashboard')
@login_required
def dashboard():
    selected_month = request.args.get('month')
    if selected_month:
        selected_date = datetime.strptime(selected_month, '%Y-%m')
        filter_month = selected_date.month
        filter_year = selected_date.year
    # load expense documents and compute totals/plot data as before
    all_data = db.collection('expenses').where('username', '==', session['username']).stream()
   # convert Firestore documents to list of dicts - list
    expense_list = []

    for e in all_data:
        expense = e.to_dict()
        expense['id'] = e.id

        if selected_month:
            exp_date = expense['date']
            if exp_date.month == filter_month and exp_date.year == filter_year:
                expense_list.append(expense)
        else:
            expense_list.append(expense)

    total = sum(e['amount'] for e in expense_list)

    # category totals
    #dictionary to hold category totals - key is category name, value is total amount for that category
    categories = {}
    for e in expense_list:
        cat = e['category']
        categories[cat] = categories.get(cat, 0) + e['amount']

    # generate pie chart image
    #figures and axes
    fig, ax = plt.subplots()
    if categories:
        ax.pie(categories.values(), labels=categories.keys(), autopct='%1.1f%%')
        ax.set_title('Expense Distribution by Category')
        #Ensures pie chart is perfect circle.
        ax.axis('equal')
    img = io.BytesIO()
    plt.savefig(img, format='png', bbox_inches='tight')
    img.seek(0)
    plot_url = base64.b64encode(img.getvalue()).decode()

    # sort by date descending
    expense_list = sorted(expense_list, key=lambda x: x['date'], reverse=True)

    # render the index page as the main dashboard
    return render_template('index.html', expenses=expense_list, total=total, plot_url=plot_url, category_totals=categories, selected_month=selected_month)

# ADD EXPENSES
@app.route('/add', methods=['GET', 'POST'])
def add_expense():
    if request.method == 'POST':
        name = request.form['name']
        amount = float(request.form['amount'])
        category = request.form['category'      ]
        date_str = request.form['date']
        date = datetime.strptime(date_str, '%Y-%m-%d')

        db.collection('expenses').add({
            'username': session['username'],  # associate expense with logged in user
            'name': name,
            'amount': amount,
            'category': category,
            'date': date
        })
        return redirect(url_for('dashboard'))
    return render_template('add_expense.html')

@app.route('/delete/<expense_id>', methods=['POST'])
@login_required
def delete_expense(expense_id):
    username = session['username']
    expense_ref = db.collection('expenses').document(expense_id)
    expense_doc = expense_ref.get()
    if expense_doc.exists and expense_doc.to_dict().get('username') == username:
        expense_ref.delete()
    return redirect(url_for('dashboard'))

@app.route('/edit/<expense_id>', methods=['GET', 'POST'])
def edit_expense(expense_id):
    username = session['username']
    expense_ref = db.collection('expenses').document(expense_id)
    expense_doc = expense_ref.get()
    if not expense_doc.exists or expense_doc.to_dict().get('username') != username:
        return "Expense not found or you don't have permission to edit this expense.", 404
    expense = expense_doc.to_dict()
    if request.method == 'POST':
        name = request.form['name']
        amount = float(request.form['amount'])
        category = request.form['category']
        date_str = request.form['date']
        date = datetime.strptime(date_str, '%Y-%m-%d')

        db.collection('expenses').document(expense_id).update({
            'username': username,  # ensure username is included in update
            'name': name,
            'amount': amount,
            'category': category,
            'date': date
        })
        return redirect(url_for('dashboard'))
    return render_template('edit_expense.html', expense=expense, expense_id=expense_id)

@app.route('/logout')
def logout():
    session.pop('username', None)
    return redirect(url_for('Login'))

if __name__ == '__main__':
    app.run()