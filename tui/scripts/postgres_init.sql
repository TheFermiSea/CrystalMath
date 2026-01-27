-- PostgreSQL initialization for AiiDA
-- ====================================
-- This script runs automatically when the container is first created.
-- It configures the database for optimal AiiDA performance.
--
-- Note: The database and user are created automatically by Docker's
-- POSTGRES_DB, POSTGRES_USER, and POSTGRES_PASSWORD environment variables.

-- =============================================================================
-- Database Configuration
-- =============================================================================

-- Set timezone to UTC for consistent timestamp handling
ALTER DATABASE aiida_crystal_tui SET timezone TO 'UTC';

-- Optimize for AiiDA's query patterns
ALTER DATABASE aiida_crystal_tui SET random_page_cost TO '1.1';
ALTER DATABASE aiida_crystal_tui SET effective_io_concurrency TO '200';

-- Enable JIT compilation for complex queries (PostgreSQL 12+)
ALTER DATABASE aiida_crystal_tui SET jit TO 'on';

-- =============================================================================
-- Extensions
-- =============================================================================

-- UUID generation (useful for unique identifiers)
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Hashing functions (used by AiiDA for content hashing)
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- =============================================================================
-- User Permissions
-- =============================================================================

-- Grant all privileges on the database to the AiiDA user
GRANT ALL PRIVILEGES ON DATABASE aiida_crystal_tui TO aiida_user;

-- Grant schema permissions (AiiDA creates its own schema)
GRANT ALL ON SCHEMA public TO aiida_user;

-- Allow user to create new schemas if needed
ALTER USER aiida_user CREATEDB;

-- =============================================================================
-- Maintenance Configuration
-- =============================================================================

-- Configure autovacuum for AiiDA's write-heavy workload
ALTER DATABASE aiida_crystal_tui SET autovacuum_vacuum_scale_factor TO '0.05';
ALTER DATABASE aiida_crystal_tui SET autovacuum_analyze_scale_factor TO '0.025';

-- =============================================================================
-- Verification
-- =============================================================================

-- Log successful initialization
DO $$
BEGIN
    RAISE NOTICE 'AiiDA database initialization complete';
    RAISE NOTICE 'Database: aiida_crystal_tui';
    RAISE NOTICE 'User: aiida_user';
    RAISE NOTICE 'Extensions: uuid-ossp, pgcrypto';
END $$;
