"""Strade e importazioni.

- instrada(): tratto che segue le strade tra due punti, con OpenRouteService (profilo mezzi pesanti).
  Serve una chiave gratuita di openrouteservice.org nei secrets:  [openrouteservice]  chiave = "..."
- leggi_tabella(): gite da Excel o CSV con le coordinate dei punti.
"""
from __future__ import annotations

import io
import re

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
