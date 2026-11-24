# PhotoBridge

PhotoBridge es una aplicación local para preparar la gestión segura de
fotografías. Esta entrega implementa exclusivamente la fase 0 (inicialización):
no conecta con Synology ni Amazon Photos y no migra archivos.

## Requisitos

- Windows.
- Python 3.12.

## Instalación

Desde PowerShell, en la carpeta del proyecto:

```powershell
.\scripts\setup.ps1
```

El script crea `.venv` usando Python 3.12 e instala la aplicación y las
dependencias de desarrollo.

## Arranque

```powershell
.\scripts\start.ps1
```

Abre <http://localhost:8000>. El servidor escucha exclusivamente en
`127.0.0.1`. Para detenerlo, pulsa `Ctrl+C` en PowerShell.

También se puede arrancar directamente:

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

## Comprobaciones

```powershell
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m ruff check .
```

`GET /health` devuelve `{"status":"ok"}`. La configuración inicial mantiene el
modo de prueba, limita las pruebas a 10 fotografías, no permite eliminar
originales, requiere confirmación manual y no ejecuta migraciones automáticas.

## Estructura

- `app/domain`: modelos y puertos de dominio.
- `app/application`: servicios y casos de uso.
- `app/infrastructure`: adaptadores futuros.
- `app/presentation`: API, plantillas y recursos estáticos.
- `app/config.py`: configuración.
- `docs/`: arquitectura y progreso.

Bootstrap 5 y HTMX se sirven desde archivos locales; la interfaz no depende de
CDN ni realiza conexiones externas. Las secciones distintas de Inicio son
marcadores no disponibles y no se guardan credenciales en esta fase.
