-- docker/postgres/init.sql
-- Se ejecuta automáticamente la primera vez que se crea el contenedor PostgreSQL

-- Habilitar extensión para búsqueda full-text (ya viene en postgres, pero se activa explícitamente)
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- Crear usuario de aplicación si no existe (opcional, para entornos más seguros)
-- DO $$
-- BEGIN
--   IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'vidtranscribe_app') THEN
--     CREATE ROLE vidtranscribe_app WITH LOGIN PASSWORD 'change_me_in_prod';
--   END IF;
-- END
-- $$;

-- Comentario: Las tablas se crearán vía Alembic desde la aplicación.
-- Este script es para extensiones, roles o configuraciones iniciales de BD.