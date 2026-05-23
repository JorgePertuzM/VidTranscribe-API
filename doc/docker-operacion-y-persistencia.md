````md
# 🛑 Cómo Suspender y ▶️ Cómo Reanudar el Entorno Docker (Sin Perder Datos)

Tus datos están **100% seguros** en volúmenes nombrados de Docker:

- `vidtranscribe_postgres_data`
- `vidtranscribe_redis_data`

No importa cómo detengas los servicios, la información persiste mientras **no elimines los volúmenes manualmente**.

---

# 🔹 Suspensión para Descansos Cortos (Horas / Fin de Semana)

Utiliza este método cuando:

- Vas a pausar el trabajo temporalmente.
- No vas a reiniciar Windows.
- Solo necesitas detener los contenedores.

## ▶️ Detener servicios

```powershell
docker compose stop
```

## ▶️ Reanudar servicios

```powershell
docker compose start
Start-Sleep -Seconds 10
```

> ✅ `stop` conserva el estado y permite reinicios rápidos.

---

# 🔹 Suspensión para Ausencias Largas (Días / Reinicio del PC)

Utiliza este método cuando:

- Vas a apagar el computador.
- Reiniciarás Windows.
- Cerrarás Docker Desktop.
- Deseas liberar recursos completamente.

## ▶️ Detener y eliminar contenedores/redes

```powershell
docker compose down
```

## ▶️ Reanudar servicios

```powershell
docker compose up -d
Start-Sleep -Seconds 15
```

> 💡 `down` elimina contenedores y redes, pero conserva los volúmenes y la base de datos.

---

# 🗄️ Formas de Acceder a PostgreSQL

---

## 🔹 Opción 1: Terminal Interactiva (`psql`)

Entrar directamente al shell de PostgreSQL:

```powershell
docker compose exec postgres psql -U postgres -d vidtranscribe
```

### Ejemplos útiles dentro de `psql`

```sql
\dt

SELECT id, title, status
FROM videos;

SELECT count(*)
FROM transcriptions;

\q
```

### Descripción de comandos

| Comando | Descripción |
|---|---|
| `\dt` | Listar tablas |
| `\q` | Salir de `psql` |

---

## 🔹 Opción 2: Consulta Rápida Sin Entrar al Shell

Ejecutar SQL directamente desde PowerShell:

```powershell
docker compose exec postgres psql -U postgres -d vidtranscribe -c "
SELECT
    v.title,
    v.status,
    COUNT(c.id) AS chunks,
    COUNT(t.id) AS transcriptions
FROM videos v
LEFT JOIN chunks c ON v.id = c.video_id
LEFT JOIN transcriptions t ON c.id = t.chunk_id
GROUP BY v.id;
"
```

---

## 🔹 Opción 3: Conexión Desde el Host

Gracias a la exposición del puerto:

```yaml
5432:5432
```

Puedes conectarte desde herramientas externas.

## Parámetros de conexión

| Parámetro | Valor |
|---|---|
| Host | `localhost` |
| Port | `5432` |
| Database | `vidtranscribe` |
| User | `postgres` |
| Password | `postgres` |

## Herramientas compatibles

- DBeaver
- DataGrip
- TablePlus
- pgAdmin
- `psql`

### Ejemplo usando `psql`

```powershell
psql -h localhost -p 5432 -U postgres -d vidtranscribe
```

---

## 🔹 Opción 4: pgAdmin (Interfaz Web)

El servicio ya está incluido bajo el perfil `tools`.

## ▶️ Levantar pgAdmin

```powershell
docker compose --profile tools up -d pgadmin
```

## ▶️ Acceder desde navegador

```text
http://localhost:5050
```

## Credenciales

Las definidas en el archivo `.env`:

```env
PGADMIN_EMAIL=
PGADMIN_PASSWORD=
```

## Configuración del servidor en pgAdmin

| Parámetro | Valor |
|---|---|
| Host | `postgres` |
| Port | `5432` |
| User | `postgres` |
| Password | `postgres` |

---

# 📋 Comandos Útiles del Día a Día

| Acción | Comando |
|---|---|
| Ver estado de servicios | `docker compose ps` |
| Ver logs en tiempo real | `docker compose logs -f` |
| Ver logs de un servicio específico | `docker compose logs -f worker` |
| Reiniciar un servicio | `docker compose restart api` |
| Ver espacio usado por Docker | `docker system df` |
| Crear backup de PostgreSQL | `docker compose exec postgres pg_dump -U postgres vidtranscribe > backup.sql` |
| Restaurar backup | `docker compose exec -T postgres psql -U postgres vidtranscribe < backup.sql` |

---

# 💡 Recomendaciones Importantes

## 1. Detener servicios antes de apagar Windows

Ejecuta:

```powershell
docker compose stop
```

Esto reduce riesgos de corrupción de volúmenes.

---

## 2. Redis también persiste información

Los siguientes datos permanecen almacenados:

- Contadores de API Keys.
- Colas de Celery.
- Caché persistente.

Todo se guarda en:

```text
vidtranscribe_redis_data
```

---

## 3. ⚠️ Comando Peligroso

```powershell
docker compose down -v
```

> ❌ Este comando elimina absolutamente TODO:
>
> - Base de datos.
> - Redis.
> - Volúmenes.
> - Información persistente.

Úsalo únicamente si deseas reiniciar el proyecto desde cero.

---

## 4. Esperar Healthchecks

Después de iniciar los servicios:

```powershell
docker compose up -d
```

Es recomendable esperar entre:

```text
15–20 segundos
```

Antes de probar la API o conectarte a PostgreSQL.

---

# 🌙 Suspensión Rápida Recomendada

## ▶️ Detener servicios limpiamente

```powershell
docker compose stop
```

## ▶️ Verificar estado

```powershell
docker compose ps
```

Resultado esperado:

```text
State = exited
```

---

# ▶️ Restaurar el Entorno

```powershell
docker compose start
Start-Sleep -Seconds 10
```

## ▶️ Verificar API

```powershell
curl http://localhost:8000/health
```

Resultado esperado:

```text
200 OK
```

---

# ✅ Resumen Rápido

| Escenario | Comando Recomendado |
|---|---|
| Pausa corta | `docker compose stop` |
| Reinicio de Windows | `docker compose down` |
| Inicio rápido | `docker compose start` |
| Inicio completo | `docker compose up -d` |
| Borrado total | `docker compose down -v` |

---

# 🚀 Estado del Proyecto

Tu MVP queda:

- Seguro.
- Persistente.
- Recuperable.
- Listo para reiniciarse en cualquier momento.

````
