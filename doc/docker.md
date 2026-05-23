# 🐳 Gestión de Infraestructura con Docker - VidTranscribe

Este documento explica cómo gestionar **todos los servicios** del proyecto VidTranscribe usando Docker Compose: PostgreSQL, Redis, API FastAPI y Worker Celery.

---

## 📋 Requisitos Previos

- Docker Desktop instalado y ejecutándose (https://www.docker.com/products/docker-desktop/)
- Docker Compose v2+ (viene incluido en Docker Desktop)
- PowerShell (Windows) o terminal bash (Linux/macOS)
- FFmpeg instalado en tu sistema para desarrollo local (opcional si usas Docker completo)

---

## 🗂️ Estructura Relacionada

```bash
vidtranscribe/
├── docker-compose.yml      # Definición de TODOS los servicios
├── Dockerfile              # Imagen para API + Worker (Python 3.14 + FFmpeg)
├── docker/
│   └── postgres/
│       └── init.sql        # Script de inicialización de BD
├── .env                    # Variables de entorno (DB, Redis, Gemini)
├── uploads/                # Volumen montado para archivos procesados
└── doc/
    └── docker.md           # Este archivo
```

---

## ⚙️ Configuración de `.env` para Docker

### Variables Esenciales

```env
# ================= DATABASE =================
DB_USER=postgres
DB_PASSWORD=postgres
DB_NAME=vidtranscribe

# Para desarrollo LOCAL (sin Docker para la app):
DATABASE_URL=postgresql+psycopg2://postgres:postgres@localhost:5432/vidtranscribe
REDIS_URL=redis://localhost:6379/0

# Para desarrollo CON Docker (la app está en contenedor):
# El docker-compose.yml sobrescribe estas variables internamente:
# DATABASE_URL=postgresql+psycopg2://postgres:postgres@postgres:5432/vidtranscribe
# REDIS_URL=redis://redis:6379/0

# ================= GEMINI =================
GEMINI_API_KEYS=AIzaSyA...,AIzaSyB...,AIzaSyC...,AIzaSyD...
GEMINI_MODEL=gemini-2.5-flash

# ================= UPLOADS & LIMITS =================
UPLOAD_DIR=./uploads
MAX_FILE_SIZE_MB=1500
MAX_DURATION_MIN=120
CHUNK_DURATION_SEC=150
CHUNK_OVERLAP_SEC=5

# ================= SERVER =================
HOST=0.0.0.0
PORT=8000
DEBUG=true

# ================= PGADMIN (opcional) =================
PGADMIN_EMAIL=admin@vidtranscribe.local
PGADMIN_PASSWORD=admin
```

> 🔑 **Regla de Oro**:
>
> - Si ejecutas la app **desde tu host** (`uvicorn` directo): usa `localhost` en `DATABASE_URL` y `REDIS_URL`.
> - Si ejecutas la app **en Docker** (`docker compose up`): el compose sobrescribe con `postgres` y `redis` (nombres de servicio).
> - Tu `.env` puede mantener `localhost`; el compose se encarga de la magia.

---

# 🚀 Modos de Desarrollo

## 🔹 Opción A: Todo en Docker

Ejecuta **todos** los servicios en contenedores. Ideal para pruebas finales y despliegue.

```powershell
# 1. Construir imágenes (solo primera vez o si cambias Dockerfile)
docker compose build

# 2. Iniciar todos los servicios
docker compose up -d

# 3. Aplicar migraciones
alembic upgrade head

# 4. Ver logs en tiempo real
docker compose logs -f api worker

# 5. Probar la API
curl http://localhost:8000/health

# 6. Detener sin perder datos
docker compose stop

# 7. Reiniciar rápido
docker compose start
```

### ✅ Ventajas

- Entorno idéntico a producción
- Sin instalar Python/FFmpeg en tu host
- Aislamiento total de dependencias

### ❌ Desventajas

- Recarga manual al cambiar código
- Debugging más complejo

---

## 🔹 Opción B: Híbrido (Recomendado para desarrollo)

Ejecuta PostgreSQL y Redis en Docker, pero la API y Worker en tu host.

```powershell
# 1. Levantar PostgreSQL + Redis
docker compose up -d postgres redis

# O con PGAdmin
docker compose --profile tools up -d

# 2. Activar entorno virtual
.venv\Scripts\Activate.ps1

# 3. Worker Celery (Terminal #1)
celery -A src.tasks worker --loglevel=info -c 4

# 4. API FastAPI (Terminal #2)
uvicorn src.main:app --reload
```

### ✅ Ventajas

- Recarga automática
- Debugging con breakpoints
- Logs directos en terminal

### ❌ Desventajas

- Requiere Python + FFmpeg local
- Diferencias menores con producción

> 💡 **Recomendación**:
>
> Usa modo híbrido durante desarrollo activo y Docker completo para pruebas finales.

---

# 🧪 Comandos Esenciales

## Ver estado de servicios

```powershell
docker compose ps

docker compose ps api worker postgres redis
```

### Salida esperada

```text
NAME                          STATUS
vidtranscribe-api             healthy
vidtranscribe-worker          running
vidtranscribe-postgres        healthy
vidtranscribe-redis           healthy
```

---

## Ver logs

```powershell
# Todos los servicios
docker compose logs -f

# Solo API
docker compose logs -f api

# Solo Worker
docker compose logs -f worker --tail 50

# Buscar errores
docker compose logs worker | Select-String "error"
```

---

## Gestión de volúmenes y datos

```powershell
# Detener sin perder datos
docker compose stop

# Eliminar contenedores
docker compose down

# ⚠️ ELIMINAR TODO
docker compose down -v

# Limpiar logs
docker compose logs --tail 0
```

---

## Acceder a consolas de servicios

### PostgreSQL

```powershell
docker exec -it vidtranscribe-postgres psql -U postgres -d vidtranscribe
```

#### Dentro de `psql`

```sql
\dt
\d videos
SELECT COUNT(*) FROM videos;
\q
```

---

### Redis

```powershell
docker exec -it vidtranscribe-redis redis-cli
```

#### Dentro de Redis

```bash
KEYS *
GET gem:rpd:0:20260523
INFO memory
exit
```

---

### API

```powershell
docker exec -it vidtranscribe-api bash
```

#### Dentro del contenedor

```bash
ls /app/uploads
curl http://localhost:8000/health
exit
```

---

# 🩺 Verificar salud de servicios

```powershell
docker compose ps postgres
docker compose ps redis
docker compose ps api
```

## Healthcheck directo

```powershell
docker inspect vidtranscribe-postgres --format='{{.State.Health.Status}}'

docker inspect vidtranscribe-redis --format='{{.State.Health.Status}}'

docker inspect vidtranscribe-api --format='{{.State.Health.Status}}'
```

## Endpoint Health

```powershell
curl http://localhost:8000/health | ConvertFrom-Json
```

---

# 🌐 PGAdmin

## Iniciar PGAdmin

```powershell
docker compose --profile tools up -d
```

## Acceso

- URL: `http://localhost:5050`
- Email: `admin@vidtranscribe.local`
- Password: `admin`

---

## Conectar PostgreSQL

### Opción A: Desde host

- Host: `localhost`
- Port: `5432`
- Username: `postgres`
- Password: `postgres`

### Opción B: Red Docker

- Host: `vidtranscribe-postgres`
- Port: `5432`

---

# 🔄 Flujo de Trabajo Recomendado

## Inicio del día

```powershell
# Levantar BD + Redis
docker compose up -d postgres redis

# Verificar estado
docker compose ps postgres redis

# Aplicar migraciones
alembic upgrade head
```

## Terminales de trabajo

### Worker

```powershell
celery -A src.tasks worker --loglevel=info -c 4
```

### API

```powershell
uvicorn src.main:app --reload
```

---

## Fin del día

```powershell
docker compose stop
```

## Próxima sesión

```powershell
docker compose start
```

---

# 🚢 Despliegue en Producción

## Render

### Preparar repositorio

```bash
git add Dockerfile docker-compose.yml render.yaml

git commit -m "Add Docker deployment config"

git push origin main
```

### Variables de entorno

```env
DATABASE_URL=(automático)
REDIS_URL=(automático)
GEMINI_API_KEYS=...
DEBUG=false
```

---

## VPS Ubuntu

### Instalar dependencias

```bash
sudo apt update

sudo apt install -y ffmpeg python3.14 python3.14-venv \
postgresql postgresql-contrib redis-server nginx
```

### Crear base de datos

```bash
sudo -u postgres psql
```

```sql
CREATE DATABASE vidtranscribe;

CREATE USER vidtranscribe WITH PASSWORD 'tu_password_seguro';

GRANT ALL PRIVILEGES ON DATABASE vidtranscribe TO vidtranscribe;

\q
```

---

# 🔧 Solución de Problemas

## ❌ Connection refused

| Causa | Solución |
|---|---|
| Contenedores no healthy | `docker compose ps` |
| DATABASE_URL incorrecto | Usar `localhost` |
| Puerto ocupado | Revisar 5432 y 6379 |

---

## ❌ Alembic no crea tablas

```powershell
docker compose ps postgres

alembic upgrade head
```

---

## ❌ Worker no procesa tareas

| Problema | Solución |
|---|---|
| Redis inaccesible | Revisar `REDIS_URL` |
| Tareas pendientes | Reiniciar Redis |
| PATH incorrecto | Revisar `WORKDIR /app` |

---

## ❌ FFmpeg no encontrado

```powershell
docker run --rm vidtranscribe-api ffmpeg -version
```

```powershell
docker compose build --no-cache api worker
```

---

## ❌ Uploads no persisten

```powershell
docker compose exec api ls -la /app/uploads

Get-ChildItem uploads/
```

---

## ❌ Gemini 429 ResourceExhausted

```powershell
docker exec -it vidtranscribe-redis redis-cli

KEYS gem:*
```

---

# 📊 Monitoreo

## Recursos

```powershell
docker stats vidtranscribe-api vidtranscribe-worker

docker system df -v
```

## Logs recientes

```powershell
docker compose logs --tail 100 | Select-String "error|exception|failed"
```

---

# 🔄 Actualización de la Aplicación

## Cambios de código

### Modo híbrido

```powershell
# Solo guardar archivos
# uvicorn --reload recarga automáticamente
```

### Docker completo

```powershell
docker compose build api worker

docker compose up -d api worker
```

---

## Cambios en dependencias

```powershell
docker compose build --no-cache api worker

docker compose up -d api worker
```

---

## Cambios en modelos / BD

```powershell
# Generar migración
alembic revision --autogenerate -m "descripcion"

# Aplicar migración
alembic upgrade head
```

---

# 🗑️ Limpieza y Mantenimiento

## Limpiar imágenes

```powershell
docker images

docker image prune -f

docker image prune -a -f
```

---

## Limpiar volúmenes

```powershell
docker volume ls

docker volume prune -f
```

---

## Backup PostgreSQL

### Exportar

```powershell
docker exec -t vidtranscribe-postgres pg_dump -U postgres vidtranscribe > backup.sql
```

### Restaurar

```powershell
docker exec -i vidtranscribe-postgres psql -U postgres vidtranscribe < backup.sql
```

---

# 📞 Soporte y Debugging

## Activar logs detallados

```env
DEBUG=true
```

---

## Logs en tiempo real

### API

```powershell
docker compose logs -f api
```

### Worker

```powershell
docker compose logs -f worker
```

---

## Comandos útiles dentro de contenedores

### Shell API

```powershell
docker exec -it vidtranscribe-api bash
```

### Procesos Worker

```powershell
docker exec -it vidtranscribe-worker ps aux | grep celery
```

### Query PostgreSQL

```powershell
docker exec -t vidtranscribe-postgres \
psql -U postgres -d vidtranscribe \
-c "SELECT COUNT(*) FROM videos;"
```

---

> ✅ **Recordatorio Final**
>
> - Usa modo híbrido para desarrollo diario.
> - Usa Docker completo para integración y preproducción.
> - Mantén `.env` fuera del repositorio.
> - Realiza backups frecuentes antes de migraciones críticas.

---

*Última actualización: Mayo 2026*  
*Versión del proyecto: 0.1.0*