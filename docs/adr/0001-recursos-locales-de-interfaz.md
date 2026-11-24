# ADR 0001: recursos locales de interfaz

- Estado: aceptada.
- Contexto: PhotoBridge debe ejecutarse únicamente en localhost y no realizar
  conexiones externas durante la fase inicial.
- Decisión: servir Bootstrap 5 y HTMX desde `app/presentation/static/vendor`,
  junto con la plantilla y los estilos de la aplicación.
- Consecuencia: la página no depende de CDN ni necesita conectividad a Internet
  al abrirse. HTMX queda disponible localmente para fases posteriores; no se
  usa para implementar lógica fuera del alcance actual.
