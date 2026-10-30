-- Campaign Command schema (MySQL 8+).
CREATE DATABASE IF NOT EXISTS campaign_command
  CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE campaign_command;

CREATE TABLE IF NOT EXISTS campaigns (
    id          BIGINT AUTO_INCREMENT PRIMARY KEY,
    name        VARCHAR(120) NOT NULL,
    channel     VARCHAR(40)  NOT NULL,
    spend       DECIMAL(12,2) NOT NULL,
    revenue     DECIMAL(12,2) NOT NULL,
    impressions BIGINT NOT NULL,
    clicks      BIGINT NOT NULL,
    day         DATE NOT NULL,
    KEY idx_day (day),
    KEY idx_channel (channel)
);

CREATE TABLE IF NOT EXISTS tasks (
    id       BIGINT AUTO_INCREMENT PRIMARY KEY,
    title    VARCHAR(160) NOT NULL,
    campaign VARCHAR(120) NOT NULL,
    owner    VARCHAR(60)  NOT NULL,
    status   VARCHAR(20)  NOT NULL,   -- todo | doing | done
    due_day  DATE NOT NULL,
    progress TINYINT NOT NULL,
    KEY idx_status (status),
    KEY idx_due (due_day)
);
