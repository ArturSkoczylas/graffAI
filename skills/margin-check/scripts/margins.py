"""Silnik sprawdzania marginesów, spadów i ramek dla plików do druku.

Działa na rastrze RGB (numpy) o znanej geometrii, dzięki czemu tę samą logikę
mogą wykorzystać wszystkie źródła:
  * pliki graficzne (JPG/PNG/TIFF) – patrz check_image.py,
  * PDF – po rasteryzacji strony z BleedBox/TrimBox (źródło 1),
  * Canva – po eksporcie do PDF.

Konwencje:
  * wymiary w mm, odległości mierzone od linii cięcia (formatu netto);
    wartości dodatnie = do środka projektu, ujemne = w spadzie,
  * "product" to słownik z rules.yaml uzupełniony o domyślne wartości.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional

import numpy as np
import yaml

MM_PER_INCH = 25.4
SEGMENT_MM = 10.0          # długość odcinka krawędzi analizowanego osobno

# Progi analizy pikseli (0–255, skala szarości)
WHITE_LEVEL = 235          # piksel jaśniejszy = papier (brak farby)
EDGE_T = 35                # różnica sąsiednich pikseli uznawana za krawędź obiektu
LINE_T = 25                # j.w. dla wykrywania cienkich linii (ramek)
LINE_FRACTION = 0.55       # część długości boku, którą musi pokrywać linia ramki
ELEMENT_DENSITY = 0.012    # gęstość krawędzi w pasie, od której uznajemy, że jest tam element

SEVERITY_ORDER = {"BŁĄD": 0, "OSTRZEŻENIE": 1, "SPRAWDŹ": 2, "INFO": 3}
SIDE_NAMES = {"top": "Górna", "bottom": "Dolna", "left": "Lewa", "right": "Prawa"}
SIDE_LOC = {"top": "górnej", "bottom": "dolnej", "left": "lewej", "right": "prawej"}


def fmt(x: float) -> str:
    """Liczba po polsku: przecinek dziesiętny, bez zbędnych zer."""
    return f"{x:.1f}".rstrip("0").rstrip(".").replace(".", ",") if x != int(x) else str(int(x))


# --------------------------------------------------------------------------- #
# Reguły i produkty
# --------------------------------------------------------------------------- #
def default_rules_path() -> Path:
    return Path(__file__).resolve().parent.parent / "rules.yaml"


def load_rules(path: Optional[Path] = None) -> dict:
    with open(path or default_rules_path(), encoding="utf-8") as fh:
        return yaml.safe_load(fh)


@dataclass
class Product:
    id: str
    name: str
    trim_w: float
    trim_h: float
    bleed_mm: float
    safe_mm: float
    frame_mm: float
    min_dpi: int
    folds_x: list = field(default_factory=list)   # pionowe bigi (mm od lewej krawędzi netto)
    folds_y: list = field(default_factory=list)   # poziome bigi (mm od górnej krawędzi netto)

    def rotated(self) -> "Product":
        return Product(self.id, self.name, self.trim_h, self.trim_w, self.bleed_mm,
                       self.safe_mm, self.frame_mm, self.min_dpi,
                       folds_x=list(self.folds_y), folds_y=list(self.folds_x))


def get_product(rules: dict, product_id: Optional[str] = None,
                trim: Optional[tuple] = None, min_dpi: Optional[int] = None,
                folds: Optional[list] = None) -> Product:
    """Zwraca produkt z rules.yaml albo produkt niestandardowy (trim=(w, h) w mm)."""
    d = rules["defaults"]
    if product_id:
        if product_id not in rules["products"]:
            known = ", ".join(sorted(rules["products"]))
            raise KeyError(f"Nieznany produkt '{product_id}'. Dostępne: {known}")
        p = rules["products"][product_id]
        tw, th = p["trim_mm"]
        name = p.get("name", product_id)
        dpi = p.get("min_dpi", d["min_dpi"])
        fx = list(p.get("folds_mm", []))
        pid = product_id
    elif trim:
        tw, th = trim
        name = f"Format niestandardowy {tw:g}×{th:g} mm"
        dpi = d["min_dpi"]
        fx = []
        pid = "custom"
    else:
        raise ValueError("Podaj produkt (product_id) albo format netto (trim).")
    if min_dpi:
        dpi = min_dpi
    if folds:
        fx = list(folds)
    return Product(pid, name, float(tw), float(th), float(d["bleed_mm"]),
                   float(d["safe_mm"]), float(d["frame_mm"]), int(dpi), folds_x=fx)


# --------------------------------------------------------------------------- #
# Geometria pliku: czy ma spady i jaka jest rzeczywista rozdzielczość
# --------------------------------------------------------------------------- #
@dataclass
class Layout:
    px_w: int
    px_h: int
    dpi_x: float
    dpi_y: float
    bleed_mm: float              # rzeczywisty spad w pliku (0 = brak spadów)
    rotated: bool                # produkt obrócony do orientacji pliku
    method: str                  # "metadata" | "aspect" | "given"
    ambiguous: bool = False
    aspect_error: float = 0.0

    @property
    def dpi(self) -> float:
        return (self.dpi_x + self.dpi_y) / 2

    @property
    def has_bleed(self) -> bool:
        return self.bleed_mm > 0.05


def _aspect_err(px_w, px_h, w_mm, h_mm) -> float:
    return abs((px_w / px_h) / (w_mm / h_mm) - 1.0)


def detect_layout(px_w: int, px_h: int, product: Product,
                  meta_dpi: Optional[tuple] = None) -> tuple:
    """Ustala, czy plik ma format netto czy netto + spady, oraz jego realne DPI.

    Zwraca (Layout | None, Product dopasowany do orientacji pliku).
    None oznacza, że proporcje pliku nie pasują do produktu.
    """
    prod = product
    rotated = False
    if (px_w > px_h) != (product.trim_w > product.trim_h) and product.trim_w != product.trim_h:
        prod = product.rotated()
        rotated = True

    b = prod.bleed_mm
    hyps = [b, 0.0]

    # 1) Metadane DPI – wiarygodne tylko, jeśli dają fizyczny rozmiar zgodny z hipotezą.
    if meta_dpi and meta_dpi[0] and meta_dpi[1] and meta_dpi[0] > 1 and meta_dpi[1] > 1:
        phys_w = px_w / meta_dpi[0] * MM_PER_INCH
        phys_h = px_h / meta_dpi[1] * MM_PER_INCH
        bx = (phys_w - prod.trim_w) / 2
        by = (phys_h - prod.trim_h) / 2
        # spad symetryczny w zakresie 0–10 mm, z tolerancją 0,6 mm
        if -0.6 <= bx <= 10 and -0.6 <= by <= 10 and abs(bx - by) <= 0.6:
            bleed = max(0.0, round((bx + by) / 2, 1))
            if bleed < 0.3:
                bleed = 0.0
            w = prod.trim_w + 2 * bleed
            h = prod.trim_h + 2 * bleed
            return Layout(px_w, px_h, px_w / (w / MM_PER_INCH), px_h / (h / MM_PER_INCH),
                          bleed, rotated, "metadata",
                          aspect_error=_aspect_err(px_w, px_h, w, h)), prod

    # 2) Proporcje boków (gdy brak metadanych lub są błędne, np. domyślne 72 dpi).
    scored = []
    for bl in hyps:
        w = prod.trim_w + 2 * bl
        h = prod.trim_h + 2 * bl
        scored.append((_aspect_err(px_w, px_h, w, h), bl, w, h))
    scored.sort()
    err, bl, w, h = scored[0]
    if err > 0.01:
        return None, prod
    ambiguous = scored[1][0] < 0.004 and (scored[1][0] - err) < 0.002
    return Layout(px_w, px_h, px_w / (w / MM_PER_INCH), px_h / (h / MM_PER_INCH),
                  bl, rotated, "aspect", ambiguous=ambiguous, aspect_error=err), prod


def layout_from_known(px_w: int, px_h: int, product: Product, bleed_mm: float) -> Layout:
    """Dla źródeł ze znaną geometrią (np. PDF z BleedBox/TrimBox po rasteryzacji)."""
    w = product.trim_w + 2 * bleed_mm
    h = product.trim_h + 2 * bleed_mm
    return Layout(px_w, px_h, px_w / (w / MM_PER_INCH), px_h / (h / MM_PER_INCH),
                  bleed_mm, False, "given")


def suggest_products(rules: dict, px_w: int, px_h: int) -> list:
    """Produkty z rules.yaml, do których plik pasuje proporcjami (z lub bez spadów)."""
    out = []
    b = rules["defaults"]["bleed_mm"]
    for pid, p in rules["products"].items():
        tw, th = p["trim_mm"]
        for (a, c) in ((tw, th), (th, tw)):
            for bl in (b, 0.0):
                if _aspect_err(px_w, px_h, a + 2 * bl, c + 2 * bl) < 0.004:
                    out.append(p.get("name", pid))
                    break
            else:
                continue
            break
    return sorted(set(out))


# --------------------------------------------------------------------------- #
# Wyniki
# --------------------------------------------------------------------------- #
@dataclass
class Finding:
    severity: str                # BŁĄD | OSTRZEŻENIE | SPRAWDŹ | INFO
    code: str
    message: str
    side: Optional[str] = None
    range_mm: Optional[tuple] = None      # zakres wzdłuż boku (mm od początku boku netto)
    distance_mm: Optional[float] = None   # odległość od linii cięcia / bigu
    boxes_px: list = field(default_factory=list)  # obszary do zaznaczenia na podglądzie

    def to_dict(self) -> dict:
        d = asdict(self)
        d.pop("boxes_px", None)
        return {k: v for k, v in d.items() if v is not None}


# --------------------------------------------------------------------------- #
# Analiza rastra
# --------------------------------------------------------------------------- #
@dataclass
class _Side:
    name: str
    nw: np.ndarray       # maska "jest farba"
    edge: np.ndarray     # maska krawędzi (wszystkie kierunki)
    line: np.ndarray     # maska krawędzi równoległych do boku
    fmask: np.ndarray    # maska wykrytych ramek (zapisywalny widok)
    off: float           # px od krawędzi pliku do linii cięcia (w poprzek boku)
    ppm: float           # px/mm w poprzek boku
    ppm_along: float
    a0: int              # zakres formatu netto wzdłuż boku (px)
    a1: int


def _views(arr: np.ndarray, side: str) -> np.ndarray:
    """Widok tablicy obrócony tak, że dany bok jest "na górze" (wiersz 0 = krawędź pliku)."""
    if side == "top":
        return arr
    if side == "bottom":
        return arr[::-1]
    if side == "left":
        return arr.swapaxes(0, 1)
    if side == "right":
        return arr.swapaxes(0, 1)[::-1]
    raise ValueError(side)


def _band(side: _Side, view: np.ndarray, d0: float, d1: float,
          a0: Optional[int] = None, a1: Optional[int] = None) -> np.ndarray:
    r0 = int(round(side.off + d0 * side.ppm))
    r1 = int(round(side.off + d1 * side.ppm))
    r0 = max(0, min(view.shape[0], r0))
    r1 = max(0, min(view.shape[0], r1))
    if r1 <= r0:
        r1 = min(view.shape[0], r0 + 1)
    return view[r0:r1, (side.a0 if a0 is None else a0):(side.a1 if a1 is None else a1)]


def _segments(a0: int, a1: int, ppm_along: float) -> list:
    seg = max(4, int(round(SEGMENT_MM * ppm_along)))
    edges = list(range(a0, a1, seg))
    return [(s, min(s + seg, a1)) for s in edges if min(s + seg, a1) - s > seg * 0.3]


def _merge(segs: list) -> list:
    """Łączy przylegające odcinki (s, e, payload) w zakresy."""
    out = []
    for s, e, p in sorted(segs, key=lambda t: t[0]):
        if out and s <= out[-1][1] + 1:
            out[-1][1] = e
            out[-1][2].append(p)
        else:
            out.append([s, e, [p]])
    return out


def _side_box(side: _Side, shape, d0_px: int, d1_px: int, s: int, e: int) -> tuple:
    """Prostokąt (x0, y0, x1, y1) w układzie oryginalnego obrazu dla pasa w widoku boku."""
    H, W = shape
    if side.name == "top":
        return (s, d0_px, e, d1_px)
    if side.name == "bottom":
        return (s, H - d1_px, e, H - d0_px)
    if side.name == "left":
        return (d0_px, s, d1_px, e)
    return (W - d1_px, s, W - d0_px, e)


def _gray(rgb: np.ndarray) -> np.ndarray:
    return (rgb[..., 0] * 0.299 + rgb[..., 1] * 0.587 + rgb[..., 2] * 0.114).astype(np.float32)


def analyze_raster(rgb: np.ndarray, layout: Layout, product: Product) -> list:
    """Główna analiza. rgb: uint8 (H, W, 3). Zwraca listę Finding."""
    H, W = rgb.shape[:2]
    findings: list = []
    ppm_x = layout.dpi_x / MM_PER_INCH
    ppm_y = layout.dpi_y / MM_PER_INCH
    bl = layout.bleed_mm
    bx = bl * ppm_x
    by = bl * ppm_y
    trim_px = (bx, by, W - bx, H - by)

    gray = _gray(rgb)
    nw = rgb.min(axis=2) < WHITE_LEVEL
    gx = np.zeros_like(gray)
    gy = np.zeros_like(gray)
    gx[:, 1:] = np.abs(np.diff(gray, axis=1))
    gy[1:, :] = np.abs(np.diff(gray, axis=0))
    edge = (gx > EDGE_T) | (gy > EDGE_T)
    hline = gy > LINE_T        # krawędzie linii poziomych
    vline = gx > LINE_T        # krawędzie linii pionowych
    frame_mask = np.zeros((H, W), dtype=bool)

    sides = []
    for name in ("top", "bottom", "left", "right"):
        horiz = name in ("top", "bottom")
        off = by if horiz else bx
        ppm = ppm_y if horiz else ppm_x
        ppm_al = ppm_x if horiz else ppm_y
        a0 = int(round(bx if horiz else by))
        a1 = int(round((W - bx) if horiz else (H - by)))
        sides.append(_Side(name, _views(nw, name), _views(edge, name),
                           _views(hline if horiz else vline, name),
                           _views(frame_mask, name), off, ppm, ppm_al, a0, a1))

    # ---- 1. Spady / elementy przy krawędzi ------------------------------------
    edge_content_sides = {}
    for sd in sides:
        bad = []
        for s, e in _segments(sd.a0, sd.a1, sd.ppm_along):
            if layout.has_bleed:
                inner = _band(sd, sd.nw, 0.3, 1.2, s, e).mean()
                outer = _band(sd, sd.nw, -bl + 0.3, -0.3, s, e).mean()
                if inner > 0.5 and outer < 0.15:
                    bad.append((s, e, None))
            else:
                at_edge = _band(sd, sd.nw, 0.0, 0.7, s, e).mean()
                if at_edge > 0.3:
                    bad.append((s, e, None))
        if bad:
            edge_content_sides[sd.name] = bad
            for s, e, _ in _merge(bad):
                r = _mm_range(sd, s, e)
                if layout.has_bleed:
                    msg = (f"{SIDE_NAMES[sd.name]} krawędź, {r[0]:g}–{r[1]:g} mm: grafika/tło "
                           f"kończy się na linii cięcia i nie wchodzi w spad – po cięciu "
                           f"może zostać biała linia.")
                    code = "BLEED_NOT_FILLED"
                else:
                    msg = (f"{SIDE_NAMES[sd.name]} krawędź, {r[0]:g}–{r[1]:g} mm: elementy "
                           f"dochodzą do krawędzi, a plik nie ma spadów "
                           f"(potrzebne {fmt(product.bleed_mm)} mm z każdej strony).")
                    code = "NO_BLEED_CONTENT_AT_EDGE"
                d1 = int(round(sd.off + 1.2 * sd.ppm))
                d0 = int(round(max(0, sd.off - bl * sd.ppm)))
                findings.append(Finding("BŁĄD", code, msg, sd.name, r,
                                        boxes_px=[_side_box(sd, (H, W), d0, d1, s, e)]))

    if not layout.has_bleed and not edge_content_sides:
        findings.append(Finding("INFO", "NO_BLEED_OK",
                                "Plik nie ma spadów, ale żaden element nie dochodzi do krawędzi – "
                                "zgodnie z zasadami drukarni spady nie są wtedy wymagane."))

    # ---- 2. Ramki ---------------------------------------------------------------
    frame_lines = {}
    for sd in sides:
        margin = int(round((product.frame_mm + 3) * sd.ppm_along))
        a0, a1 = sd.a0 + margin, sd.a1 - margin
        if a1 - a0 < 20:
            continue
        r_start = int(round(sd.off + 0.3 * sd.ppm))
        r_end = int(round(sd.off + (product.frame_mm + 3) * sd.ppm))
        r_end = min(r_end, sd.line.shape[0] // 2)
        frac = sd.line[r_start:r_end, a0:a1].mean(axis=1) if r_end > r_start else np.array([])
        rows = np.nonzero(frac > LINE_FRACTION)[0]
        if rows.size:
            first = rows[0] + r_start
            last = first
            for r in rows[1:] + r_start:      # grupa przyległych wierszy = jedna linia
                if r - last <= max(2, int(2.0 * sd.ppm)):
                    last = r
                else:
                    break
            frame_lines[sd.name] = (first, last)
            dist = (first - sd.off) / sd.ppm
            frame_lines[sd.name] = (first, last, dist)
            sd.fmask[max(0, first - 2):last + 3, :] = True

    if len(frame_lines) >= 3:
        too_close = {n: v for n, v in frame_lines.items() if v[2] < product.frame_mm - 0.25}
        if too_close:
            for n, (f, l, dist) in too_close.items():
                sd = next(s for s in sides if s.name == n)
                findings.append(Finding(
                    "OSTRZEŻENIE", "FRAME_TOO_CLOSE",
                    f"Ramka przy {SIDE_LOC[n]} krawędzi jest ok. {fmt(dist)} mm od linii cięcia "
                    f"(minimum {fmt(product.frame_mm)} mm). Przy przesunięciu cięcia o 1–2 mm "
                    f"ramka będzie wyglądała krzywo.",
                    n, distance_mm=round(dist, 1),
                    boxes_px=[_side_box(sd, (H, W), f, l + 1, sd.a0, sd.a1)]))
        else:
            dmin = min(v[2] for v in frame_lines.values())
            findings.append(Finding("INFO", "FRAME_OK",
                                    f"Wykryto ramkę – najmniejsza odległość od linii cięcia "
                                    f"ok. {fmt(dmin)} mm (min. {fmt(product.frame_mm)} mm)."))
    else:
        for n, (f, l, dist) in frame_lines.items():
            if dist < product.frame_mm - 0.25:
                sd = next(s for s in sides if s.name == n)
                findings.append(Finding(
                    "SPRAWDŹ", "LINE_NEAR_EDGE",
                    f"Linia/pas równoległy do {SIDE_LOC[n]} krawędzi, ok. {fmt(dist)} mm od "
                    f"linii cięcia. Jeśli to element ramki lub obramowania, powinien być "
                    f"min. {fmt(product.frame_mm)} mm od krawędzi.",
                    n, distance_mm=round(dist, 1),
                    boxes_px=[_side_box(sd, (H, W), f, l + 1, sd.a0, sd.a1)]))

    # ---- 3. Ważne elementy w strefie bezpieczeństwa ---------------------------
    for sd in sides:
        warn, check = [], []
        edge_bad = {(s, e) for s, e, _ in edge_content_sides.get(sd.name, [])}
        for s, e in _segments(sd.a0, sd.a1, sd.ppm_along):
            band_e = _band(sd, sd.edge, 0.4, product.safe_mm, s, e)
            band_f = _band(sd, sd.fmask, 0.4, product.safe_mm, s, e)
            em = band_e & ~band_f
            dens = em.mean() if em.size else 0.0
            if dens < ELEMENT_DENSITY:
                continue
            # najbliższy wiersz z treścią -> odległość od linii cięcia
            prof = em.mean(axis=1)
            idx = np.nonzero(prof > 0.04)[0]
            r0 = int(round(sd.off + 0.4 * sd.ppm))
            dist = ((idx[0] + r0) - sd.off) / sd.ppm if idx.size else 0.4
            if layout.has_bleed:
                ref = (_band(sd, sd.edge, -bl + 0.3, -0.3, s, e) &
                       ~_band(sd, sd.fmask, -bl + 0.3, -0.3, s, e)).mean()
                background = ref >= 0.5 * dens
            else:
                background = (s, e) in edge_bad
            (check if background else warn).append((s, e, dist))

        for bucket, sev in ((warn, "OSTRZEŻENIE"), (check, "SPRAWDŹ")):
            for s, e, dists in _merge(bucket):
                r = _mm_range(sd, s, e)
                dmin = round(min(dists), 1)
                if sev == "OSTRZEŻENIE":
                    msg = (f"{SIDE_NAMES[sd.name]} krawędź, {r[0]:g}–{r[1]:g} mm: element "
                           f"(np. tekst, logo) ok. {fmt(dmin)} mm od linii cięcia – ważne "
                           f"elementy powinny być min. {fmt(product.safe_mm)} mm od krawędzi.")
                    code = "ELEMENT_IN_SAFE_ZONE"
                else:
                    msg = (f"{SIDE_NAMES[sd.name]} krawędź, {r[0]:g}–{r[1]:g} mm: szczegółowa "
                           f"grafika przy krawędzi, ciągnąca się w spad – prawdopodobnie tło. "
                           f"Upewnij się, że nie ma tam tekstu ani elementów, które muszą "
                           f"być widoczne w całości.")
                    code = "DETAIL_NEAR_EDGE"
                d0 = int(round(sd.off))
                d1 = int(round(sd.off + product.safe_mm * sd.ppm))
                findings.append(Finding(sev, code, msg, sd.name, r, dmin,
                                        boxes_px=[_side_box(sd, (H, W), d0, d1, s, e)]))

    # ---- 4. Bigi (zgięcia) ------------------------------------------------------
    findings += _check_folds(edge, vline, hline, frame_mask, layout, product, trim_px, ppm_x, ppm_y)

    return findings


def _mm_range(sd: _Side, s: int, e: int) -> tuple:
    return (round((s - sd.a0) / sd.ppm_along), round((e - sd.a0) / sd.ppm_along))


def _check_folds(edge, vline, hline, frame_mask, layout, product, trim_px, ppm_x, ppm_y) -> list:
    out = []
    H, W = edge.shape
    x0, y0, x1, y1 = trim_px
    folds = [("x", f) for f in product.folds_x] + [("y", f) for f in product.folds_y]
    for axis, pos in folds:
        if axis == "x":
            E, L, F = edge, vline, frame_mask           # bigi pionowe: kolumny
            c = x0 + pos * ppm_x
            ppm, ppm_al = ppm_x, ppm_y
            a0, a1 = int(round(y0)), int(round(y1))
        else:
            E, L, F = edge.T, hline.T, frame_mask.T     # bigi poziome: transpozycja
            c = y0 + pos * ppm_y
            ppm, ppm_al = ppm_y, ppm_x
            a0, a1 = int(round(x0)), int(round(x1))

        def cols(d0, d1):
            c0 = int(round(c + d0 * ppm))
            c1 = int(round(c + d1 * ppm))
            return max(0, c0), min(E.shape[1], max(c1, c0 + 1))

        s_mm = product.safe_mm
        warn, check = [], []
        seg = max(4, int(round(SEGMENT_MM * ppm_al)))
        for s in range(a0, a1, seg):
            e = min(s + seg, a1)
            lc0, lc1 = cols(-s_mm, -0.5)
            rc0, rc1 = cols(0.5, s_mm)
            band = np.concatenate([E[s:e, lc0:lc1] & ~F[s:e, lc0:lc1],
                                   E[s:e, rc0:rc1] & ~F[s:e, rc0:rc1]], axis=1)
            dens = band.mean() if band.size else 0
            if dens < ELEMENT_DENSITY:
                continue
            nl = E[s:e, slice(*cols(-s_mm - 6, -s_mm))].mean()
            nr = E[s:e, slice(*cols(s_mm, s_mm + 6))].mean()
            both = nl >= 0.5 * dens and nr >= 0.5 * dens
            (check if both else warn).append((s, e, None))
        # Grafika po obu stronach bigu na większości jego długości = tło (zdjęcie, wzór).
        # Lokalny fragment po obu stronach (np. tekst przechodzący przez big) = ostrzeżenie.
        n_seg = max(1, len(range(a0, a1, seg)))
        if check and len(check) < 0.6 * n_seg:
            warn += check
            check = []
        where = "pionowy" if axis == "x" else "poziomy"
        where_gen = "pionowego" if axis == "x" else "poziomego"
        for bucket, sev, code, txt in (
            (warn, "OSTRZEŻENIE", "ELEMENT_NEAR_FOLD",
             "element (np. tekst) bliżej niż {s} mm od bigu lub na nim – na zgięciu może się złamać "
             "lub zostać przesunięty"),
            (check, "SPRAWDŹ", "DETAIL_ACROSS_FOLD",
             "grafika przechodzi przez big – sprawdź, czy to tło, a nie tekst/ważny element"),
        ):
            for s, e, _ in _merge(bucket):
                r = (round((s - a0) / ppm_al), round((e - a0) / ppm_al))
                c0, c1 = cols(-s_mm, s_mm)
                box = (c0, s, c1, e) if axis == "x" else (s, c0, e, c1)
                out.append(Finding(sev, code,
                                   f"Big {where} na {fmt(pos)} mm, odcinek {r[0]:g}–{r[1]:g} mm: "
                                   + txt.format(s=fmt(s_mm)) + ".",
                                   range_mm=r, boxes_px=[box]))

        # ramka za blisko bigu (linia na całej długości w strefie 0,7–5 mm od bigu)
        for d0, d1 in ((-product.frame_mm, -0.7), (0.7, product.frame_mm)):
            c0, c1 = cols(d0, d1)
            if c1 <= c0:
                continue
            frac = L[a0:a1, c0:c1].mean(axis=0)
            hit = np.nonzero(frac > LINE_FRACTION)[0]
            if hit.size:
                col = hit[0] + c0 if d0 > 0 else hit[-1] + c0
                dist = abs(col - c) / ppm
                box = (col - 2, a0, col + 3, a1) if axis == "x" else (a0, col - 2, a1, col + 3)
                out.append(Finding("OSTRZEŻENIE", "FRAME_NEAR_FOLD",
                                   f"Linia/ramka ok. {fmt(dist)} mm od bigu {where_gen} na {fmt(pos)} mm "
                                   f"(minimum {fmt(product.frame_mm)} mm).",
                                   distance_mm=round(dist, 1), boxes_px=[box]))
    return out


def check_resolution(layout: Layout, product: Product) -> list:
    dpi = layout.dpi
    out = []
    if dpi >= product.min_dpi * 0.98:
        out.append(Finding("INFO", "DPI_OK",
                           f"Rozdzielczość w docelowym rozmiarze: ok. {dpi:.0f} dpi "
                           f"(wymagane {product.min_dpi})."))
    elif dpi >= product.min_dpi * 0.8:
        out.append(Finding("OSTRZEŻENIE", "DPI_LOW",
                           f"Rozdzielczość ok. {dpi:.0f} dpi – nieco poniżej wymaganych "
                           f"{product.min_dpi} dpi. Druk może być lekko mniej ostry."))
    else:
        out.append(Finding("BŁĄD", "DPI_TOO_LOW",
                           f"Za niska rozdzielczość: ok. {dpi:.0f} dpi przy wymaganych "
                           f"{product.min_dpi} dpi. Na wydruku będą widoczne piksele / rozmycie."))
    return out


def overall_status(findings: list) -> str:
    sev = {f.severity for f in findings}
    if "BŁĄD" in sev:
        return "BŁĘDY"
    if "OSTRZEŻENIE" in sev:
        return "OSTRZEŻENIA"
    if "SPRAWDŹ" in sev:
        return "DO_WERYFIKACJI"
    return "OK"


def sort_findings(findings: list) -> list:
    return sorted(findings, key=lambda f: SEVERITY_ORDER.get(f.severity, 9))
