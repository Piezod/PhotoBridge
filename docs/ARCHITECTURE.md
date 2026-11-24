# Arquitectura de PhotoBridge

## Alcance actual

La fase 0 crea un monolito modular de ejecución local. `app/main.py` compone
FastAPI, recursos estáticos, plantillas y rutas. La ruta de salud solo informa
que el proceso responde; no realiza comprobaciones de servicios externos.

## Capas previstas

- `app/domain/models` y `app/domain/ports`: modelos y contratos independientes
  del framework.
- `app/application/services` y `app/application/use_cases`: reglas y
  orquestación.
- `app/infrastructure`: adaptadores de persistencia, almacenamiento, seguridad
  e integraciones futuras.
- `app/presentation/api`, `templates` y `static`: HTTP e interfaz web.
- `app/config.py`: configuración de la aplicación.

Las capas de dominio, aplicación e infraestructura se crean como estructura,
pero no contienen lógica hasta sus fases autorizadas.

## Seguridad inicial

- Uvicorn se enlaza únicamente a `127.0.0.1`.
- El modo de prueba está activo y limitado a un máximo de 10 fotografías.
- La configuración no permite habilitar la eliminación de originales ni
  desactivar la confirmación manual o habilitar migraciones automáticas.
- No se cargan credenciales, no hay almacenamiento local de datos ni se hacen
  conexiones externas.
- La configuración sensible no se guarda en Git; `.env` está excluido y
  `.env.example` no contiene secretos.

## Interfaz

La página de inicio, Bootstrap 5, HTMX y los estilos propios se sirven
localmente. Las secciones no disponibles son marcadores visuales y no
implementan acciones. No se carga ningún recurso CDN ni se realizan
conexiones externas.
