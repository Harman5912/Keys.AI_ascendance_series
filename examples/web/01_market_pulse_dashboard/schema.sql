-- Market Pulse schema (MySQL 8+).
-- Idempotent: safe to run on an existing database.
CREATE DATABASE IF NOT EXISTS market_pulse
  CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE market_pulse;

CREATE TABLE IF NOT EXISTS market_ticks (
    id      BIGINT AUTO_INCREMENT PRIMARY KEY,
    symbol  VARCHAR(16) NOT NULL,
    day     DATE        NOT NULL,
    price   DECIMAL(14, 4) NOT NULL,
    volume  BIGINT      NOT NULL,
    UNIQUE KEY uniq_symbol_day (symbol, day),
    KEY idx_day (day)
);
