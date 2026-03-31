-- Rygell Dashboard - Initial Schema (Reference, auto-migrated by GORM)
-- This file serves as documentation; GORM handles migrations automatically.

-- ============================================================
-- MASTER DATA
-- ============================================================

CREATE TABLE IF NOT EXISTS mills (
    id SERIAL PRIMARY KEY,
    code VARCHAR(50) UNIQUE NOT NULL,
    name VARCHAR(255) NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    deleted_at TIMESTAMPTZ
);
CREATE INDEX idx_mills_deleted_at ON mills(deleted_at);

CREATE TABLE IF NOT EXISTS vendors (
    id SERIAL PRIMARY KEY,
    code VARCHAR(50) UNIQUE NOT NULL,
    name VARCHAR(255) NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    deleted_at TIMESTAMPTZ
);
CREATE INDEX idx_vendors_deleted_at ON vendors(deleted_at);

CREATE TABLE IF NOT EXISTS products (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    deleted_at TIMESTAMPTZ
);
CREATE INDEX idx_products_deleted_at ON products(deleted_at);

CREATE TABLE IF NOT EXISTS zones (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    type VARCHAR(50) NOT NULL, -- 'origin' or 'destination'
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    deleted_at TIMESTAMPTZ
);
CREATE INDEX idx_zones_deleted_at ON zones(deleted_at);

CREATE TABLE IF NOT EXISTS mots (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    deleted_at TIMESTAMPTZ
);
CREATE INDEX idx_mots_deleted_at ON mots(deleted_at);

CREATE TABLE IF NOT EXISTS uoms (
    id SERIAL PRIMARY KEY,
    name VARCHAR(50) NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    deleted_at TIMESTAMPTZ
);
CREATE INDEX idx_uoms_deleted_at ON uoms(deleted_at);

-- ============================================================
-- CONTRACTS
-- ============================================================

CREATE TABLE IF NOT EXISTS contract_dedicated_fixes (
    id SERIAL PRIMARY KEY,
    mill_id INTEGER NOT NULL REFERENCES mills(id),
    vendor_id INTEGER NOT NULL REFERENCES vendors(id),
    product_id INTEGER REFERENCES products(id),
    license_plate VARCHAR(50),
    spk_number VARCHAR(100),
    validity_start TIMESTAMPTZ,
    validity_end TIMESTAMPTZ,
    cost_jan NUMERIC(15,2) DEFAULT 0,
    cost_feb NUMERIC(15,2) DEFAULT 0,
    cost_mar NUMERIC(15,2) DEFAULT 0,
    cost_apr NUMERIC(15,2) DEFAULT 0,
    cost_may NUMERIC(15,2) DEFAULT 0,
    cost_jun NUMERIC(15,2) DEFAULT 0,
    distributed_cost NUMERIC(15,2) DEFAULT 0,
    notes TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    deleted_at TIMESTAMPTZ
);
CREATE INDEX idx_cdf_mill ON contract_dedicated_fixes(mill_id);
CREATE INDEX idx_cdf_vendor ON contract_dedicated_fixes(vendor_id);
CREATE INDEX idx_cdf_spk ON contract_dedicated_fixes(spk_number);
CREATE INDEX idx_cdf_deleted_at ON contract_dedicated_fixes(deleted_at);

CREATE TABLE IF NOT EXISTS contract_dedicated_vars (
    id SERIAL PRIMARY KEY,
    mill_id INTEGER NOT NULL REFERENCES mills(id),
    vendor_id INTEGER NOT NULL REFERENCES vendors(id),
    product_id INTEGER REFERENCES products(id),
    origin_zone_id INTEGER REFERENCES zones(id),
    dest_zone_id INTEGER REFERENCES zones(id),
    mot_id INTEGER REFERENCES mots(id),
    uom_id INTEGER REFERENCES uoms(id),
    spk_number VARCHAR(100),
    validity_start TIMESTAMPTZ,
    validity_end TIMESTAMPTZ,
    payload NUMERIC(15,2) DEFAULT 0,
    cost_per_kg NUMERIC(15,4) DEFAULT 0,
    notes TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    deleted_at TIMESTAMPTZ
);
CREATE INDEX idx_cdv_mill ON contract_dedicated_vars(mill_id);
CREATE INDEX idx_cdv_vendor ON contract_dedicated_vars(vendor_id);
CREATE INDEX idx_cdv_spk ON contract_dedicated_vars(spk_number);
CREATE INDEX idx_cdv_deleted_at ON contract_dedicated_vars(deleted_at);

CREATE TABLE IF NOT EXISTS contract_oncalls (
    id SERIAL PRIMARY KEY,
    mill_id INTEGER NOT NULL REFERENCES mills(id),
    vendor_id INTEGER NOT NULL REFERENCES vendors(id),
    product_id INTEGER REFERENCES products(id),
    origin_zone_id INTEGER REFERENCES zones(id),
    dest_zone_id INTEGER REFERENCES zones(id),
    mot_id INTEGER REFERENCES mots(id),
    uom_id INTEGER REFERENCES uoms(id),
    spk_number VARCHAR(100),
    validity_start TIMESTAMPTZ,
    validity_end TIMESTAMPTZ,
    distance NUMERIC(10,2) DEFAULT 0,
    loading_cost NUMERIC(15,2) DEFAULT 0,
    unloading_cost NUMERIC(15,2) DEFAULT 0,
    running_cost_idr NUMERIC(15,4) DEFAULT 0,
    notes TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    deleted_at TIMESTAMPTZ
);
CREATE INDEX idx_co_mill ON contract_oncalls(mill_id);
CREATE INDEX idx_co_vendor ON contract_oncalls(vendor_id);
CREATE INDEX idx_co_spk ON contract_oncalls(spk_number);
CREATE INDEX idx_co_deleted_at ON contract_oncalls(deleted_at);

-- ============================================================
-- AUDIT LOGS
-- ============================================================

CREATE TABLE IF NOT EXISTS audit_logs (
    id SERIAL PRIMARY KEY,
    entity_type VARCHAR(100) NOT NULL,
    entity_id INTEGER NOT NULL,
    action VARCHAR(50) NOT NULL,
    changed_by VARCHAR(255),
    agreement_note TEXT,
    old_data JSONB,
    new_data JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_audit_entity ON audit_logs(entity_type, entity_id);
