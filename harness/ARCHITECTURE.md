# Architektura

## Metafora: plac zabaw i aktor

`harness` to **playground** – infrastruktura, która nie wie nic o tym, jak napisać dobrą
odpowiedź klientowi. Pilnuje skrzynki IMAP i daje agentowi dokładnie jedno "zabawkę":
narzędzie `create_draft(subject, body, needs_human, staff_notes)`.

**Aktorem** jest zawartość `skills/odpowiedzi-klientom/` (SKILL.md, fakty.yaml, szablony) –
to ona decyduje, co napisać. Harness tylko wczytuje tę treść jako prompt systemowy i
zapisuje to, co aktor zwróci, do folderu Szkice. Harness nigdy nie wysyła niczego sam.

## Drzewo katalogów

```
harness/
├── Dockerfile, requirements.txt, docker-compose.yml (root), .env.example (root)
├── README.md            – jak skonfigurować i uruchomić (ten dokument: jak to działa)
└── src/
    ├── main.py           – punkt wejścia procesu
    ├── config.py         – Config: walidacja zmiennych środowiskowych, fail-fast
    ├── agent/            – AI ("aktor")
    │   ├── skill_prompt.py   – DraftDecision, CREATE_DRAFT_TOOL, budowa promptu
    │   ├── agent_loop.py     – generyczna pętla wywołań narzędzi (niezależna od dostawcy)
    │   └── providers/
    │       ├── base.py              – BaseProvider (abstrakcja), ToolSpec/ToolCall/ProviderReply
    │       └── anthropic_provider.py – AnthropicProvider (Claude)
    └── mail_listener/    – infrastruktura pocztowa ("plac zabaw")
        ├── watcher.py        – pętla IDLE/poll, handle_new_mail (okablowanie + granice błędów)
        ├── mailbox.py        – IMAP: połączenie, select_folder/fetch_new, budowa i zapis szkicu
        └── state.py          – ProcessedState: punkt startowy UID + dedup po Message-ID
```

Reguła zależności: `mail_listener/` może importować z `agent/` (potrzebuje `DraftDecision`
do zbudowania maila), ale `agent/` nigdy nie importuje z `mail_listener/` – logika AI nie wie,
że to e-mail; mogłaby równie dobrze obsługiwać inny kanał.

## Przepływ dla jednej wiadomości

1. `main.py` buduje `Config` ze zmiennych środowiskowych i woła `watcher.run(cfg)`.
2. `watcher.py` łączy się przez `mailbox.connect(cfg)` i albo czeka na IDLE, albo odpytuje
   (`poll_loop`/`idle_loop`). Gdy coś się zmieni, woła `handle_new_mail(cfg, client, state)`.
3. `handle_new_mail`:
   - `mailbox.select_folder` – wybiera INBOX i odczytuje `UIDVALIDITY`/`UIDNEXT`.
   - **Pierwszy start albo zmiana UIDVALIDITY** → ustawia `state.last_uid` na aktualny
     najwyższy UID i **wychodzi bez przetwarzania** (patrz niżej: "Od teraz").
   - W przeciwnym razie: `mailbox.fetch_new(client, since_uid=state.last_uid)` – tylko
     wiadomości z UID większym niż zapamiętany punkt.
   - Dla każdej nowej wiadomości (jeśli jej Message-ID nie jest już w `state.processed_ids`):
     - `skill_prompt.build_user_message(msg.plain_text)` – owija treść klienta jako dane.
     - `agent_loop.run_agent(provider, system_prompt, user_message, tools=[CREATE_DRAFT_TOOL], stop_tool="create_draft")`
       – pętla: `provider.step(...)` → jeśli model wywołał `create_draft`, zwraca `ToolCall`
       natychmiast; jeśli wywołał coś innego, wynik (albo błąd) trafia z powrotem do modelu
       jako `tool_result` i pętla kontynuuje (maks. `MAX_TURNS` razy).
     - `DraftDecision.model_validate(tool_call.raw_input)` – walidacja tego, co model zwrócił.
     - `mailbox.build_draft_mime(...)` + `mailbox.append_draft(...)` – zapis do Szkiców
       (IMAP APPEND, flaga `\Draft`).
     - `state.mark_processed(...)` + `state.advance_uid(...)` + `state.save(...)`.
4. Wynik (`ProcessedState`) wraca do `watcher.py` i jest przekazywany do kolejnego cyklu.

## Kluczowe typy

- `Config` (pydantic, frozen) – jedyny sposób budowy to `Config.from_env(env)`; waliduje
  wszystko na starcie (brakujący klucz, źle sformatowany port, nieznany dostawca) – błąd
  konfiguracji nigdy nie wychodzi w połowie działania, tylko od razu przy starcie.
- `ProcessedState` (pydantic, frozen) – `processed_ids` (dedup po Message-ID, ucięty do
  ostatnich 500) + `last_uid`/`uid_validity` (punkt startowy "od teraz"). Każda mutacja
  (`mark_processed`, `advance_uid`, `with_baseline`) zwraca nową instancję.
- `FetchedMessage` (dataclass) – uid, message_id, plain_text, oryginalny `email.message.Message`.
  Czysta struktura przekazywana z `mailbox.py` do `watcher.py`, bez logiki.
- `DraftDecision` (pydantic) – to, co agent zwraca przez `create_draft`: subject, body,
  needs_human, staff_notes. Ten sam model generuje JSON Schema narzędzia
  (`DraftDecision.model_json_schema()`) – jedna definicja, zero duplikacji.
- `ToolSpec` / `ToolCall` / `ProviderReply` (dataclassy w `providers/base.py`) – mechanika
  rozmowy z dostawcą AI, niezależna od tego, że to maile; `agent_loop.py` nic nie wie
  o `DraftDecision`, tylko o `ToolCall.raw_input` (surowy dict z odpowiedzi modelu).

## Granice błędów (świadoma decyzja projektowa)

`handle_new_mail` ma dwa różne poziomy obsługi błędów:

1. **Na poziomie partii** (`select_folder`, `fetch_new`, `build_system_prompt`, `get_provider`)
   – te wywołania dają identyczny wynik dla każdej wiadomości w partii, więc błąd przerywa
   cały cykl, loguje i zwraca stan bez zmian. Następny cykl spróbuje od nowa.
2. **Na poziomie pojedynczej wiadomości** (`run_agent`, walidacja `DraftDecision`,
   `build_draft_mime`, `append_draft`) – błąd **zatrzymuje całą resztę partii**, a nie tylko
   tę jedną wiadomość. To jest kluczowe dla poprawności śledzenia UID: gdybyśmy pominęli
   nieudaną wiadomość i poszli dalej, punkt startowy przesunąłby się ZA nią i nigdy by nie
   wróciła do przetworzenia. Zatrzymanie na pierwszej usterce gwarantuje, że następny cykl
   zacznie dokładnie od tej samej wiadomości.

## Śledzenie UID – "od teraz", nie "wszystko nieprzeczytane"

Pierwsza wersja harnessu używała `SEARCH UNSEEN` (flaga `\Seen`). Dwa problemy:

- Konto z zaległością 5000+ nieprzeczytanych maili dostałoby 5000+ wywołań modelu i 5000+
  szkiców przy pierwszym starcie.
- Jeśli człowiek przeczyta nowego maila w Thunderbirdzie przed cyklem harnessu, wiadomość
  przestaje być `UNSEEN` i harness **zgubiłby ją na zawsze**, mimo że przyszła po starcie.

Rozwiązanie: punkt startowy to numer UID, nie flaga. Przy pierwszym starcie (albo gdy
serwer zmieni `UIDVALIDITY` – rzadkie, ale oznacza, że stare UID-y są już nieaktualne)
harness zapamiętuje aktualny najwyższy UID i **nic nie przetwarza** – to jest "teraz".
Każdy kolejny cykl pyta tylko o `UID > ostatni_zapamiętany`, niezależnie od flagi `\Seen`.

## Jak to rozszerzyć

- **Nowy dostawca AI** (np. OpenAI): nowa klasa w `agent/providers/`, implementująca
  `BaseProvider` (`start_conversation`, `step`, `tool_result_messages`), wpis w rejestrze
  `agent/providers/__init__.py`. Zero zmian w `agent_loop.py` czy `watcher.py`.
- **Nowe narzędzie dla agenta** (np. `check_print_file` dla załączników): dodać `ToolSpec`
  do listy przekazywanej w `run_agent(..., tools=[...])` i funkcję wykonawczą do
  `executors={...}` – pętla już to obsługuje (patrz `agent_loop.py`).
