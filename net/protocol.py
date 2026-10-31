"""Wspólne stałe i protokół.

Host to serwer HTTP (zgodny ze starym klientem v3):
  GET /hello              -> {"magic", "id", "name", "protected", "nonce"}   (bez hasła)
  GET /status             -> {"scanning", "scanned", "done", "total", ...}
  GET /index              -> {"ścieżka/względna": {"size", "hash"}}  (503 podczas skanowania)
  GET /download/<rel>     -> bajty pliku, obsługuje nagłówek Range (wznawianie)
  GET /ping?state&total   -> klient zgłasza, co robi (lista klientów u hosta)
  GET /bye                -> klient się rozłącza
Hasło: nagłówek X-MXSync-Auth = HMAC-SHA256(hasło, nonce) – hasło nie idzie przez sieć.
Wykrywanie: klient wysyła UDP "MXSYNC?" (broadcast), host odpowiada JSON-em.
"""
import hashlib
import hmac

MAGIC = "MXSYNC1"
QUERY = b"MXSYNC?"
DISCOVERY_PORT = 50515
HTTP_PORT = 8888
CHUNK = 256 * 1024

HDR_CLIENT = "X-MXSync-Client"
HDR_AUTH = "X-MXSync-Auth"


def make_proof(password, nonce):
    return hmac.new((password or "").encode("utf-8"), nonce.encode("ascii"), hashlib.sha256).hexdigest()


def parse_address(text):
    """'1.2.3.4', '1.2.3.4:9000', 'http://1.2.3.4:8888/' -> (ip, port)."""
    text = text.strip().replace("http://", "").replace("https://", "").rstrip("/")
    ip, _, port = text.partition(":")
    return ip, int(port) if port else HTTP_PORT
