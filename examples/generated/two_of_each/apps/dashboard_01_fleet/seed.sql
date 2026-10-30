-- Insert sample data into vehicles table
INSERT INTO vehicles (vehicle_id, make, model, year, registration_date) VALUES
('V1234', 'Toyota', 'Corolla', 2018, '2020-01-15'),
('V5678', 'Honda', 'Civic', 2019, '2020-02-20'),
('V9012', 'Ford', 'F-150', 2020, '2020-03-10');

-- Insert sample data into trips table
INSERT INTO trips (trip_id, vehicle_id, start_date, end_date, distance_km, fuel_liters) VALUES
('T1001', 'V1234', '2023-01-01', '2023-01-05', 150.00, 30.00),
('T1002', 'V5678', '2023-01-02', '2023-01-07', 200.00, 40.00),
('T1003', 'V9012', '2023-01-03', '2023-01-08', 250.00, 50.00');

-- Insert sample data into fuel_costs table
INSERT INTO fuel_costs (fuel_cost_id, vehicle_id, date, cost) VALUES
('FC1001', 'V1234', '2023-01-05', 30.00),
('FC1002', 'V5678', '2023-01-07', 40.00),
('FC1003', 'V9012', '2023-01-08', 50.00');

-- Insert sample data into maintenance_costs table
INSERT INTO maintenance_costs (maintenance_cost_id, vehicle_id, date, cost, service_type) VALUES
('MC1001', 'V1234', '2023-01-10', 100.00, 'Oil Change'),
('MC1002', 'V5678', '2023-01-12', 150.00, 'Brake Service'),
('MC1003', 'V9012', '2023-01-15', 200.00, 'Tire Replacement');

-- Insert sample data into services table
INSERT INTO services (service_id, vehicle_id, service_date, service_type, overdue) VALUES
('S1001', 'V1234', '2023-01-10', 'Oil Change', FALSE),
('S1002', 'V5678', '2023-01-12', 'Brake Service', FALSE),
('S1003', 'V9012', '2023-01-15', 'Tire Replacement', TRUE);