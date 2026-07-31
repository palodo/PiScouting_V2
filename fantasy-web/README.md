# PiFantasy — fantasy de baloncesto FEB

App **independiente** del scouting (`frontend/`), pensada para **móvil**. Comparte el backend
FastAPI (`backend/`) pero tiene su propia cuenta de usuario, diseño y despliegue.

```powershell
# 1) backend (desde la raíz del repo)
cd backend
python -m uvicorn app.main:app --port 8000 --host 0.0.0.0

# 2) la app
cd fantasy-web
npm install
npm run dev        # http://localhost:5174  (y por IP para el móvil)
```

## Cómo funciona el juego

- **Ligas por conferencia**: se juega dentro de una competición + grupo (solo jugadores de ahí).
- **Plantilla inicial**: al entrar recibes 5 jugadores aleatorios (configurable) para poder jugar ya.
- **Mercado programado (estilo Biwenger)**: al crear la liga eliges **día de la semana + hora**
  (peninsular) y **duración**. Al abrir salen N jugadores libres al azar, repartidos por tramos
  de precio (siempre hay alguna estrella, medios y chollos).
- **Pujas a ciegas**: pujas por encima del precio de salida; ves *cuánta* gente ha pujado, no el
  importe. Al cerrar, **gana la puja más alta** (a igualdad, la primera). Los que pierden no pagan.
- **Presupuesto comprometido**: no puedes pujar más de lo que tienes sumando todas tus pujas.
- **Exclusividad**: un jugador solo lo puede tener un mánager; sale del mercado al ficharse.
- **Cláusulas de rescisión (clausulazos)**: cada jugador fichado tiene una cláusula (= su valor
  × factor, configurable al crear la liga). Otro mánager puede **llevárselo pagándola**, y el
  dinero va íntegro a su dueño. Tras fichar hay un **blindaje** de X horas (configurable) en el
  que no se le puede clausular. El dueño puede **subir la cláusula** pagando un 25 % de la subida.
- **Ficha de jugador**: toca cualquier jugador (mercado, tu plantilla o la de un rival) para ver
  todas sus estadísticas —medias, porcentajes, +/-— y su gráfico de las últimas jornadas.
- **Precios dinámicos**: suben y bajan con la valoración, la forma reciente y el +/-.
- **Puntos por jornada**: valoración (VAL) del jugador + bonus si su equipo ganó. Solo puntúan
  los 5 titulares.
- **Actividad**: feed con fichajes, ventas, aperturas/cierres de mercado y jornadas.

El creador de la liga puede **abrir/cerrar el mercado al momento** y **avanzar jornada** (la
temporada 2025/26 ya está jugada: se avanza en modo repetición).

## Notas

- El mercado se abre y cierra solo, sin tareas en segundo plano: se resuelve al vuelo en cada
  petición comparando con el reloj.
- Para el móvil: abre la web y usa *Compartir → Añadir a pantalla de inicio* (va a pantalla completa).
- ⚠️ 3ª FEB puede incluir jugadores menores de edad: úsalo en privado, no publiques la app así.
- Despliegue gratuito: ver `DEPLOY.md` en la raíz.
