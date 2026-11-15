"""Wspólne stałe i protokół.

Host to serwer HTTP. Od wersji 1.3 protokół 2 – starsze wersje (1.2 i wcześniej, skrypty v2/v3)
nie łączą się z nową, a nowa ze starymi (MAGIC się różni, a każde zapytanie oprócz /hello musi mieć
nagłówek X-MXSync-Proto = PROTO – inaczej host odpowiada 426 „zaktualizuj MX Sync”).
  GET /hello              -> {"magic", "id", "name", "protected", "nonce"}   (bez hasła)
  GET /status             -> {"scanning", "scanned", "done", "total", ...}
  GET /index              -> {"ścieżka/względna": {"size", "hash"}}  (503 podczas skanowania)
  GET /download/<rel>     -> bajty pliku, obsługuje nagłówek Range (wznawianie)
  GET /ping?state&total&done&peer -> klient zgłasza, co robi (lista klientów u hosta)
                             i port swojego serwera P2P
  GET /peers              -> [{"name", "ip", "port"}] inni klienci udostępniający mody (P2P)
  GET /bye                -> klient się rozłącza
Hasło: nagłówek X-MXSync-Auth = HMAC-SHA256(hasło, nonce) – hasło nie idzie przez sieć.
Wykrywanie: klient wysyła UDP "MXSYNC?" (broadcast), host odpowiada JSON-em.
"""
import hashlib
import hmac

PROTO = 2
MAGIC = f"MXSYNC{PROTO}"
OLD_VERSION_MSG = "Host ma starą wersję MX Sync – musi zainstalować nową (1.3 lub nowszą)"
UPDATE_ME_MSG = "Masz starą wersję MX Sync – zainstaluj nową z GitHuba"
QUERY = b"MXSYNC?"
DISCOVERY_PORT = 50515
HTTP_PORT = 8888
PEER_PORT = 8900          # serwer P2P klienta (kolejny wolny, jeśli zajęty)
CHUNK = 256 * 1024

HDR_CLIENT = "X-MXSync-Client"
HDR_AUTH = "X-MXSync-Auth"
HDR_PROTO = "X-MXSync-Proto"


def make_proof(password, nonce):
    return hmac.new((password or "").encode("utf-8"), nonce.encode("ascii"), hashlib.sha256).hexdigest()


def parse_address(text):
    """'1.2.3.4', '1.2.3.4:9000', 'http://1.2.3.4:8888/' -> (ip, port)."""
    text = text.strip().replace("http://", "").replace("https://", "").rstrip("/")
    ip, _, port = text.partition(":")
    return ip, int(port) if port else HTTP_PORT
