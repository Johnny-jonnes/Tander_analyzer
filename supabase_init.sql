-- Table names: enterprises, tenders, analyses, email_logs

-- 1. Enterprises
CREATE TABLE IF NOT EXISTS enterprises (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    sector VARCHAR(255) NOT NULL,
    min_budget FLOAT NOT NULL DEFAULT 0.0,
    max_budget FLOAT NOT NULL DEFAULT 0.0,
    zones TEXT,
    experience_years INTEGER NOT NULL DEFAULT 0,
    technical_capacity TEXT,
    email VARCHAR(255),
    specific_keywords TEXT,
    exclude_keywords TEXT,
    created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS ix_enterprises_id ON enterprises (id);
CREATE INDEX IF NOT EXISTS ix_enterprises_name ON enterprises (name);
CREATE INDEX IF NOT EXISTS ix_enterprises_sector ON enterprises (sector);

-- 2. Tenders
CREATE TABLE IF NOT EXISTS tenders (
    id SERIAL PRIMARY KEY,
    title VARCHAR(500) NOT NULL,
    description TEXT,
    raw_text TEXT,
    sector VARCHAR(255),
    estimated_budget FLOAT,
    location VARCHAR(255),
    deadline TIMESTAMP WITHOUT TIME ZONE,
    source_url VARCHAR(1000) NOT NULL UNIQUE,
    pdf_path VARCHAR(500),
    is_analyzed BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS ix_tenders_id ON tenders (id);
CREATE INDEX IF NOT EXISTS ix_tenders_title ON tenders (title);
CREATE INDEX IF NOT EXISTS ix_tenders_sector ON tenders (sector);
CREATE INDEX IF NOT EXISTS ix_tenders_is_analyzed ON tenders (is_analyzed);

-- 3. Analyses
CREATE TABLE IF NOT EXISTS analyses (
    id SERIAL PRIMARY KEY,
    tender_id INTEGER NOT NULL UNIQUE,
    enterprise_id INTEGER,
    summary TEXT,
    score FLOAT NOT NULL DEFAULT 0.0,
    explanation TEXT,
    extracted_sector TEXT,
    extracted_budget FLOAT,
    extracted_location TEXT,
    extracted_deadline TEXT,
    created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_analyses_tender FOREIGN KEY (tender_id) REFERENCES tenders (id) ON DELETE CASCADE,
    CONSTRAINT fk_analyses_enterprise FOREIGN KEY (enterprise_id) REFERENCES enterprises (id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS ix_analyses_id ON analyses (id);
CREATE INDEX IF NOT EXISTS ix_analyses_tender_id ON analyses (tender_id);
CREATE INDEX IF NOT EXISTS ix_analyses_enterprise_id ON analyses (enterprise_id);

-- 4. Email Logs
CREATE TABLE IF NOT EXISTS email_logs (
    id SERIAL PRIMARY KEY,
    enterprise_id INTEGER NOT NULL,
    tender_id INTEGER,
    recipient_email VARCHAR(255) NOT NULL,
    subject VARCHAR(500),
    status VARCHAR(50) NOT NULL DEFAULT 'pending',
    error_message TEXT,
    sent_at TIMESTAMP WITHOUT TIME ZONE,
    created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_email_logs_enterprise FOREIGN KEY (enterprise_id) REFERENCES enterprises (id) ON DELETE CASCADE,
    CONSTRAINT fk_email_logs_tender FOREIGN KEY (tender_id) REFERENCES tenders (id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS ix_email_logs_id ON email_logs (id);
CREATE INDEX IF NOT EXISTS ix_email_logs_enterprise_id ON email_logs (enterprise_id);
