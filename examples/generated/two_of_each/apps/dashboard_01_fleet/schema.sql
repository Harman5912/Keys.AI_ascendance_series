-- Create fleet_ops database
CREATE DATABASE IF NOT EXISTS fleet_ops;

-- Use fleet_ops database
USE fleet_ops;

-- Vehicles table
CREATE TABLE IF NOT EXISTS vehicles (
    id INT AUTO_INCREMENT PRIMARY KEY,
    vehicle_id VARCHAR(50) NOT NULL,
    make VARCHAR(50) NOT NULL,
    model VARCHAR(50) NOT NULL,
    year INT NOT NULL,
    registration_date DATE NOT NULL
);

-- Trips table
CREATE TABLE IF NOT EXISTS trips (
    id INT AUTO_INCREMENT PRIMARY KEY,
    trip_id VARCHAR(50) NOT NULL,
    vehicle_id VARCHAR(50) NOT NULL,
    start_date DATE NOT NULL,
    end_date DATE NOT NULL,
    distance_km DECIMAL(10,2) NOT NULL,
    fuel_liters DECIMAL(10,2) NOT NULL,
    FOREIGN KEY (vehicle_id) REFERENCES vehicles(vehicle_id)
);

-- Fuel Costs table
CREATE TABLE IF NOT EXISTS fuel_costs (
    id INT AUTO_INCREMENT PRIMARY KEY,
    fuel_cost_id VARCHAR(50) NOT NULL,
    vehicle_id VARCHAR(50) NOT NULL,
    date DATE NOT NULL,
    cost DECIMAL(10,2) NOT NULL,
    FOREIGN KEY (vehicle_id) REFERENCES vehicles(vehicle_id)
);

-- Maintenance Costs table
CREATE TABLE IF NOT EXISTS maintenance_costs (
    id INT AUTO_INCREMENT PRIMARY KEY,
    maintenance_cost_id VARCHAR(50) NOT NULL,
    vehicle_id VARCHAR(50) NOT NULL,
    date DATE NOT NULL,
    cost DECIMAL(10,2) NOT NULL,
    service_type VARCHAR(50) NOT NULL,
    FOREIGN KEY (vehicle_id) REFERENCES vehicles(vehicle_id)
);

-- Services table
CREATE TABLE IF NOT EXISTS services (
    id INT AUTO_INCREMENT PRIMARY KEY,
    service_id VARCHAR(50) NOT NULL,
    vehicle_id VARCHAR(50) NOT NULL,
    service_date DATE NOT NULL,
    service_type VARCHAR(50) NOT NULL,
    overdue BOOLEAN NOT NULL,
    FOREIGN KEY (vehicle_id) REFERENCES vehicles(vehicle_id)
);