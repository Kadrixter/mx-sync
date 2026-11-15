"""Adres WAN routera przez UPnP (GetExternalIPAddress) – do wykrycia CGNAT / podwójnego routera.

Gdy router ma na WAN adres prywatny (10.x, 100.64.x, 192.168.x…) albo inny niż publiczne IP,
przekierowanie portu na nim nic nie da – przed nami jest jeszcze NAT operatora.
"""
import re
import socket
from urllib.parse import urljoin

import requests

SSDP = ("239.255.255.250", 1900)
SERVICES = ("urn:schemas-upnp-org:service:WANIPConnection:2", "urn:schemas-upnp-org:service:WANIPConnection:1",
            "urn:schemas-upnp-org:service:WANPPPConnection:1")


def _locations(timeout=2.0):
    """Adresy opisu routera z SSDP – pytamy przez każdą kartę poza VPN-em (Radmin łapie multicast)."""
    from utils.netinfo import interfaces
    found = []
    for iface in [i for i in interfaces() if not i["radmin"]] or [{"ip": ""}]:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(timeout)
        try:
            s.bind((iface["ip"], 0))
            if iface["ip"]:
                s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF, socket.inet_aton(iface["ip"]))
            for st in SERVICES:
                msg = (f"M-SEARCH * HTTP/1.1\r\nHOST: 239.255.255.250:1900\r\nMAN: \"ssdp:discover\"\r\n"
                       f"MX: 1\r\nST: {st}\r\n\r\n").encode()
                s.sendto(msg, SSDP)
            while True:
                data, _ = s.recvfrom(4096)
                m = re.search(rb"(?im)^location:\s*(\S+)", data)
                if m and m.group(1).decode() not in found:
                    found.append(m.group(1).decode())
        except OSError:
            pass
        finally:
            s.close()
    return found


def router_wan_ip():
    """Adres WAN zgłaszany przez router albo None (brak UPnP)."""
    for loc in _locations():
        try:
            xml = requests.get(loc, timeout=3).text
        except requests.RequestException:
            continue
        base = (re.search(r"<URLBase>\s*([^<]+?)\s*</URLBase>", xml) or [None, loc])[1]
        for block in re.findall(r"<service>(.*?)</service>", xml, re.S):
            st = re.search(r"<serviceType>\s*([^<]+?)\s*</serviceType>", block)
            ctl = re.search(r"<controlURL>\s*([^<]+?)\s*</controlURL>", block)
            if not st or not ctl or st.group(1) not in SERVICES:
                continue
            body = ('<?xml version="1.0"?><s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" '
                    's:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/"><s:Body>'
                    f'<u:GetExternalIPAddress xmlns:u="{st.group(1)}"/></s:Body></s:Envelope>')
            try:
                r = requests.post(urljoin(base, ctl.group(1)), data=body, timeout=3, headers={
                    "Content-Type": 'text/xml; charset="utf-8"',
                    "SOAPAction": f'"{st.group(1)}#GetExternalIPAddress"'})
            except requests.RequestException:
                continue
            m = re.search(r"<NewExternalIPAddress>\s*([0-9.]+)\s*</NewExternalIPAddress>", r.text)
            if m:
                return m.group(1)
    return None
