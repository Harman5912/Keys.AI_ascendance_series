from flask import Flask, jsonify, render_template, request
import pymysql
import os
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)

# Database connection
def get_db_connection():
    conn = pymysql.connect(
        host=os.getenv('DB_HOST'),
        port=int(os.getenv('DB_PORT')),
        user=os.getenv('DB_USER'),
        password=os.getenv('DB_PASSWORD'),
        database=os.getenv('DB_NAME'),
        cursorclass=pymysql.cursors.DictCursor
    )
    return conn

# API endpoints
@app.route('/api/kpis', methods=['GET'])
def get_kpis():
    conn = get_db_connection()
    with conn.cursor() as cursor:
        # Fuel cost per vehicle
        cursor.execute("""
            SELECT v.vehicle_id, SUM(fc.cost) AS total_fuel_cost
            FROM vehicles v
            JOIN fuel_costs fc ON v.vehicle_id = fc.vehicle_id
            GROUP BY v.vehicle_id
        """)
        fuel_costs = cursor.fetchall()

        # Maintenance cost per vehicle
        cursor.execute("""
            SELECT v.vehicle_id, SUM(mc.cost) AS total_maintenance_cost
            FROM vehicles v
            JOIN maintenance_costs mc ON v.vehicle_id = mc.vehicle_id
            GROUP BY v.vehicle_id
        """)
        maintenance_costs = cursor.fetchall()

        # Overdue services
        cursor.execute("""
            SELECT COUNT(*) AS overdue_services
            FROM services
            WHERE overdue = TRUE
        """)
        overdue_services = cursor.fetchone()

        # Distance per day
        cursor.execute("""
            SELECT DATE(trip.start_date) AS date, SUM(trip.distance_km) AS total_distance
            FROM trips trip
            GROUP BY DATE(trip.start_date)
        """)
        distance_per_day = cursor.fetchall()

    conn.close()

    return jsonify({
        "fuel_costs": fuel_costs,
        "maintenance_costs": maintenance_costs,
        "overdue_services": overdue_services,
        "distance_per_day": distance_per_day
    })

@app.route('/api/series', methods=['GET'])
def get_series():
    range_days = request.args.get('range', default=30, type=int)
    conn = get_db_connection()
    with conn.cursor() as cursor:
        cursor.execute("""
            SELECT DATE(trip.start_date) AS date, SUM(trip.distance_km) AS total_distance
            FROM trips trip
            WHERE trip.start_date >= CURDATE() - INTERVAL %s DAY
            GROUP BY DATE(trip.start_date)
        """, (range_days,))
        distance_per_day = cursor.fetchall()

    conn.close()

    return jsonify({"distance_per_day": distance_per_day})

# Serve the dashboard
@app.route('/')
def index():
    return render_template('index.html')

if __name__ == '__main__':
    app.run(debug=True, port=5071)
