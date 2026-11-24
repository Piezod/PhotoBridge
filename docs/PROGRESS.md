# Progreso de PhotoBridge

## Fase implementada

Fase 0 — Bootstrap e inicialización. No se ha comenzado la fase 1.

## Archivos creados

- `.gitignore`, `.env.example`, `pyproject.toml` y `README.md`.
- `app/config.py`, `app/main.py` y estructura modular bajo `app/`.
- `app/presentation/api/routes.py`, plantilla, estilos y recursos locales de
  Bootstrap 5 / HTMX con sus licencias.
- `tests/unit/test_config.py` y `tests/integration/test_health.py`.
- `scripts/setup.ps1` y `scripts/start.ps1`.
- `docs/ARCHITECTURE.md`, `docs/adr/0001-recursos-locales-de-interfaz.md` y
  este archivo.

## Decisiones técnicas

- FastAPI compone la aplicación; Uvicorn escucha en `127.0.0.1`.
- Pydantic Settings mantiene activas las protecciones: modo de prueba,
  máximo de 10 fotografías, originales no eliminables, confirmación manual
  obligatoria y migraciones automáticas deshabilitadas.
- Las restricciones de seguridad iniciales se validan como valores fijos y el
  límite de prueba no puede superar 10.
- Bootstrap 5 y HTMX se incluyen como recursos locales junto con los estilos
  propios; no se cargan CDNs ni se realizan conexiones externas.
- Las secciones distintas de Inicio son marcadores no disponibles.

## Pruebas y resultados

Entorno creado con Python 3.12.10:

- `.\.venv\Scripts\python.exe -m pytest` — 6 pruebas correctas.
- `.\.venv\Scripts\python.exe -m ruff check .` — correcto, sin errores.
- Arranque mediante `.\scripts\start.ps1` — servidor iniciado correctamente en
  `127.0.0.1:8000`; `/` y `/health` respondieron HTTP 200.
- `/static/vendor/bootstrap.min.css` y `/static/vendor/htmx.min.js` respondieron
  HTTP 200. El proceso de validación fue detenido y el puerto quedó liberado.
- `.\.venv\Scripts\python.exe -m pip wheel --no-deps --wheel-dir .\data\wheel-check .`
  — wheel construido correctamente e incluye plantilla, estilos, Bootstrap y
  HTMX.

## Problemas pendientes

- No se encontró `.github/copilot-instructions.md`; se leyó íntegramente el
  archivo disponible `copilot-instructions-python.md`.
- No se implementaron integraciones ni lógica de las secciones pendientes,
  conforme al alcance de fase 0.
- Las secciones de conexiones, explorador, migraciones, historial y
  configuración siguen sin funcionalidad, a la espera de autorización para
  fases posteriores.

## Arranque

Desde PowerShell en la carpeta del proyecto:

1. `.\scripts\setup.ps1`
2. `.\scripts\start.ps1`
3. Abrir `http://localhost:8000`.

El endpoint de comprobación es `http://localhost:8000/health`.
