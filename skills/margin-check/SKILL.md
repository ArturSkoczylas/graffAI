---
name: margin-check
description: Sprawdza, czy plik do druku (JPG, PNG, TIFF lub link do Canvy) ma poprawne spady, marginesy bezpieczeństwa, odsunięcie ramek, bigi i rozdzielczość według zasad Drukarni Gutenberg. Używaj, gdy klient przesyła projekt do druku albo pyta, czy jego plik jest dobrze przygotowany.
---

# Sprawdzanie marginesów i spadów (Drukarnia Gutenberg)

Twoje zadanie: ocenić, czy projekt klienta jest gotowy do druku pod względem
geometrii, i wyjaśnić klientowi prostym językiem, co ewentualnie poprawić.
**Nie poprawiasz plików klienta** – drukarnia nie ingeruje w pliki bez wyraźnej prośby.

## Zasady drukarni (pełna wersja: `rules.yaml`)

| Reguła | Wartość |
|---|---|
| Spad z każdej strony | 2,5 mm (np. A5 148×210 → plik 153×215 mm) |
| Ważne elementy (tekst, logo) od krawędzi cięcia i bigu | min. 3 mm |
| Ramki od krawędzi cięcia i bigu | min. 5 mm |
| Rozdzielczość | 300 dpi; **wizytówki 600 dpi** |
| Formaty plików | pdf, tiff, jpg, ai, eps (PNG nie jest wymieniony) |
| Spady niewymagane | gdy nic nie dochodzi do krawędzi |
| Produkty składane | jako rozkładówka, nie pojedyncze strony |

## Krok 1. Ustal produkt

Bez produktu nie da się ocenić marginesów, bo plik graficzny nie zna swojego rozmiaru w mm.
Jeśli klient nie podał, czym jest projekt (np. „ulotka A5”, „wizytówka 90×50”), zapytaj.
Listę produktów pokaże:

```bash
python scripts/check_image.py --list-products
```

Dla formatu spoza listy użyj `--trim SZERxWYS` (mm), opcjonalnie `--dpi` i `--folds` (bigi w mm od lewej).

## Krok 2a. Plik graficzny (JPG, PNG, TIFF…)

```bash
python scripts/check_image.py <plik> --product <id> --preview <katalog> [--json]
```

Skrypt:
- rozpoznaje, czy plik ma format netto, czy netto + spady, i liczy rzeczywiste DPI
  (metadane DPI bywają błędne, np. 72 – wtedy liczy z proporcji),
- sprawdza, czy tło wchodzi w spad i czy coś nie dochodzi do krawędzi bez spadów,
- wykrywa elementy w strefie 3 mm, ramki bliżej niż 5 mm i treść przy bigach,
- zapisuje podgląd `*_podglad.png` z naniesionymi liniami: czerwona = cięcie,
  zielona = strefa 3 mm, pomarańczowa = 5 mm, niebieska = big; problemy w ramkach.

Kody wyjścia: 0 OK, 1 ostrzeżenia lub do weryfikacji, 2 błędy, 3 nie da się sprawdzić.

## Krok 2b. Link do Canvy

Nie otworzysz projektu Canva z linku: wymaga logowania. Uruchom:

```bash
python scripts/canva_link.py "<link>" --product <id>
```

Skrypt sprawdzi typ linku (drukarnia potrzebuje **linku do współpracy z edycją**)
i zwróci listę kontrolną dla klienta. Jeśli klient może przesłać plik, poproś o eksport
„PDF do druku” (CMYK, „Znaczniki przycięcia i spady”) – wtedy sprawdź go jak PDF
lub poproś o JPG w pełnej rozdzielczości i przejdź do kroku 2a.

## Krok 3. Zweryfikuj wzrokowo i odpowiedz klientowi

1. **Zawsze obejrzyj podgląd** przy wynikach `SPRAWDŹ` i `OSTRZEŻENIE`. Skrypt mierzy
   piksele i nie wie, co jest tekstem, a co tłem. Twoja ocena rozstrzyga, np.:
   - `DETAIL_NEAR_EDGE` przy zdjęciu w tle – zwykle OK, jeśli przy krawędzi nie ma napisów,
   - `ELEMENT_IN_SAFE_ZONE` – sprawdź, czy to ważny element (tekst, logo) czy dekoracja,
     która może być ucięta.
2. Odpowiedz po polsku, bez żargonu. Najpierw wynik (gotowe / do poprawy), potem
   konkretne poprawki z miejscem i liczbą („numer telefonu jest 1 mm od dolnej krawędzi –
   przesuń go min. 3 mm do środka”).
3. Przy błędach spadów wyjaśnij krótko *dlaczego*: przy cięciu mogą wystąpić
   przesunięcia 1–2 mm, więc bez spadu zostaje biała linia.
4. Nie strasz informacjami `INFO` – wspominaj o nich tylko, gdy są przydatne (np. RGB).

## Ograniczenia

- Analiza zakłada białe tło papieru; na papierach kolorowych i przy kolorach
  specjalnych (biały/złoty/srebrny) wyniki traktuj orientacyjnie.
- Duże formaty (banery, płótna, plakaty > A3) nie mają jeszcze reguł – zapytaj drukarnię.
- PDF sprawdza skill `pdf-check` (`../pdf-check/scripts/check_pdf.py`) – ten sam silnik
  `scripts/margins.py` na zrasteryzowanej stronie.
