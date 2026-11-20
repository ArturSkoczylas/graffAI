# Architektura

## Metafora: plac zabaw i aktor

`harness` to **playground** – infrastruktura, która nie wie nic o tym, jak napisać dobrą
odpowiedź klientowi. Przyjmuje jedno żądanie HTTP z surowym e-mailem i daje agentowi dokładnie
jedno "zabawkę": narzędzie `create_draft(subject, body, needs_human, staff_notes)`.

**Aktorem** jest `agents/harness-agent.md` (instrukcje bazowe agenta) plus wszystkie skille pod
`skills/*/SKILL.md` (odpowiedzi-klientom, pdf-check, margin-check, wycena) – to one decydują, co
napisać. Harness wczytuje agenta jako bazowy prompt systemowy, dokłada do niego lekki indeks
`<available_skills>` (nazwa + opis każdego skilla, z `skills_registry.discover_skills()`) i daje
modelowi narzędzie `read_skill(name)`, którym sam wczyta pełną instrukcję skilla, gdy uzna go za
właściwy – harness nie zgaduje z wyprzedzeniem, który skill jest potrzebny, i nie wkleja ich
wszystkich na stałe. Harness zapisuje to, co aktor zwróci, do folderu Szkice. Nigdy nie wysyła
niczego sam.

**Wywołującym** jest przycisk w `thunderbird-extension/` – klik na otwartej wiadomości
wysyła jej surową treść (`messenger.messages.getRaw()`) do `POST /draft`. Harness nie
obserwuje skrzynki w tle – każdy szkic powstaje na żądanie, dla jednej, już posiadanej
wiadomości.

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
    │   ├── skills_registry.py – odkrywanie skilli (skills/*/SKILL.md), read_skill na żądanie
    │   ├── print_check.py    – narzędzie check_print_file (pdf-check/margin-check jako kod)
    │   ├── run_script.py     – narzędzie run_skill_script (wycena.py/canva_link.py jako subprocess)
    │   ├── agent_loop.py     – generyczna pętla wywołań narzędzi (niezależna od dostawcy)
    │   └── providers/
    │       ├── base.py              – BaseProvider (abstrakcja), ToolSpec/ToolCall/ProviderReply
    │       └── anthropic_provider.py – AnthropicProvider (Claude)
    ├── mail_listener/    – infrastruktura pocztowa ("plac zabaw")
    │   └── mailbox.py        – parsowanie e-maili, budowa szkicu MIME, IMAP connect/append
    └── api/              – wejście z zewnątrz ("plac zabaw" od strony HTTP)
        └── server.py         – serwer HTTP stdlib: POST /draft, okablowanie + granice błędów
```

Reguła zależności: `mail_listener/` i `api/` mogą importować z `agent/` (potrzebują
`DraftDecision` do zbudowania maila), ale `agent/` nigdy nie importuje z nich – logika AI nie
wie, że to e-mail; mogłaby równie dobrze obsługiwać inny kanał.

## Przepływ dla jednego żądania

1. `main.py` buduje `Config` ze zmiennych środowiskowych i woła `api.server.run(cfg)`.
2. `server.py` nasłuchuje na `cfg.api_host:cfg.api_port` (domyślnie `127.0.0.1:8765`,
   `ThreadingHTTPServer` ze stdlib – zero nowych zależności). Rozszerzenie Thunderbirda woła
   `POST /draft` z surowym RFC822 w ciele żądania.
3. `_DraftHandler.do_POST` czyta ciało i woła `handle_draft_request(cfg, raw)` – czystą funkcję
   (bez I/O sieciowego), więc testowalną bez stawiania prawdziwego serwera:
   - Puste ciało → `400`.
   - W przeciwnym razie woła `create_draft_from_raw_email(cfg, raw)`:
     - `email.message_from_bytes(raw)` + `mailbox.extract_plain_text(original)`.
     - `skill_prompt.build_system_prompt`/`build_user_message` – budują prompt.
     - `agent_loop.run_agent(provider, system_prompt, user_message, tools=[CREATE_DRAFT_TOOL,
       read_skill, ...], stop_tool="create_draft")` – pętla: `provider.step(...)` → jeśli model wywołał
       `create_draft`, zwraca `ToolCall` natychmiast; jeśli wywołał coś innego, wynik (albo
       błąd) trafia z powrotem do modelu jako `tool_result` i pętla kontynuuje (maks.
       `MAX_TURNS` razy).
     - `DraftDecision.model_validate(tool_call.raw_input)` – walidacja tego, co model zwrócił.
     - `mailbox.build_draft_mime(...)` + `mailbox.connect(cfg)` + `mailbox.append_draft(...)` –
       zapis do Szkiców (IMAP APPEND, flaga `\Draft`), połączenie zawsze zamykane (`finally`).
     - Każdy błąd na tej ścieżce → `500` z treścią błędu w `message`; handler nigdy nie
       podnosi wyjątku na zewnątrz, zawsze zwraca odpowiedź HTTP.
   - Sukces → `200` z `{"status": "ok", "subject": ..., "needs_human": ...}`.
4. Połączenie IMAP jest otwierane i zamykane per żądanie (nie ma trwałego połączenia IDLE ani
   żadnego stanu między żądaniami – każde żądanie jest niezależne).

## Kluczowe typy

- `Config` (pydantic, frozen) – jedyny sposób budowy to `Config.from_env(env)`; waliduje
  wszystko na starcie (brakujący klucz, źle sformatowany port, nieznany dostawca) – błąd
  konfiguracji nigdy nie wychodzi w połowie działania, tylko od razu przy starcie.
- `DraftDecision` (pydantic) – to, co agent zwraca przez `create_draft`: subject, body,
  needs_human, staff_notes. Ten sam model generuje JSON Schema narzędzia
  (`DraftDecision.model_json_schema()`) – jedna definicja, zero duplikacji.
- `ToolSpec` / `ToolCall` / `ProviderReply` (dataclassy w `providers/base.py`) – mechanika
  rozmowy z dostawcą AI, niezależna od tego, że to maile; `agent_loop.py` nic nie wie
  o `DraftDecision`, tylko o `ToolCall.raw_input` (surowy dict z odpowiedzi modelu).

## Granice błędów (świadoma decyzja projektowa)

W przeciwieństwie do wcześniejszej wersji z wsadowym watcherem IMAP, jedno żądanie HTTP = jedna
wiadomość = jeden niezależny wynik. Nie ma pojęcia "partii" ani punktu startowego (UID) do
pilnowania – błąd w jednym żądaniu (parsowanie, model, zapis do IMAP) kończy się po prostu
odpowiedzią `500` z opisem błędu; kolejne kliknięcia przycisku są całkowicie niezależne.

## Jak to rozszerzyć

- **Nowy dostawca AI** (np. OpenAI): nowa klasa w `agent/providers/`, implementująca
  `BaseProvider` (`start_conversation`, `step`, `tool_result_messages`), wpis w rejestrze
  `agent/providers/__init__.py`. Zero zmian w `agent_loop.py` czy `api/server.py`.
- **Nowe narzędzie dla agenta** (np. `check_print_file` dla załączników): dodać `ToolSpec`
  do listy przekazywanej w `run_agent(..., tools=[...])` i funkcję wykonawczą do
  `executors={...}` – pętla już to obsługuje (patrz `agent_loop.py`).
- **Powrót do automatycznego obserwowania skrzynki**: poprzednia wersja (`mail_listener/watcher.py`
  + `state.py`, IDLE/poll + śledzenie UID) jest w historii gita – `git log --all -- harness/src/mail_listener/watcher.py`.
