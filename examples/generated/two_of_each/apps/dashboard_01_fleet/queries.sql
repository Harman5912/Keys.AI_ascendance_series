# Queries for the fleet operations dashboard

-- Get KPIs: distance per day, fuel cost per vehicle, maintenance cost, overdue services
SELECT
    DATE_FORMAT(trips.start_date, '%Y-%m-%d') AS date,
    SUM(trips.distance_km) AS total_distance_km
FROM
    trips
GROUP BY
    DATE_FORMAT(trips.start_date, '%Y-%m-%d');

-- Fuel cost per vehicle
SELECT
    fuel_costs.vehicle_id,
    SUM(fuel_costs.cost) AS total_fuel_cost
FROM
    fuel_costs
GROUP BY
    fuel_costs.vehicle_id;

-- Maintenance cost per vehicle
SELECT
    maintenance_costs.vehicle_id,
    SUM(maintenance_costs.cost) AS total_maintenance_cost
FROM
    maintenance_costs
GROUP BY
    maintenance_costs.vehicle_id;

-- Overdue services
SELECT
    services.vehicle_id,
    COUNT(*) AS overdue_services
FROM
    services
WHERE
    services.overdue = TRUE
GROUP BY
    services.vehicle_id;

-- Get all vehicles
SELECT
    *
FROM
    vehicles;

-- Get all trips
SELECT
    *
FROM
    trips;

-- Get all fuel costs
SELECT
    *
FROM
    fuel_costs;

-- Get all maintenance costs
SELECT
    *
FROM
    maintenance_costs;

-- Get all services
SELECT
    *
FROM
    services;