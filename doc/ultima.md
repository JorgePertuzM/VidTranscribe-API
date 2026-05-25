🔹 Para DESARROLLO LOCAL (con postgres/redis locales)
Si quieres probar localmente con los contenedores de postgres/redis:

# 1. Opción A: Sobrescribe tu .env temporalmente
cp .env.local .env

# 2. Levanta con el perfil 'local' para incluir postgres/redis
docker compose --profile local up --build

# 3. (Opcional) Incluye pgadmin también
docker compose --profile local --profile tools up --build

# Ver los logs para asegurarte que todo está bien
docker-compose logs -f api worker

# Sal del contenedor si estás dentro
exit

# Para detener:
docker compose --profile local down

# o con volúmenes (borra datos):
docker compose --profile local down -v

🔹 Comandos útiles adicionales

# Ver logs en tiempo real
docker compose logs -f api
docker compose logs -f worker

# Entrar a un contenedor para debug
docker compose exec api bash
docker compose exec worker bash

# Reconstruir sin caché (útil si cambiaste requirements)
docker compose up --build --no-cache

# Detener todo
docker compose down

# Ver estado de servicios
docker compose ps

🚨 Verificación rápida antes de ejecutar
Confirma que tu .env tiene las URLs correctas (ya lo tiene ✅)
Confirma que FFmpeg está en tu Dockerfile (ya lo tiene ✅)
Confirma que el volumen ./uploads:/app/uploads existe:

mkdir -p uploads

🧪 Prueba mínima después de levantar

# Verifica que la API responde
curl http://localhost:8000/health

# O abre en navegador:
# http://localhost:8000/docs

