from flask import Flask, request, redirect, url_for, render_template
import mysql.connector
from mysql.connector import Error

app = Flask(__name__)

# Database connection function
def get_db_connection():
    try:
        conn = mysql.connector.connect(
            host='localhost',
            user='root',
            password='root',
            database='Problem-Order Matching System'
        )
        return conn
    except Error as e:
        print(f"Error: {e}")
        return None

# Function to process orders
def process_order(buyer_qty, buyer_price, seller_qty, seller_price):
    conn = get_db_connection()
    if conn is None:
        return

    cursor = conn.cursor()
    
    try:
        cursor.execute('START TRANSACTION;')  # Start a transaction
        
        # Insert the new pending order
        cursor.execute(
            "INSERT INTO PendingOrder (buyer_qty, buyer_price, seller_price, seller_qty) VALUES (%s, %s, %s, %s)",
            (buyer_qty, buyer_price, seller_price, seller_qty)
        )
        
        # Check for matching orders
        cursor.execute(
            "SELECT buyer_qty, seller_qty FROM PendingOrder WHERE buyer_price = seller_price"
        )
        matching_orders = cursor.fetchall()

        for buyer_qty, seller_qty in matching_orders:
            qty = min(buyer_qty, seller_qty)
            
            # Update the completed orders table
            cursor.execute(
                "INSERT INTO CompletedOrder (price, qty) VALUES (%s, %s) ON DUPLICATE KEY UPDATE qty = qty + VALUES(qty)",
                (buyer_price, qty)
            )
            
            # Update the pending orders table
            cursor.execute(
                "UPDATE PendingOrder SET buyer_qty = buyer_qty - %s, seller_qty = seller_qty - %s WHERE buyer_price = %s AND seller_price = %s",
                (qty, qty, buyer_price, seller_price)
            )
            
        cursor.execute('COMMIT;')  # Commit the transaction
    
    except Error as e:
        print(f"Error: {e}")
        conn.rollback()  # Rollback in case of error
    
    finally:
        cursor.close()
        conn.close()

@app.route('/submit_order', methods=['POST'])
def submit_order():
    # Extract data from the form
    buyer_qty = int(request.form['buyer_qty'])
    buyer_price = float(request.form['buyer_price'])
    seller_qty = int(request.form['seller_qty'])
    seller_price = float(request.form['seller_price'])
    
    process_order(buyer_qty, buyer_price, seller_qty, seller_price)
    
    return redirect(url_for('index'))

@app.route('/')
def index():
    return render_template('form.html')

if __name__ == '__main__':
    app.run(debug=True)

