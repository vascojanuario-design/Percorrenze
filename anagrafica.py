"""Utenti, ruoli, cantieri e mezzi.

I dati stanno nell'archivio, accanto alle gite:
    anagrafica/utenti.json   utenti con password cifrata (mai in chiaro)
    anagrafica/flotte.json   cantieri e mezzi

Una gita appartiene a un cantiere e a un mezzo (campi "cantiere" e "mezzo" in meta.json);
un mezzo può avere più gite, distinte da numero, turno e giorni.
"""
from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import uuid

RUOLI = {
    "amministratore": "Amministratore",
    "responsabile": "Responsabile di cantiere",
    "operatore": "Operatore",
}
TIPI_MEZZO = ["Compattatore posteriore", "Compattatore laterale", "Vasca", "Porter / mezzo leggero",
              "Lavastrade", "Spazzatrice", "Altro"]
TURNI = ["Mattina", "Pomeriggio", "Notte"]
GIORNI = ["Lun", "Mar", "Mer", "Gio", "Ven", "Sab", "Dom"]

UTENTI_VUOTO = {"utenti": {}}
FLOTTE_VUOTO = {"cantieri": {}, "mezzi": {}}
ITERAZIONI = 200_000


def nuovo_id(prefisso: str) -> str:
    return f"{prefisso}-{uuid.uuid4().hex[:8]}"


# ---------------------------------------------------------------- password

def cifra(password: str, sale: str | None = None) -> dict:
    sale = sale or secrets.token_hex(16)
    h = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(sale), ITERAZIONI).hex()
    return {"sale": sale, "hash": h, "metodo": f"pbkdf2-sha256-{ITERAZIONI}"}


def verifica(password: str, dati: dict) -> bool:
    try:
        return hmac.compare_digest(cifra(password, dati["sale"])["hash"], dati["hash"])
    except (KeyError, ValueError):
        return False


def controlla_password(password: str) -> None:
    if len(password) < 8:
        raise ValueError("La password deve avere almeno 8 caratteri")


def controlla_nome_utente(nome: str) -> str:
    nome = (nome or "").strip().lower()
    if not re.fullmatch(r"[a-z0-9._-]{3,40}", nome):
        raise ValueError("Nome utente non valido: da 3 a 40 caratteri tra lettere minuscole, numeri, punto, trattino")
    return nome


# ---------------------------------------------------------------- accesso

def accedi(utenti_doc: dict, admin_cfg: dict | None, utente: str, password: str) -> dict | None:
    """Restituisce i dati della sessione se le credenziali sono giuste, altrimenti None.

    L'amministratore definito nei Secrets vale sempre: serve per il primo avvio
    e come accesso di emergenza se nessun altro amministratore può entrare.
    """
    utente = (utente or "").strip().lower()
    if admin_cfg and utente and utente == str(admin_cfg.get("utente", "")).strip().lower():
        if hmac.compare_digest(password.encode(), str(admin_cfg.get("password", "")).encode()) and admin_cfg.get("password"):
            return {"utente": utente, "nome": admin_cfg.get("nome", "Amministratore"), "ruolo": "amministratore",
                    "cantieri": [], "da_secrets": True}
        return None
    u = utenti_doc.get("utenti", {}).get(utente)
    if u and u.get("attivo", True) and verifica(password, u.get("password", {})):
        return sessione(utente, u)
    return None


def sessione(utente: str, u: dict) -> dict:
    return {"utente": utente, "nome": u.get("nome") or utente, "ruolo": u.get("ruolo", "operatore"),
            "cantieri": list(u.get("cantieri", [])), "da_secrets": False}


def rinfresca(utenti_doc: dict, chi: dict) -> dict | None:
    """Rilegge l'utente a ogni pagina: se è stato disattivato o ha cambiato ruolo, vale subito."""
    if chi.get("da_secrets"):
        return chi
    u = utenti_doc.get("utenti", {}).get(chi["utente"])
    if not u or not u.get("attivo", True):
        return None
    return sessione(chi["utente"], u)


# ---------------------------------------------------------------- modifiche utenti

def crea_utente(doc: dict, utente: str, nome: str, ruolo: str, cantieri: list[str], password: str) -> None:
    utente = controlla_nome_utente(utente)
    if utente in doc["utenti"]:
        raise ValueError(f"Esiste già un utente '{utente}'")
    if ruolo not in RUOLI:
        raise ValueError("Ruolo non valido")
    controlla_password(password)
    doc["utenti"][utente] = {"nome": nome.strip() or utente, "ruolo": ruolo, "cantieri": list(cantieri),
                             "attivo": True, "password": cifra(password)}


def aggiorna_utente(doc: dict, utente: str, nome: str, ruolo: str, cantieri: list[str], attivo: bool,
                    nuova_password: str = "") -> None:
    u = doc["utenti"].get(utente)
    if not u:
        raise ValueError(f"L'utente '{utente}' non esiste")
    if ruolo not in RUOLI:
        raise ValueError("Ruolo non valido")
    u.update({"nome": nome.strip() or utente, "ruolo": ruolo, "cantieri": list(cantieri), "attivo": bool(attivo)})
    if nuova_password:
        controlla_password(nuova_password)
        u["password"] = cifra(nuova_password)


def cambia_password(doc: dict, utente: str, attuale: str, nuova: str) -> None:
    u = doc["utenti"].get(utente)
    if not u or not verifica(attuale, u.get("password", {})):
        raise ValueError("La password attuale non è corretta")
    controlla_password(nuova)
    u["password"] = cifra(nuova)


# ---------------------------------------------------------------- flotte

def cantieri_visibili(flotte: dict, chi: dict) -> list[str]:
    tutti = sorted(flotte["cantieri"], key=lambda c: flotte["cantieri"][c]["nome"].lower())
    if chi["ruolo"] == "amministratore":
        return tutti
    return [c for c in tutti if c in chi["cantieri"]]


def mezzi_del_cantiere(flotte: dict, cantiere: str, solo_attivi: bool = False) -> list[str]:
    ids = [m for m, v in flotte["mezzi"].items() if v.get("cantiere") == cantiere
           and (v.get("attivo", True) or not solo_attivi)]
    return sorted(ids, key=lambda m: _ordinabile(flotte["mezzi"][m]["codice"]))


def _ordinabile(codice: str):
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", str(codice))]


def etichetta_mezzo(flotte: dict, mezzo: str | None) -> str:
    v = flotte["mezzi"].get(mezzo or "")
    if not v:
        return "Senza mezzo"
    return f"{v['codice']}" + (f" ({v['tipo']})" if v.get("tipo") else "")


def leggi_giorni(testo) -> list[str]:
    """'lun mer ven', 'Lun-Sab', 'tutti' → elenco ordinato di giorni."""
    if isinstance(testo, list):
        testo = " ".join(map(str, testo))
    t = (str(testo or "")).strip().lower()
    if not t:
        return []
    if t in ("tutti", "tutti i giorni", "sempre"):
        return list(GIORNI)
    chiavi = [g.lower() for g in GIORNI]
    scelti: set[int] = set()
    for parte in re.split(r"[,\s;/]+", t):
        if not parte:
            continue
        m = re.fullmatch(r"([a-zì]{3})[a-zì]*-([a-zì]{3})[a-zì]*", parte)
        if m and m.group(1) in chiavi and m.group(2) in chiavi:
            a, b = chiavi.index(m.group(1)), chiavi.index(m.group(2))
            scelti.update(range(a, b + 1) if a <= b else list(range(a, 7)) + list(range(0, b + 1)))
            continue
        if parte[:3] in chiavi:
            scelti.add(chiavi.index(parte[:3]))
        else:
            raise ValueError(f"Giorno non riconosciuto: '{parte}'. Usa per esempio 'Lun Mer Ven' o 'Lun-Sab'")
    return [GIORNI[i] for i in sorted(scelti)]


def scrivi_giorni(giorni: list[str] | None) -> str:
    g = list(giorni or [])
    if g == GIORNI:
        return "Tutti i giorni"
    if g == GIORNI[:6]:
        return "Lun-Sab"
    if g == GIORNI[:5]:
        return "Lun-Ven"
    return " ".join(g)


def salva_cantieri(flotte: dict, righe: list[dict], gite_per_cantiere: dict[str, int]) -> None:
    """Righe dalla tabella dei cantieri: {id, Nome, Rimessa}. Rimessa come 'lat, lon' o vuota."""
    visti = set()
    nuovi = {}
    for r in righe:
        nome = str(r.get("Nome") or "").strip()
        if not nome:
            continue
        cid = r.get("id") or nuovo_id("cantiere")
        rimessa = None
        testo = str(r.get("Rimessa") or "").strip()
        if testo:
            try:
                lat, lon = [float(x) for x in testo.replace(";", ",").split(",")]
                rimessa = [round(lat, 6), round(lon, 6)]
            except ValueError:
                raise ValueError(f"Rimessa di '{nome}': scrivi le coordinate come '43.8102, 11.1433'") from None
        nuovi[cid] = {"nome": nome, "rimessa": rimessa}
        visti.add(cid)
    for cid in flotte["cantieri"]:
        if cid not in visti:
            n_mezzi = len(mezzi_del_cantiere(flotte, cid))
            if n_mezzi or gite_per_cantiere.get(cid):
                nome = flotte["cantieri"][cid]["nome"]
                raise ValueError(f"Il cantiere '{nome}' ha ancora mezzi o gite: spostali prima di eliminarlo")
    flotte["cantieri"] = nuovi


def salva_mezzi(flotte: dict, cantiere: str, righe: list[dict], gite_per_mezzo: dict[str, int]) -> None:
    """Righe dalla tabella dei mezzi di un cantiere: {id, Codice, Targa, Tipo, Attivo}."""
    codici = set()
    visti = set()
    for r in righe:
        codice = str(r.get("Codice") or "").strip()
        if not codice:
            continue
        if codice.lower() in codici:
            raise ValueError(f"Il codice mezzo '{codice}' è ripetuto")
        codici.add(codice.lower())
        mid = r.get("id") or nuovo_id("mezzo")
        flotte["mezzi"][mid] = {"codice": codice, "targa": str(r.get("Targa") or "").strip().upper(),
                                "tipo": r.get("Tipo") or "", "cantiere": cantiere,
                                "attivo": bool(r.get("Attivo", True))}
        visti.add(mid)
    for mid in mezzi_del_cantiere(flotte, cantiere):
        if mid not in visti:
            if gite_per_mezzo.get(mid):
                raise ValueError(f"Il mezzo '{flotte['mezzi'][mid]['codice']}' ha ancora gite assegnate: "
                                 "spostale o disattiva il mezzo invece di eliminarlo")
            del flotte["mezzi"][mid]
