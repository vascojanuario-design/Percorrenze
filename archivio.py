"""Archivio delle gite su disco.

Struttura:
    <cartella dati>/gite/<id>/meta.json   dati della gita e storico versioni
    <cartella dati>/gite/<id>/v001.gpx    una versione per file, mai sovrascritta

Ogni modifica avviene sotto lock, con scrittura atomica (file temporaneo + rename),
quindi più persone possono inviare correzioni contemporaneamente senza corrompere i dati.
"""
from __future__ import annotations

import hashlib
import io
import json
import math
import os
import re
import unicodedata
import uuid
import zipfile
from datetime import datetime
from pathlib import Path
from xml.etree import ElementTree as ET
from xml.sax.saxutils import escape

from filelock import FileLock

Punto = list  # [lat, lon, tipo] con tipo "r" (raccolta) o "t" (trasferimento)


class Conflitto(Exception):
    """La gita è stata modificata da qualcun altro dopo che la bozza è stata iniziata."""

    def __init__(self, versione_attuale: int):
        super().__init__(versione_attuale)
        self.versione_attuale = versione_attuale


# ---------------------------------------------------------------- GPX

def _locale(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def leggi_gpx(contenuto: bytes, nome_file: str = "") -> tuple[str, list[Punto]]:
    """Restituisce (nome, punti). Legge tracce (trk) o, in mancanza, rotte (rte)."""
    try:
        radice = ET.fromstring(contenuto)
    except ET.ParseError as e:
        raise ValueError(f"{nome_file}: non è un GPX leggibile ({e})") from None

    punti: list[Punto] = []
    for seg in (el for el in radice.iter() if _locale(el.tag) == "trkseg"):
        tipo = "r"
        for el in seg.iter():
            if _locale(el.tag) == "tipo" and (el.text or "").strip() == "trasferimento":
                tipo = "t"
        for p in (el for el in seg if _locale(el.tag) == "trkpt"):
            punti.append([float(p.get("lat")), float(p.get("lon")), tipo])
    if not punti:
        for p in (el for el in radice.iter() if _locale(el.tag) == "rtept"):
            punti.append([float(p.get("lat")), float(p.get("lon")), "r"])
    if len(punti) < 2:
        raise ValueError(f"{nome_file}: il file non contiene una traccia")

    nome = ""
    for el in radice.iter():
        if _locale(el.tag) == "name" and (el.text or "").strip():
            nome = el.text.strip()
            break
    return nome or Path(nome_file).stem, punti


def distanza(a: Punto, b: Punto) -> float:
    r = math.pi / 180
    dl, dn = (b[0] - a[0]) * r, (b[1] - a[1]) * r
    x = math.sin(dl / 2) ** 2 + math.cos(a[0] * r) * math.cos(b[0] * r) * math.sin(dn / 2) ** 2
    return 2 * 6371000 * math.asin(math.sqrt(x))


def pulisci(punti: list[Punto]) -> tuple[list[Punto], int]:
    """Toglie i punti doppi consecutivi (meno di 0,5 m). Il tipo del tratto successivo si conserva."""
    out: list[Punto] = []
    rimossi = 0
    for p in punti:
        if out and distanza(out[-1], p) < 0.5:
            out[-1][2] = p[2]
            rimossi += 1
            continue
        out.append([round(p[0], 6), round(p[1], 6), p[2] if p[2] in ("r", "t") else "r"])
    return out, rimossi


def lunghezze(punti: list[Punto]) -> dict:
    racc = trasf = 0.0
    for a, b in zip(punti, punti[1:]):
        d = distanza(a, b)
        if a[2] == "t":
            trasf += d
        else:
            racc += d
    return {"km_tot": round((racc + trasf) / 1000, 2), "km_raccolta": round(racc / 1000, 2),
            "km_trasferimento": round(trasf / 1000, 2)}


def scrivi_gpx(nome: str, punti: list[Punto], descrizione: str = "") -> str:
    """GPX 1.1 con un trkseg per ogni tratto omogeneo e il tipo nelle estensioni."""
    righe = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<gpx version="1.1" creator="Percorsi" xmlns="http://www.topografix.com/GPX/1/1" xmlns:p="urn:percorsi:1">',
        f"  <metadata><name>{escape(nome)}</name><desc>{escape(descrizione)}</desc>"
        f"<time>{datetime.now().astimezone().isoformat(timespec='seconds')}</time></metadata>",
        f"  <trk><name>{escape(nome)}</name>",
    ]
    inizio = 0
    for i in range(1, len(punti)):
        fine_tratto = i == len(punti) - 1 or punti[i][2] != punti[inizio][2]
        if fine_tratto:
            tipo = "trasferimento" if punti[inizio][2] == "t" else "raccolta"
            righe.append(f"    <trkseg><extensions><p:tipo>{tipo}</p:tipo></extensions>")
            for p in punti[inizio:i + 1]:
                righe.append(f'      <trkpt lat="{p[0]:.6f}" lon="{p[1]:.6f}"/>')
            righe.append("    </trkseg>")
            inizio = i
    righe += ["  </trk>", "</gpx>", ""]
    return "\n".join(righe)


def _slug(testo: str) -> str:
    t = unicodedata.normalize("NFKD", testo).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", t.lower()).strip("-")[:40] or "gita"


# ---------------------------------------------------------------- archivio

class Archivio:
    def __init__(self, cartella: Path):
        self.root = Path(cartella)
        self.gite = self.root / "gite"
        self.gite.mkdir(parents=True, exist_ok=True)
        self.lock = FileLock(str(self.root / ".lock"), timeout=30)

    # --- lettura

    def _meta_path(self, gid: str) -> Path:
        if not re.fullmatch(r"[a-z0-9-]+", gid):
            raise ValueError("Identificativo gita non valido")
        return self.gite / gid / "meta.json"

    def meta(self, gid: str) -> dict:
        return json.loads(self._meta_path(gid).read_text(encoding="utf-8"))

    def elenco(self, archiviate: bool = False) -> list[dict]:
        out = []
        for f in sorted(self.gite.glob("*/meta.json")):
            m = json.loads(f.read_text(encoding="utf-8"))
            if bool(m.get("archiviata")) == archiviate:
                out.append(m)
        return sorted(out, key=lambda m: m["nome"].lower())

    def punti(self, gid: str, n: int | None = None) -> list[Punto]:
        m = self.meta(gid)
        v = m["versioni"][-1] if n is None else next(v for v in m["versioni"] if v["n"] == n)
        _, pts = leggi_gpx((self.gite / gid / v["file"]).read_bytes(), v["file"])
        return pts

    def gpx(self, gid: str, n: int) -> str:
        m = self.meta(gid)
        v = next(v for v in m["versioni"] if v["n"] == n)
        return (self.gite / gid / v["file"]).read_text(encoding="utf-8")

    def impronta(self) -> str:
        """Cambia ogni volta che una gita viene creata, modificata o archiviata."""
        h = hashlib.sha1()
        for f in sorted(self.gite.glob("*/meta.json")):
            h.update(f.read_bytes())
        return h.hexdigest()[:16]

    def vuoto(self) -> bool:
        return not any(self.gite.glob("*/meta.json"))

    # --- scrittura

    @staticmethod
    def _scrivi(path: Path, testo: str) -> None:
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(testo, encoding="utf-8")
        os.replace(tmp, path)

    def _aggiungi_versione(self, m: dict, punti: list[Punto], autore: str, nota: str, nonce: str | None = None) -> dict:
        n = m["versioni"][-1]["n"] + 1 if m["versioni"] else 1
        file = f"v{n:03d}.gpx"
        cartella = self.gite / m["id"]
        self._scrivi(cartella / file, scrivi_gpx(m["nome"], punti, f"Versione {n}: {nota}"))
        v = {"n": n, "file": file, "data": datetime.now().astimezone().isoformat(timespec="seconds"),
             "autore": autore, "nota": nota, "nome": m["nome"], "punti": len(punti), **lunghezze(punti)}
        if nonce:
            v["invio"] = nonce
        m["versioni"].append(v)
        self._scrivi(cartella / "meta.json", json.dumps(m, ensure_ascii=False, indent=2))
        return v

    def crea(self, nome: str, punti: list[Punto], autore: str, nota: str, nonce: str | None = None) -> str:
        punti, _ = pulisci(punti)
        if len(punti) < 2:
            raise ValueError("Una gita deve avere almeno due punti")
        with self.lock:
            gid = f"{_slug(nome)}-{uuid.uuid4().hex[:6]}"
            (self.gite / gid).mkdir()
            m = {"id": gid, "nome": nome.strip() or "Gita senza nome", "creata": datetime.now().astimezone().isoformat(timespec="seconds"),
                 "creata_da": autore, "archiviata": False, "versioni": []}
            self._aggiungi_versione(m, punti, autore, nota, nonce)
        return gid

    def salva(self, gid: str, punti: list[Punto], autore: str, nota: str, base: int, nome: str | None = None,
              nonce: str | None = None) -> int:
        """Salva una nuova versione. Rifiuta se nel frattempo qualcuno ha inviato una versione più recente."""
        punti, _ = pulisci(punti)
        if len(punti) < 2:
            raise ValueError("Una gita deve avere almeno due punti")
        with self.lock:
            m = self.meta(gid)
            attuale = m["versioni"][-1]["n"]
            if base != attuale:
                raise Conflitto(attuale)
            if nome and nome.strip():
                m["nome"] = nome.strip()
            return self._aggiungi_versione(m, punti, autore, nota, nonce)["n"]

    def ripristina(self, gid: str, n: int, autore: str) -> int:
        punti = self.punti(gid, n)
        with self.lock:
            m = self.meta(gid)
            return self._aggiungi_versione(m, punti, autore, f"Ripristinata la versione {n}")["n"]

    def archivia(self, gid: str, autore: str, archiviata: bool = True) -> None:
        with self.lock:
            m = self.meta(gid)
            m["archiviata"] = archiviata
            m.setdefault("eventi", []).append({"data": datetime.now().astimezone().isoformat(timespec="seconds"),
                                              "autore": autore, "azione": "archiviata" if archiviata else "riattivata"})
            self._scrivi(self._meta_path(gid), json.dumps(m, ensure_ascii=False, indent=2))

    # --- esportazione

    def zip_ultime(self) -> bytes:
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            for m in self.elenco():
                v = m["versioni"][-1]
                z.writestr(f"{_slug(m['nome'])}_v{v['n']}.gpx", self.gpx(m["id"], v["n"]))
        return buf.getvalue()

    def semina(self, cartella: Path, autore: str = "importazione iniziale") -> int:
        """Importa i GPX di una cartella se l'archivio è vuoto. Restituisce quante gite ha creato."""
        if not self.vuoto() or not Path(cartella).is_dir():
            return 0
        n = 0
        for f in sorted(Path(cartella).glob("*.gpx")):
            nome, pts = leggi_gpx(f.read_bytes(), f.name)
            pts, rimossi = pulisci(pts)
            self.crea(nome, pts, autore, f"Importata da {f.name}" + (f", rimossi {rimossi} punti doppi" if rimossi else ""))
            n += 1
        return n
