"""Protokół 3 (MX Sync 2.0) – każdy gracz jest równy: udostępnia swoje mody i pobiera od innych.

HTTP (port HTTP_PORT, kolejny wolny):
  GET /hello            -> {"magic", "proto", "id", "name", "lt", "rev", "mods", "size", "protected", "nonce"}
  GET /library          -> gzip JSON {"rev", "mods": {klucz: [infohash, rozmiar, pliki]}}
  GET /torrent/<ih>     -> plik .torrent modu
  GET /show             -> (tylko z 127.0.0.1) druga instancja prosi o pokazanie okna
Hasło grupy: nagłówek X-MXSync-Auth = HMAC-SHA256(hasło, nonce adresata) – hasło nie idzie przez sieć.
Wykrywanie (UDP DISCOVERY_PORT): b"MXSYNC3?" + JSON nadawcy -> odpowiedź JSON z /hello.
Stare wersje (1.x) pytają b"MXSYNC?" – odpowiadamy, żeby zobaczyły, że trzeba zaktualizować.
Transfery: libtorrent (port w polu "lt"), prywatne torrenty v2 – po jednym na mod.
"""
import hashlib
import hmac

PROTO = 4                   # 4: mod = pojedynczy plik .pkz, foldery z paczkami to grupy
MAGIC = f"MXSYNC{PROTO}"
QUERY = MAGIC.encode() + b"?"
OLD_QUERY = b"MXSYNC?"
DISCOVERY_PORT = 50515
HTTP_PORT = 8888

HDR_AUTH = "X-MXSync-Auth"
HDR_NAME = "X-MXSync-Name"
HDR_PROTO = "X-MXSync-Proto"


def make_proof(password, nonce):
    return hmac.new((password or "").encode("utf-8"), nonce.encode("ascii"), hashlib.sha256).hexdigest()


def parse_address(text):
    """'1.2.3.4', '1.2.3.4:9000', 'http://1.2.3.4:8888/' -> (ip, port)."""
    text = text.strip().replace("http://", "").replace("https://", "").rstrip("/")
    ip, _, port = text.partition(":")
    return ip, int(port) if port else HTTP_PORT
