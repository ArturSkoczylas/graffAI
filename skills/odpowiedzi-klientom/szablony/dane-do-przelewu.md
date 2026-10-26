---
id: dane-do-przelewu
tytul: Wysyłka i dane do przelewu
kategoria: zamówienia
tryb: pracownik
kiedy: Pracownik wysyła dane do przelewu po ustaleniu kwoty (np. przy wysyłce kurierem).
zmienne:
  nrb: numer rachunku – wyłącznie z fakty.yaml
  kwota: łączna kwota – tylko od pracownika
  rozliczenie: z czego wynika kwota, np. 150 zł obraz 70x100 i 25 zł wysyłka
zrodlo: TEKSTY_MAILI.docx – WYSYŁKA I DANE DO PRZELEWU
---

Dzień dobry,

poniżej przesyłam dane do przelewu:

Graffa Paweł Kisielewicz
ul. Miejska 14
51-352 Wrocław
NRB: {{nrb}}

kwota: {{kwota}} ({{rozliczenie}})

Proszę o przesłanie potwierdzenia przelewu i podanie adresu wysyłki lub namiarów na paczkomat (wraz z osobą kontaktową i nr telefonu).
