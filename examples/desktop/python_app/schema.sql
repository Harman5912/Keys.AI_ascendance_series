-- Ledger Lite schema (MySQL 8+).
CREATE DATABASE IF NOT EXISTS ledger_lite
  CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE ledger_lite;

CREATE TABLE IF NOT EXISTS notes (
    id      BIGINT AUTO_INCREMENT PRIMARY KEY,
    title   VARCHAR(140) NOT NULL,
    body    TEXT NOT NULL,
    status  VARCHAR(16) NOT NULL DEFAULT 'open',
    created DATE NOT NULL,
    KEY idx_status (status)
);
