"""Strade e importazioni.

- instrada(): tratto che segue le strade tra due punti, con OpenRouteService (profilo mezzi pesanti).
  Serve una chiave gratuita di openrouteservice.org nei secrets:  [openrouteservice]  chiave = "..."
- leggi_tabella(): gite da Excel o CSV con le coordinate dei punti.
"""
from __future__ import annotations

import io
import re
import unicodedata

import pandas as pd

import os

# Il servizio è passato su api.heigit.org; il vecchio indirizzo resta come riserva.
ORS_URLS = [os.environ["PERCORSI_ORS_URL"]] if os.environ.get("PERCORSI_ORS_URL") else [
    "https://api.heigit.org/openrouteservice/v2/directions/{profilo}/geojson",
    "https://api.openrouteservice.org/v2/directions/{profilo}/geojson",
]


class ErroreStrade(Exception):
    pass


def instrada(chiave: str, da: list[float], a: list[float], profilo: str = "driving-hgv") -> list[list[float]]:
    """Restituisce i punti [lat, lon] lungo le strade da `da` ad `a` (entrambi [lat, lon])."""
    import requests

    if not chiave:
        raise ErroreStrade("Aggancio alle strade non configurato: manca la chiave di OpenRouteService")
    corpo = {"coordinates": [[da[1], da[0]], [a[1], a[0]]], "radiuses": [80, 80], "instructions": False}
    r, ultimo_errore = None, None
    for url in ORS_URLS:
        try:
            r = requests.post(url.format(profilo=profilo), json=corpo, timeout=20,
                              headers={"Authorization": chiave, "Content-Type": "application/json"})
        except Exception as e:  # rete non raggiungibile: si prova l'indirizzo successivo
            ultimo_errore, r = e, None
            continue
        if r.status_code in (404, 502, 503) and "routable" not in r.text and url != ORS_URLS[-1]:
            continue
        break
    if r is None:
        raise ErroreStrade(f"Servizio delle strade non raggiungibile ({ultimo_errore})")
    if r.status_code == 404 or (r.status_code == 400 and "routable" in r.text):
        raise ErroreStrade("Nessuna strada trovata vicino a uno dei due punti")
    if r.status_code == 403:
        raise ErroreStrade("Chiave di OpenRouteService non valida")
    if r.status_code == 429:
        raise ErroreStrade("Raggiunto il limite giornaliero di richieste di OpenRouteService")
    if r.status_code >= 400:
        raise ErroreStrade(f"OpenRouteService ha risposto {r.status_code}")
    try:
        coords = r.json()["features"][0]["geometry"]["coordinates"]
    except (KeyError, IndexError, ValueError):
        raise ErroreStrade("Risposta non valida dal servizio delle strade") from None
    return [[round(c[1], 6), round(c[0], 6)] for c in coords]


# ---------------------------------------------------------------- Excel / CSV

def _colonna(colonne: list[str], *modelli: str) -> str | None:
    for m in modelli:
        for c in colonne:
            if re.fullmatch(m, c.strip().lower()):
                return c
    return None


def leggi_tabella(contenuto: bytes, nome_file: str) -> list[dict]:
    """Legge un Excel o CSV di punti e restituisce le gite: [{nome, punti, waypoint}].

    Colonne riconosciute (maiuscole e minuscole indifferenti):
      latitudine:  lat, latitudine, latitude, y, ycoord
      longitudine: lon, lng, longitudine, longitude, x, xcoord
      gita (facoltativa): gita, nome, percorso, giro   -> una gita per ogni valore diverso
      ordine (facoltativa): ordine, progressivo, n, sequenza
      tipo (facoltativa): raccolta / trasferimento
      lato (facoltativa): destro / sinistro / entrambi
      nota (facoltativa): testo di un punto d'interesse in quel punto
    """
    nome_lower = nome_file.lower()
    try:
        if nome_lower.endswith((".xlsx", ".xlsm", ".xls")):
            df = pd.read_excel(io.BytesIO(contenuto))
        else:
            testo = contenuto.decode("utf-8-sig", errors="replace")
            sep = ";" if testo.count(";") > testo.count(",") else ","
            df = pd.read_csv(io.StringIO(testo), sep=sep)
    except Exception as e:
        raise ValueError(f"{nome_file}: file non leggibile ({e})") from None
    colonne = [str(c) for c in df.columns]
    df.columns = colonne
    c_lat = _colonna(colonne, r"lat", r"latitudine", r"latitude", r"y", r"ycoord", r"y coord")
    c_lon = _colonna(colonne, r"lon", r"lng", r"long", r"longitudine", r"longitude", r"x", r"xcoord", r"x coord")
    if not c_lat or not c_lon:
        if _colonna(colonne, r"via", r"indirizzo", r"strada", r".*indirizzo.*"):
            raise ValueError(f"{nome_file}: il file contiene indirizzi ma non coordinate. Per ora servono le "
                             "colonne di latitudine e longitudine (vedi la guida all'import da Excel).")
        raise ValueError(f"{nome_file}: non trovo le colonne di latitudine e longitudine")
    c_gita = _colonna(colonne, r"gita", r"nome", r"nome gita", r"percorso", r"giro")
    c_ord = _colonna(colonne, r"ordine", r"progressivo", r"n", r"n\.", r"nr", r"sequenza", r"seq")
    c_tipo = _colonna(colonne, r"tipo", r"tipo tratto")
    c_lato = _colonna(colonne, r"lato", r"lato strada", r"lato raccolta")
    c_nota = _colonna(colonne, r"nota", r"note", r"punto", r"punto d'interesse", r"descrizione")

    def numero(v):
        if isinstance(v, str):
            v = v.strip().replace(",", ".")
        return float(v)

    gruppi: dict[str, list] = {}
    base = re.sub(r"\.[^.]+$", "", nome_file)
    for i, r in df.iterrows():
        try:
            lat, lon = numero(r[c_lat]), numero(r[c_lon])
        except (ValueError, TypeError):
            continue
        if pd.isna(lat) or pd.isna(lon):
            continue
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            raise ValueError(f"{nome_file}: coordinate fuori scala alla riga {i + 2}")
        if 5 < lat < 20 and 35 < lon < 50:  # colonne invertite (tipico di X/Y)
            lat, lon = lon, lat
        nome = str(r[c_gita]).strip() if c_gita and not pd.isna(r[c_gita]) else base
        ordine = numero(r[c_ord]) if c_ord and not pd.isna(r[c_ord]) else i
        tipo = "t" if c_tipo and str(r[c_tipo]).strip().lower().startswith("tras") else "r"
        lato = {"d": "d", "s": "s", "e": "e"}.get(str(r[c_lato]).strip().lower()[:1], "") if c_lato and not pd.isna(r[c_lato]) else ""
        nota = str(r[c_nota]).strip() if c_nota and not pd.isna(r[c_nota]) else ""
        gruppi.setdefault(nome, []).append((ordine, lat, lon, tipo, lato, nota))
    gite = []
    for nome, righe in gruppi.items():
        righe.sort(key=lambda x: x[0])
        punti = [[lat, lon, tipo, lato] for _, lat, lon, tipo, lato, _ in righe]
        wp = [{"lat": lat, "lon": lon, "tipo": "nota", "testo": nota} for _, lat, lon, _, _, nota in righe if nota]
        if len(punti) >= 2:
            gite.append({"nome": nome, "punti": punti, "waypoint": wp})
    if not gite:
        raise ValueError(f"{nome_file}: nessuna gita con almeno due punti validi")
    return gite


# ---------------------------------------------------------------- elenco di vie (senza coordinate)

GEO_URL = os.environ.get("PERCORSI_GEOCODER_URL", "https://photon.komoot.io/api/")
NOMINATIM_URL = os.environ.get("PERCORSI_NOMINATIM_URL", "https://nominatim.openstreetmap.org/search")
UA = {"User-Agent": "PortalePercorsi-Cristoforo/1.0 (gestione percorsi di raccolta)"}


def _norm(t) -> str:
    t = unicodedata.normalize("NFKD", str(t or "")).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", " ", t).strip()


def leggi_elenco_vie(contenuto: bytes, nome_file: str) -> dict | None:
    """Se il file è un elenco di vie senza coordinate restituisce {nome, vie: [{via, comune, cap}]}, altrimenti None."""
    try:
        if nome_file.lower().endswith((".xlsx", ".xlsm", ".xls")):
            grezzo = pd.read_excel(io.BytesIO(contenuto), header=None, dtype=str)
        else:
            testo = contenuto.decode("utf-8-sig", errors="replace")
            sep = ";" if testo.count(";") > testo.count(",") else ","
            grezzo = pd.read_csv(io.StringIO(testo), header=None, sep=sep, dtype=str)
    except Exception:
        return None
    riga_int = None
    for i in range(min(len(grezzo), 15)):
        celle = [_norm(c) for c in grezzo.iloc[i].tolist()]
        if any(c in ("via", "indirizzo", "strada", "nome via") for c in celle):
            riga_int = i
            break
    if riga_int is None:
        return None
    intest = [_norm(c) for c in grezzo.iloc[riga_int].tolist()]
    if any(c in ("lat", "latitudine", "latitude", "y", "ycoord", "lon", "lng", "longitudine", "longitude", "x", "xcoord")
           for c in intest):
        return None
    def col(*nomi):
        for n in nomi:
            if n in intest:
                return intest.index(n)
        return None
    c_via = col("via", "indirizzo", "strada", "nome via")
    c_com, c_cap = col("comune", "citta", "localita"), col("cap")
    titolo = ""
    for i in range(riga_int):
        valori = [str(v).strip() for v in grezzo.iloc[i].tolist() if not pd.isna(v) and str(v).strip()]
        if valori:
            titolo = valori[0]
    vie = []
    for i in range(riga_int + 1, len(grezzo)):
        r = grezzo.iloc[i].tolist()
        via = r[c_via] if c_via is not None and c_via < len(r) else None
        if via is None or pd.isna(via) or not str(via).strip():
            continue
        via = str(via).replace("\u2019", "'").replace("\u2018", "'").strip()
        comune = str(r[c_com]).strip() if c_com is not None and not pd.isna(r[c_com]) else ""
        cap = str(r[c_cap]).strip().split(".")[0] if c_cap is not None and not pd.isna(r[c_cap]) else ""
        vie.append({"via": via, "comune": comune, "cap": cap})
    if not vie:
        return None
    return {"nome": titolo or re.sub(r"\.[^.]+$", "", nome_file), "vie": vie}


def geocodifica_via(via: str, comune: str, cap: str = "", vicino: list[float] | None = None) -> list[float] | None:
    """Posizione [lat, lon] della via nel comune indicato (Photon, poi Nominatim). None se non trovata."""
    import requests

    via_n, com_n = _norm(via), _norm(comune)
    parametri = {"q": f"{via}, {comune}".strip(", "), "limit": 8}
    if vicino:
        parametri.update(lat=round(vicino[0], 5), lon=round(vicino[1], 5))
    try:
        r = requests.get(GEO_URL, params=parametri, headers=UA, timeout=15)
        candidati = []
        for f in r.json().get("features", []):
            pr = f.get("properties", {})
            luogo = _norm(" ".join(str(pr.get(k, "")) for k in ("city", "county", "district", "locality", "state")))
            nome = _norm(pr.get("name") or pr.get("street") or "")
            punti = (2 if com_n and com_n in luogo else 0) + (2 if nome and (nome in via_n or via_n in nome) else 0) \
                + (1 if pr.get("osm_key") == "highway" else 0)
            lon, lat = f["geometry"]["coordinates"][:2]
            candidati.append((punti, lat, lon))
        candidati = [c for c in candidati if c[0] >= 3]
        if candidati:
            _, lat, lon = max(candidati, key=lambda c: c[0])
            return [round(lat, 6), round(lon, 6)]
    except Exception:
        pass
    try:
        q = {"format": "json", "limit": 1, "street": via, "city": comune, "country": "Italia"}
        if cap:
            q["postalcode"] = cap
        r = requests.get(NOMINATIM_URL, params=q, headers=UA, timeout=15)
        dati = r.json()
        if dati:
            return [round(float(dati[0]["lat"]), 6), round(float(dati[0]["lon"]), 6)]
    except Exception:
        pass
    return None


def costruisci_da_vie(elenco: dict, chiave_ors: str, avanzamento=None) -> tuple[list, list, list]:
    """Trova le vie e le collega nell'ordine lungo le strade. Restituisce (punti, waypoint, vie_non_trovate)."""
    import time

    trovate, non_trovate = [], []
    vicino = None
    for k, v in enumerate(elenco["vie"], 1):
        if avanzamento:
            avanzamento(k, len(elenco["vie"]), v["via"])
        pos = geocodifica_via(v["via"], v["comune"], v["cap"], vicino)
        if pos:
            trovate.append((v["via"], pos))
            vicino = pos
        else:
            non_trovate.append(v["via"])
        time.sleep(0.3)
    punti: list = []
    waypoint = [{"lat": p[0], "lon": p[1], "tipo": "nota", "testo": f"{n} (n. {i} dell'elenco)"}
                for i, (n, p) in enumerate(trovate, 1)]
    for i in range(len(trovate) - 1):
        da, a = trovate[i][1], trovate[i + 1][1]
        try:
            tratto = instrada(chiave_ors, da, a) if chiave_ors else [da, a]
        except ErroreStrade:
            tratto = [da, a]
        tratto = [[p[0], p[1], "r", ""] for p in tratto]
        punti.extend(tratto if not punti else tratto[1:])
    return punti, waypoint, non_trovate
