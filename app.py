"""Servidor mínimo de voz: recibe texto, devuelve MP3 generado con Edge TTS.
Solo depende de edge-tts. Variables de entorno opcionales:
  TOKEN    -> si la defines, las peticiones deben llevar la cabecera X-Token con ese valor
  ORIGINS  -> orígenes permitidos separados por comas (por defecto *)
  PORT     -> lo pone Render
"""
import asyncio, json, os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import edge_tts

TOKEN = os.environ.get("TOKEN", "")
ORIGINS = [o.strip() for o in os.environ.get("ORIGINS", "*").split(",") if o.strip()]
VOZ_FIJA = "es-ES-AlvaroNeural"
MAX_CHARS = 700


async def sintetizar(texto, voz, velocidad):
    com = edge_tts.Communicate(texto, voz, rate=velocidad)
    audio = bytearray()
    async for trozo in com.stream():
        if trozo["type"] == "audio":
            audio += trozo["data"]
    if len(audio) < 200:
        raise RuntimeError("Edge TTS no devolvió audio")
    return bytes(audio)


def sintetizar_con_reintentos(texto, voz, velocidad):
    ultimo = None
    for intento in range(1, 4):
        try:
            return asyncio.run(sintetizar(texto, voz, velocidad))
        except Exception as e:  # noqa: BLE001
            ultimo = e
            if intento < 3:
                import time
                time.sleep(intento * 1.5)
    raise RuntimeError(f"Edge TTS falló tras 3 intentos: {ultimo}")


class H(BaseHTTPRequestHandler):
    def _cors(self):
        origen = self.headers.get("Origin", "")
        permitido = "*" if "*" in ORIGINS else (origen if origen in ORIGINS else "")
        if permitido:
            self.send_header("Access-Control-Allow-Origin", permitido)
            self.send_header("Vary", "Origin")
        self.send_header("Access-Control-Allow-Headers", "content-type, x-token")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")

    def _json(self, code, obj):
        b = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code); self._cors()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)

    def do_OPTIONS(self):
        self.send_response(204); self._cors(); self.end_headers()

    def do_GET(self):
        if self.path.startswith("/health"):
            return self._json(200, {"ok": True, "voz": VOZ_FIJA})
        self._json(404, {"error": "No existe"})

    def do_POST(self):
        if not self.path.startswith("/tts"):
            return self._json(404, {"error": "No existe"})
        if TOKEN and self.headers.get("X-Token", "") != TOKEN:
            return self._json(401, {"error": "Token incorrecto"})
        try:
            n = int(self.headers.get("Content-Length", "0"))
            datos = json.loads(self.rfile.read(min(n, 20000)) or b"{}")
            texto = str(datos.get("texto", "")).strip()
            voz = str(datos.get("voz") or VOZ_FIJA)
            vel = str(datos.get("velocidad") or "+0%")
            if not texto:
                return self._json(400, {"error": "Falta el texto"})
            if len(texto) > MAX_CHARS:
                return self._json(400, {"error": f"Texto demasiado largo (máx. {MAX_CHARS})"})
            if not voz.startswith("es-") or not vel.replace("%", "").lstrip("+-").isdigit():
                return self._json(400, {"error": "Voz o velocidad no válidas"})
            audio = sintetizar_con_reintentos(texto, voz, vel)
        except Exception as e:  # noqa: BLE001
            return self._json(502, {"error": str(e)[:300]})
        self.send_response(200); self._cors()
        self.send_header("Content-Type", "audio/mpeg")
        self.send_header("Content-Length", str(len(audio))); self.end_headers(); self.wfile.write(audio)

    def log_message(self, fmt, *a):
        print("%s %s" % (self.address_string(), fmt % a), flush=True)


if __name__ == "__main__":
    puerto = int(os.environ.get("PORT", "8000"))
    print(f"Servidor de voz en el puerto {puerto}", flush=True)
    ThreadingHTTPServer(("0.0.0.0", puerto), H).serve_forever()
