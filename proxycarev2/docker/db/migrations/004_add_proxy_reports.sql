CREATE TABLE IF NOT EXISTS proxy_reports (
    id SERIAL PRIMARY KEY,
    proxy_id INTEGER REFERENCES proxies(id),
    status_code INTEGER,
    reported_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
); 