"""Protokół 6 (MX Sync 2.3.2) – każdy gracz jest równy: udostępnia swoje mody i pobiera od innych.

HTTP (port HTTP_PORT, kolejny wolny):
  GET /hello            -> {"magic", "proto", "id", "name", "lt", "rev", "mods", "size", "protected", "nonce"}
  GET /library          -> gzip JSON {"rev", "mods": {klucz: [infohash, rozmiar, pliki]}}
  GET /torrent/<ih>     -> plik .torrent modu
  GET /show             -> (tylko z 127.0.0.1) druga instancja prosi o pokazanie okna
  GET /reach            -> {"ok"} – próbuję połączyć się z publicznym adresem pytającego (test portu)
  GET /punch?ih=a,b     -> łączę się z publicznym adresem pytającego dla tych modów (hole punching)
/hello z poprawnym hasłem zawiera też "wan": [publiczne ip, port] (połączenia bezpośrednie, MX Sync 2.3).
Nagłówek X-MXSync-Id = id pytającego (do /reach i /punch).
Hasło grupy: nagłówek X-MXSync-Auth = HMAC-SHA256(hasło, nonce adresata) – hasło nie idzie przez sieć.
Wykrywanie (UDP DISCOVERY_PORT): b"MXSYNC6?" + JSON nadawcy -> odpowiedź JSON z /hello.
Inne wersje (b"MXSYNC?", b"MXSYNC5?" …) dostają odpowiedź, żeby zobaczyły, że trzeba zaktualizować,
ale bez wspólnego protokołu nie ma listy modów, plików .torrent ani transferów.
Transfery: libtorrent (port w polu "lt"), prywatne torrenty v2 – po jednym na mod.
"""
import hashlib
import hmac

PROTO = 6                   # 4: mod = pojedynczy plik .pkz, foldery z paczkami to grupy
                            # 5: malowania / rękawice / gogle osobno także w rozpakowanych modach
                            # 6: suma modu bez atrybutów plików (2.3.1) – starsze wersje odcięte
MAGIC = f"MXSYNC{PROTO}"
QUERY = MAGIC.encode() + b"?"
OLD_QUERY = b"MXSYNC?"
DISCOVERY_PORT = 50515
HTTP_PORT = 8888

HDR_AUTH = "X-MXSync-Auth"
HDR_NAME = "X-MXSync-Name"
HDR_PROTO = "X-MXSync-Proto"
HDR_ID = "X-MXSync-Id"


def proto_of(info):
    """Wersja protokołu z /hello albo z UDP ("proto" albo numer w "magic"); 0 – nieznana."""
    try:
        return int(info.get("proto") or str(info.get("magic", ""))[6:] or 0)
    except (TypeError, ValueError):
        return 0


def make_proof(password, nonce):
    return hmac.new((password or "").encode("utf-8"), nonce.encode("ascii"), hashlib.sha256).hexdigest()


def parse_address(text):
    """'1.2.3.4', '1.2.3.4:9000', 'http://1.2.3.4:8888/' -> (ip, port)."""
    text = text.strip().replace("http://", "").replace("https://", "").rstrip("/")
    ip, _, port = text.partition(":")
    return ip, int(port) if port else HTTP_PORT
