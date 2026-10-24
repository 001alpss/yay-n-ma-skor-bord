import http.server
import json
import os
import socketserver
import sys
import threading
import time
from datetime import datetime, timedelta

import requests

TARGET_TEAMS = ("Trabzonspor",)
TAKIM = TARGET_TEAMS[0]
GUNCELLEME_SANIYE = 15
CANLI_API = "https://vd.mackolik.com/livedata?group=0"
GUNLUK_API = "https://vd.mackolik.com/livedata?date={tarih}"
TEAM_ALIASES = {
    "trabzonspor": ("trabzonspor", "trabzonspor a", "trabzonspor u21", "trabzonspor u19"),
    "samsunspor": ("samsunspor", "samsunspor a", "samsunspor u21", "samsunspor u19"),
    "fenerbahce": ("fenerbahce", "fenerbahçe", "fenerbahce a", "fenerbahçe a", "fenerbahce u21", "fenerbahçe u21"),
    "ponte preta": ("ponte preta", "ponte pretta", "pontepreta", "ponte-preta"),
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://www.mackolik.com/",
}

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
FUTBOL_KODU = 1
ALT_TAKIM_EKLERI = (" u19", " u21", " u23", " u18", " u17", " u16")

SON_MAC_VERISI = {
    "ev": "-",
    "dep": "-",
    "ev_skor": "-",
    "dep_skor": "-",
    "dakika": "-",
    "canli": False,
}


def log(mesaj):
    print(mesaj, flush=True)


def dosyalari_guncelle(veri):
    dosyalar = {
        "ev_takim.txt": veri.get("ev", "-"),
        "dep_takim.txt": veri.get("dep", "-"),
        "ev_skor.txt": veri.get("ev_skor", "-"),
        "dep_skor.txt": veri.get("dep_skor", "-"),
        "dakika.txt": veri.get("dakika", "-"),
    }
    for dosya, icerik in dosyalar.items():
        try:
            with open(os.path.join(SCRIPT_DIR, dosya), "w", encoding="utf-8") as fp:
                fp.write(str(icerik))
        except Exception as exc:
            log(f"{dosya} yazılamadı: {exc}")


def api_cek(url):
    yanit = requests.get(url, headers=HEADERS, timeout=8)
    yanit.raise_for_status()
    return yanit.json()


def maclari_topla():
    maclar = []
    gorulen = set()
    try:
        veri = api_cek(CANLI_API)
        for mac in veri.get("m", []):
            if mac[0] not in gorulen:
                gorulen.add(mac[0])
                maclar.append(mac)
    except Exception as e:
        log(f"Canlı API hatası: {e}")

    bugun = datetime.now()
    tarihler = [bugun.strftime("%d/%m/%Y"), (bugun - timedelta(days=1)).strftime("%d/%m/%Y")]
    for t in tarihler:
        try:
            veri = api_cek(GUNLUK_API.format(tarih=t))
            for mac in veri.get("m", []):
                if mac[0] not in gorulen:
                    gorulen.add(mac[0])
                    maclar.append(mac)
        except Exception as e:
            log(f"Günlük API hatası ({t}): {e}")
    return maclar


def normalize_name(metin):
    if metin is None:
        return ""
    text = str(metin).lower().strip()
    maplar = {
        "ı": "i",
        "ğ": "g",
        "ü": "u",
        "ş": "s",
        "ç": "c",
        "ö": "o",
        "-": " ",
        "_": " ",
        ".": " ",
        "'": " ",
        "/": " ",
    }
    for kaynak, hedef in maplar.items():
        text = text.replace(kaynak, hedef)
    return " ".join(text.split())


def takim_eslesir(mac, takim):
    ev = normalize_name(mac[2])
    dep = normalize_name(mac[4])
    hedefler = {normalize_name(takim)}
    key = normalize_name(takim)
    for alias in TEAM_ALIASES.get(key, ()):  # type: ignore[arg-type]
        hedefler.add(normalize_name(alias))

    for hedef in hedefler:
        if not hedef:
            continue
        if hedef in ev or hedef in dep:
            return True

        hedef_tokens = set(hedef.split())
        if hedef_tokens and (
            hedef_tokens.issubset(set(ev.split())) or hedef_tokens.issubset(set(dep.split()))
        ):
            return True

    if not any(ek in normalize_name(takim) for ek in ALT_TAKIM_EKLERI):
        if any(ek in ev or ek in dep for ek in ("u19", "u21", "u23", "u18", "u17", "u16")):
            return False
    return False


def skor_al(mac):
    ev = mac[12] if len(mac) > 12 else ""
    dep = mac[13] if len(mac) > 13 else ""
    if ev is None or ev == "" or dep is None or dep == "":
        ham = str(mac[7] or "")
        if "-" in ham:
            p = ham.split("-", 1)
            return p[0].strip(), p[1].strip()
        return "-", "-"
    return str(ev), str(dep)


def skoru_guncelle():
    global SON_MAC_VERISI
    while True:
        try:
            maclar = maclari_topla()
            adaylar = [
                m
                for m in maclar
                if len(m) > 0
                and m[-1] == FUTBOL_KODU
                and any(takim_eslesir(m, takim) for takim in TARGET_TEAMS)
            ]

            if adaylar:
                mac = adaylar[0]
                ev_s, dep_s = skor_al(mac)
                durum = str(mac[6] or "").strip()
                takimi_bul = next((takim for takim in TARGET_TEAMS if takim_eslesir(mac, takim)), TAKIM)
                SON_MAC_VERISI = {
                    "ev": mac[2],
                    "dep": mac[4],
                    "ev_skor": ev_s,
                    "dep_skor": dep_s,
                    "dakika": f"{durum}'" if durum.isdigit() else (durum or "-"),
                    "canli": durum not in {"MS", "Pen", "Uz", "İpt", "Ert", ""},
                    "takim": takimi_bul,
                }
                dosyalari_guncelle(SON_MAC_VERISI)
                log(f"[{time.strftime('%H:%M:%S')}] {takimi_bul} -> {SON_MAC_VERISI['ev']} {ev_s}-{dep_s} {SON_MAC_VERISI['dep']} ({SON_MAC_VERISI['dakika']})")
            else:
                SON_MAC_VERISI = {
                    "ev": "-",
                    "dep": "-",
                    "ev_skor": "-",
                    "dep_skor": "-",
                    "dakika": "-",
                    "canli": False,
                    "takim": TAKIM,
                }
                dosyalari_guncelle(SON_MAC_VERISI)
                log(f"[{time.strftime('%H:%M:%S')}] Hedef takımlar için maç bulunamadı: {', '.join(TARGET_TEAMS)}")
        except Exception as e:
            log(f"Hata: {e}")

        time.sleep(GUNCELLEME_SANIYE)


class OverlayHTTPRequestHandler(http.server.SimpleHTTPRequestHandler):
    def translate_path(self, path):
        if path == "/" or path == "/overlay.html":
            return os.path.join(SCRIPT_DIR, "overlay.html")
        return super().translate_path(path)

    def do_GET(self):
        if self.path == "/api/data":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(SON_MAC_VERISI).encode("utf-8"))
        else:
            super().do_GET()


def run_server():
    PORT = 8000
    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer(("", PORT), OverlayHTTPRequestHandler) as httpd:
        log(f"Web Overlay Sunucusu Başlatıldı: http://localhost:{PORT}")
        httpd.serve_forever()


if __name__ == "__main__":
    t = threading.Thread(target=skoru_guncelle, daemon=True)
    t.start()
    run_server()