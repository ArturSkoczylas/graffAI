# Zasady przygotowania plików – Drukarnia Gutenberg

Źródło: <https://gutenberg-drukarnia.pl/jak-przygotowac-projekt-do-druku/> (stan z 25.10.2026).
Wartości liczbowe są w `skills/margin-check/rules.yaml`. Ten plik to streszczenie dla zespołu.

## Wspólne dla wszystkich produktów

- **Spady**: 2,5 mm z każdej strony (przedłużenie tła i grafik). Przy cięciu możliwe
  przesunięcia 1–2 mm.
- **Spady niewymagane**, jeśli żaden element nie dochodzi do krawędzi.
- **Ważne elementy** (teksty, rebusy, grafiki widoczne w całości): min. 3 mm od krawędzi
  cięcia i od linii bigu.
- **Ramki**: min. 5 mm od krawędzi cięcia i od bigów lub zgięć.
- **Formaty plików**: pdf, tiff, jpg, ai, eps. W plikach wektorowych teksty zamienione
  na krzywe albo dołączone fonty.
- Nie układać prac na arkuszach – osobne pliki dla każdego projektu (przód i tył osobno).

## Produkty

| Produkt | Format netto | Plik ze spadami | DPI |
|---|---|---|---|
| Wizytówka | 90×50 / 85×55 mm (dowolny inny też) | 95×55 / 90×60 mm | **600** |
| Ulotka/plakat jednokartkowy | np. A5 148×210 | 153×215 | 300 |
| Ulotka składana (rozkładówka) | np. A4 297×210 → DL 99×210 | 302×215 | 300 |
| Zaproszenie jednokartkowe | np. 120×170 | 125×175 | 300 |
| Zaproszenie składane (rozkładówka) | np. 280×140 → 140×140 | 285×145 | 300 |

Produkty składane: rozkładówka (strona zewnętrzna 4–1, wewnętrzna 2–3). Przy zaproszeniach
otwieranych do góry strona 4 jest obrócona o 180°.

## Canva

- Rozmiar strony = format docelowy. Produkty składane jako rozkładówki.
- Plik → Linijki i prowadnice → **Pokaż spady drukarskie**. Tło i zdjęcia dochodzące do
  krawędzi wychodzą poza czarną linię.
- Pobieranie: **PDF do druku (CMYK)** z opcją „**Znaczniki przycięcia i spady**”.
- Albo **link do współpracy**: Udostępnij → „Każda osoba, która ma link” + „Może edytować”.
- Wizytówki: zalecane udostępnienie linku, bo domyślne wizytówki w Canvie mają za niską
  rozdzielczość i niestandardowy format.
- Zaproszenia personalizowane: każdy gość na powielonej stronie. Udostępnić projekt
  **przed** personalizacją.

## Poza zakresem sprawdzania marginesów (do innych modułów)

- Uszlachetnienia (złocenie, srebrzenie, lakier): 3 pliki – podkład, maska efektu, wizualizacja.
- Tonery specjalne (biały, złoty, srebrny): kanał spot `White` / `Special`.
- Grawer: wektor, czarny R0 G0 B0.
- Zaproszenia personalizowane: wielostronicowy PDF.

## Otwarte pytania do drukarni

- Spady i DPI dla wielkiego formatu (banery, płótna, fototapety, plakaty > A3)?
- Czy przyjmować PNG? Instrukcja go nie wymienia.
- Czy spad większy niż 2,5 mm (np. 3 mm z innych programów) jest akceptowany?
