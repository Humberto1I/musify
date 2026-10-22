# Musify · guía para ponerla en internet y en Android

## Qué contiene el proyecto
- `server.py`: servidor (web + búsqueda con ytmusicapi + audio con Piped y respaldo entre instancias).
- `static/`: la app (página, manifest y service worker para instalarla como PWA, íconos).
- `requirements.txt`, `render.yaml`: lo que necesita el hosting.

## Probarla en tu computadora (opcional)
1. `pip install -r requirements.txt`
2. `python server.py`
3. Abre http://localhost:8000

## Paso 1 · Subir el código a GitHub
1. Crea una cuenta en github.com y un repositorio nuevo llamado `musify`.
2. Sube **el contenido** de esta carpeta (server.py, static, requirements.txt, render.yaml). En la web de GitHub: "Add file" → "Upload files".

## Paso 2 · Publicar el servidor en Render (gratis)
1. Crea una cuenta en render.com e inicia sesión con GitHub.
2. "New" → "Web Service" → elige tu repositorio `musify`.
3. Render lee `render.yaml`. Si te pide datos: Runtime = Python, Build = `pip install -r requirements.txt`, Start = `python server.py`, plan Free.
4. Al terminar te da un enlace como `https://musify-xxxx.onrender.com`. Esa es tu app en internet.
5. Cada vez que cambies algo en GitHub, Render la vuelve a publicar solo.

Nota: en el plan gratis el servidor se duerme tras ~15 minutos sin uso, y la primera visita después tarda cerca de un minuto en despertar.

## Paso 3 · Instalarla en Android (sin descargar archivos)
1. Abre tu enlace de Render en Chrome desde el celular.
2. Menú ⋮ → "Instalar app" (o "Agregar a la pantalla de inicio").
3. Queda con su ícono y se abre a pantalla completa, como una app.

## Paso 4 (opcional) · Generar un APK
1. Entra a pwabuilder.com y pega tu enlace de Render.
2. Elige "Package for stores" → Android y descarga el paquete.
3. Instala el APK en el celular (permite "instalar apps de orígenes desconocidos").

## Si Piped falla
Las instancias públicas de Piped caen seguido. En Render ve a "Environment" y crea la variable
`PIPED_INSTANCES` con enlaces separados por comas, sacados de la lista de instancias de Piped
(usa los de "API URL"). El servidor prueba uno por uno hasta que alguno responda.

## Aviso
Piped extrae audio de YouTube, lo cual va contra sus términos. Úsalo para ti o tu grupo cercano; si lo vas a
publicar para más gente, deja solo Audius y YouTube (oficial). Las tiendas de apps probablemente rechazarían la versión con Piped.

## Playlists y música sin conexión
- **Playlists:** en cada canción toca ＋ para agregarla a una playlist (o crear una nueva). En la sección «Playlists» las abres, las reproduces completas, las renombras o las eliminas. Se guardan en el navegador del dispositivo.
- **Sin conexión:** en las canciones de Audius toca ⬇ para guardarlas en el dispositivo; el ✔ indica que ya están guardadas. Aparecen en la sección «Sin conexión», que se abre sola cuando no hay internet, y también suenan dentro de tus playlists.
- Las canciones de YouTube y Piped no se pueden guardar: el reproductor de YouTube no lo permite y descargar audio de YouTube es copiar contenido protegido.
- Playlists y descargas viven en cada dispositivo; si limpias los datos del navegador o desinstalas la app, se borran.

## Funciones de la versión 3
- **Letras sincronizadas (🎤):** muestra la letra con la línea actual resaltada. Las busca en LRCLIB a través del servidor; no todas las canciones tienen letra, y si solo hay letra sin tiempos se muestra completa.
- **Ecualizador (⚙ Personalizar):** graves, medios y agudos. Solo actúa sobre Audius y música guardada, se aplica desde la siguiente canción y, si algún día Audius dejara de permitirlo, basta con ponerlo en 0.
- **Radio (📻):** al llegar al final de la cola agrega canciones parecidas. Con YouTube/Piped usa la radio de YouTube Music; con Audius busca otras canciones del mismo artista (no hay "similares" reales).
- **Para ti, Estadísticas y Descubrir:** se calculan con tu historial en este dispositivo (una escucha cuenta tras 20 s). Descubrir usa las listas de tendencias de Audius.
- **Fundido:** activable en Personalizar; baja y sube el volumen 3 s al inicio y final de cada canción (no es un cruce real entre dos canciones).
- **Temporizador (⏲), historial (Recientes) y sin conexión:** ya estaban; el temporizador cicla 15 / 30 / 60 min.
- **Pantalla de bloqueo:** el sistema muestra título, artista, carátula y botones. En Android funciona con Audius y Piped; el reproductor de YouTube incrustado suele pausarse con la pantalla apagada.
- **Importar playlists:** pega una lista «Artista - Título» o sube el CSV de Exportify (Spotify). Se busca cada canción en Audius o YouTube Music y se guardan las coincidencias (máx. 60).
- **Compartir playlists:** el botón 🔗 genera un enlace con la lista; quien lo abra puede guardarla. Va dentro del enlace, sin cuentas.
- **Buscar por letra (♪):** mejor esfuerzo, usando la búsqueda de YouTube Music; no es una búsqueda de texto completo.
- **Temas y colores:** oscuro, AMOLED y claro, con cinco colores de acento.

## Corrección importante (versión 3.1)
Se arregló un error de JavaScript que dejaba la app sin responder (no se podía cambiar de sección ni de buscador). Ahora el menú, los buscadores y todas las funciones responden, y se agregaron 3 temas nuevos (Océano, Vino, Bosque), 12 colores de acento y un selector de color personalizado en «Personalizar».
