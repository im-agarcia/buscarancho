# Buscarancho

Busca propiedades en varios portales tres veces por día (8:00, 12:00 y 18:00 de Argentina), se queda con las que cumplen un filtro y avisa solo las novedades: avisos nuevos, cambios de precio y bajas.

## Cómo funciona

1. **GitHub Actions** ([buscar.yml](.github/workflows/buscar.yml)) corre `python -m buscarancho` en cada horario.
2. Cada portal de [buscarancho/sources/](buscarancho/sources) devuelve sus avisos en un formato común.
3. [matching.py](buscarancho/matching.py) aplica el mismo filtro a todos. Si la tarjeta no aclara cochera, balcón o baños, abre la ficha del aviso y lo busca en el texto.
4. [store.py](buscarancho/store.py) compara contra `data/listings.json` (el historial, versionado en el repo) y detecta las novedades.
5. Si hay novedades se abre un **issue** con el resumen (GitHub lo manda por mail y a la app) y, si está configurado, un mensaje de Telegram.
6. Opcional: un **panel en Cloudflare** ([web/](web)) con el formulario de filtros y el listado de resultados.

El mismo departamento publicado en dos portales (misma dirección y precio) se muestra una sola vez, con un link a cada uno.

## Portales

| Portal | Estado |
| --- | --- |
| MercadoLibre | funciona |
| RE/MAX | funciona (API pública del sitio) |
| Mudafy | funciona |
| Cabaprop | funciona (buscador público del sitio) |
| Century 21 | funciona |
| BuscadorProp | funciona |
| iCasas | funciona; agregador: no informa dirección ni cochera/balcón en la tarjeta, y filtra por dormitorios en vez de ambientes |
| Argenprop | funciona con pocos pedidos; si recibe muchos seguidos responde con un desafío anti-bot y esa corrida lo saltea |
| Zonaprop, Properati | no incluidos: bloquean el acceso automatizado y no se intenta evadirlo. Ambos ofrecen alertas por mail propias |

Un portal que falla o bloquea no frena a los demás: figura con ❌ en el resumen y sus avisos no se dan de baja.

## Filtros

Sin panel, se editan en [filters.json](filters.json):

| Campo | Significado |
| --- | --- |
| `operacion`, `tipo` | `venta` / `alquiler`; `departamento` / `casa` / `ph` |
| `barrios` | lista de barrios de CABA |
| `ambientes_min`, `ambientes_max` | `ambientes_max: null` = sin tope |
| `banos_min` | mínimo de baños |
| `precio_min`, `precio_max`, `moneda` | los avisos publicados en otra moneda se descartan |
| `cochera`, `balcon` | exigir que el aviso los mencione |
| `incluir_sin_confirmar` | `true` incluye también los avisos que no aclaran cochera/balcón, marcados como "sin confirmar" |
| `fuentes` | portales a consultar; vacío = todos |

Con el panel configurado (`PANEL_URL`), los filtros guardados en el formulario tienen prioridad sobre este archivo.

## Uso local

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m buscarancho --dry-run            # no guarda ni notifica
.venv/bin/python -m buscarancho --only remax,mudafy  # solo algunos portales
```

## Agregar un portal

Crear `buscarancho/sources/<portal>.py` con una subclase de `Source` que defina `name`, `label` y `search(filtros)`, devolviendo objetos `Listing`. Se registra sola. No hace falta que `search()` filtre con precisión: alcanza con acotar por zona y precio, el filtro final es común. Ver [remax.py](buscarancho/sources/remax.py) como ejemplo corto.

## Panel en Cloudflare (opcional)

```bash
cd web
npx wrangler login
npx wrangler kv namespace create KV      # pegar el id en wrangler.toml
npx wrangler secret put PANEL_TOKEN      # clave del formulario
npx wrangler deploy
```

Después, en el repo de GitHub: variable `PANEL_URL` (la URL del Worker) y secreto `PANEL_TOKEN` (la misma clave).

## Telegram (opcional)

Secretos `TELEGRAM_BOT_TOKEN` y `TELEGRAM_CHAT_ID` en el repo.
