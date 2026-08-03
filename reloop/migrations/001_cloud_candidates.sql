-- Reloop RDS baseline. Apply with the deployment migration runner before
-- enabling the delivery worker. The unique key is required by upsert_candidate.
CREATE TABLE IF NOT EXISTS cloud_candidates (
    fingerprint VARCHAR(64) NOT NULL,
    name VARCHAR(255) NOT NULL DEFAULT '',
    phone VARCHAR(64) NOT NULL DEFAULT '',
    email VARCHAR(255) NOT NULL DEFAULT '',
    raw_profile JSON NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (fingerprint)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
