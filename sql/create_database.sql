-- ============================================================
-- create_database.sql
-- Create the ecommerce_analytics database
-- ============================================================
-- Run ONCE before create_tables.sql.
--
-- MySQL:
--   mysql -u root -p < sql/create_database.sql
--
-- PostgreSQL:
--   psql -U postgres -f sql/create_database.sql
-- ============================================================


-- ==================== MySQL ====================

CREATE DATABASE IF NOT EXISTS ecommerce_analytics
    CHARACTER SET utf8mb4
    COLLATE utf8mb4_unicode_ci;

USE ecommerce_analytics;


-- ==================== PostgreSQL (uncomment below, comment MySQL above) ====================
-- NOTE: PostgreSQL does not support CREATE DATABASE IF NOT EXISTS natively.
-- Use the shell approach or the PL/pgSQL block below.
--
-- Option A — From the OS shell:
--   psql -U postgres -tc "SELECT 1 FROM pg_database WHERE datname = 'ecommerce_analytics'" \
--        | grep -q 1 || psql -U postgres -c "CREATE DATABASE ecommerce_analytics ENCODING 'UTF8'"
--
-- Option B — SQL block (run from psql as superuser):
--   DO $$
--   BEGIN
--       IF NOT EXISTS (SELECT FROM pg_database WHERE datname = 'ecommerce_analytics') THEN
--           PERFORM dblink_exec('dbname=postgres', 'CREATE DATABASE ecommerce_analytics ENCODING ''UTF8''');
--       END IF;
--   END
--   $$;
--
-- Then connect:
--   \c ecommerce_analytics
