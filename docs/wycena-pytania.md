# System wycen – pytania do autora API

Stan: 1.11.2026, wersja robocza aplikacji (moduł `print_pricing`, `POST /v1/quote`).
Skill `wycena` korzysta z API zgodnie z poniższymi założeniami – do potwierdzenia.

## Pola, których znaczenie zakładamy

| Pole | Nasze założenie | Pytanie |
|---|---|---|
| `order_group` | A – pojedynczy typowy produkt, B – kilka produktów (domyślnie), C – dużo pracy | Według jakich kryteriów pracownik wybiera grupę? Czy model może ją ustalać sam? |
| `wedding_order` | `true` dla zamówień ślubnych | Czy tylko zaproszenia ślubne, czy cała papeteria (winietki, zawieszki)? |
| `cutter` | zawsze `false` | Co oznacza „Cutter” i kiedy go zaznaczać? |
| `iecho` | wycinanie po obrysie (nietypowy kształt) | Kiedy kształt jest „skomplikowany” (`complex_patterns_enabled`)? |
| `ricoh_special_color` | druk tonerem białym/złotym/srebrnym | Czy dotyczy też złota/srebra, czy tylko bieli? |
| `confection_quantity` | liczba sztuk do składania / wkładania do kopert | Co dokładnie obejmuje konfekcjonowanie? |
| `matrix_price` | zawsze 0, ustala pracownik | Kiedy matryca jest potrzebna i skąd znać jej koszt? |
| `wymiar_arkusza`, marginesy, spad | stałe: SRA3, 5, 5, 2,5 mm (jak w promptach aplikacji) | Czy kiedykolwiek inne? |

## Odpowiedź API

- Książki (`softcover_book`, `hardcover_book`, `saddle_stitched_book`) wracają z `cena: null`,
  a całe zamówienie z książką ma `costs` = `null`. Kiedy będzie wycena książek?
- Dodatkowe pola odpowiedzi (`setting_possibilities`, `ustawienie`, `cut` itd.) – skill używa tylko
  `products[].cena`, `products[].arkusze` i `costs`. Reszta może zostać albo zniknąć.
- `GET /v1/papers` zwraca `sra3_price: null` – nie używamy.

## Wdrożenie

- API nie ma uwierzytelniania – jeśli ma być dostępne poza komputerem w drukarni, potrzebny klucz/token.
- Docelowy adres serwera (teraz `http://0.0.0.0:5001/api`) – ustawiany w `GRAFFAI_WYCENA_URL`.
- Aplikacja ma własny odczyt maili przez OpenRouter (`AI/`). Skill `wycena` go zastępuje
  (Claude wypełnia te same pola) – czy moduł AI w aplikacji zostaje?
