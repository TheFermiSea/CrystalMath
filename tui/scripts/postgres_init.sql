-- PostgreSQL initialization for AiiDA
-- This script runs automatically when the container is first created

-- Ensure the database is properly configured for AiiDA
ALTER DATABASE aiida_crystal_tui SET timezone TO 'UTC';

-- Create extensions if needed
-- CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Grant all privileges to the AiiDA user
GRANT ALL PRIVILEGES ON DATABASE aiida_crystal_tui TO aiida_user;
