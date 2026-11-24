# Synology Photos API: observaciones y estado

## Alcance y confianza

La interfaz web observada usa APIs internas de Synology Photos. No existe aquí
una garantía oficial de compatibilidad para estos contratos. La observación se
hizo en una sesión DSM real autenticada manualmente y fue de solo lectura; no
se descargaron originales ni se modificaron datos. Los identificadores y
valores de cuenta se omiten.

`SYNO.API.Info` de DSM es el mecanismo oficial de descubrimiento de APIs. En
esta sesión se consultó en `/webapi/entry.cgi`; las rutas y versiones se deben
tomar dinámicamente de la respuesta, no fijarse por versión DSM.

## Llamadas observadas

| API / recurso | Método HTTP y operación | Parámetros observados | Resultado / uso |
|---|---|---|---|
| `SYNO.Foto.Browse.SimilarTimeline` v1 | `POST`, `get` | `timeline_group_unit` como JSON serializado (por ejemplo, `"day"`) | Grupos temporales con secciones y cantidades. |
| `SYNO.Foto.Browse.SimilarItem` v1 | `POST`, `list` | `offset`, `limit`, `start_time`, `end_time`, `additional` | Elementos multimedia paginados. Se consultó una página limitada a 50. |
| `SYNO.Foto.Browse.Album` hasta v5 | `POST`, `list` | `offset`, `limit` | Álbumes personales. El contenido observado se pidió con `SYNO.Foto.Browse.Item.list` y `album_id`. |
| `SYNO.Foto.Browse.Item` hasta v6 | `POST`, `list` | `offset`, `limit`, `additional`; `album_id` para contenido del álbum | Elementos y contenido de carpetas/álbumes según la vista. |
| `SYNO.Foto.Browse.Folder` hasta v2 | `POST`, `list` | API anunciada dinámicamente; parámetros concretos pueden variar | Exploración de carpetas, aún pendiente de validación en PhotoBridge. |
| `SYNO.Foto.Thumbnail` hasta v2 | `GET` a `/synofoto/api/v2/p/Thumbnail/get` | `id`, `cache_key`, `type=unit`, `size`, `SynoToken` | Respuesta de miniatura de imagen. El token y la cookie se mantienen en el backend. |
| `SYNO.Foto.Download` hasta v2 | Contrato de descarga no investigado | No se inició ninguna descarga | No se considera una capacidad de descarga validada. |

El parámetro `additional` observado se serializó como JSON con campos como
`thumbnail`, `resolution`, `orientation`, `video_convert`, `video_meta` y
`address`. Los elementos observados contenían `id`, `filename`, `filesize`,
`folder_id`, `owner_user_id`, `time`, `indexed_time`, `type` y `additional`.
La respuesta de la página consultada incluyó fotografías y vídeos, pero no un
total global. `additional.thumbnail.cache_key` permite solicitar miniaturas;
`additional.resolution` y `additional.video_meta` pueden contener dimensiones
y duración.

La lista general se consultó mediante `SimilarItem.list`; no se usa
`list_similar` para enumerar la biblioteca porque esa variante refleja
agrupaciones de elementos similares. La llamada de observación usó un rango
temporal amplio y un límite de 50, no una indexación ni descarga masiva.

## Sesión y seguridad

El navegador DSM envió la cookie de sesión y cabeceras relacionadas con el
token DSM. PhotoBridge reutiliza su sesión HTTP autenticada; las cookies y
`SynoToken` permanecen en el servidor. La consulta de miniatura observada
funcionó con la sesión y `X-Syno-Token`. DSM también envió `X-Syno-Hash` en el
navegador; no se ha determinado su generación ni se afirma que PhotoBridge lo
necesite. No se incluyen credenciales, cookies, tokens, SID ni datos personales
en este documento.

## Implementación PhotoBridge y límites

- El adaptador Photos comparte cliente HTTP, QuickConnect y autenticación DSM
  con el conector existente; File Station sigue disponible por separado.
- El acceso a Photos se habilita tras una consulta personal o compartida de
  solo lectura satisfactoria, no únicamente por la presencia de una entrada en
  `SYNO.API.Info`.
- El listado inicial usa páginas máximas de 50; se muestran fotos y vídeos,
  fechas reportadas por Photos, tamaño, extensión y resolución disponible.
  Los filtros de nombre, extensión y tipo se aplican sobre los elementos
  devueltos en la página actual; no se recorre toda la biblioteca. Las fechas
  delimitan la consulta paginada y no se sustituyen por fechas de modificación.
- Las miniaturas se transmiten desde el backend y no exponen sesión al
  navegador. Una miniatura solo se declara accesible tras una respuesta de
  imagen con contenido.
- Los vídeos son de visualización solamente: la selección y descarga de
  originales desde PhotoBridge sigue limitada a formatos de fotografía.
- Aunque `SYNO.Foto.Download` se anuncia, su contrato no fue probado ni se
  inició una descarga. La descarga de originales Photos se mantiene marcada
  como no validada/no disponible en el diagnóstico.
- Espacio compartido, carpetas, álbumes, expiración de sesión y la operación
  completa de PhotoBridge requieren validación manual del usuario. La
  observación del sitio DSM no equivale a validar esta aplicación.

