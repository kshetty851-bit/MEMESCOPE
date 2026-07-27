-- Runs once, on first initialisation of the data volume.

-- gen_random_uuid() for UUID primary keys.
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- Trigram indexes, for future token name/symbol search.
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- Dedicated test database so `make test` never touches development data.
SELECT 'CREATE DATABASE memescope_test'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'memescope_test')\gexec
