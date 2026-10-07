# Ingress-API en persistente queue

## Doel en migratiestatus

Sherlock zal fiches via HTTPS POST afleveren aan de ingress-API op bibib.
De Python-server luistert standaard alleen op `127.0.0.1:8000`. Een afzonderlijke
tunnel/reverse proxy levert externe HTTPS-bereikbaarheid; die infrastructuur is
geen onderdeel van de Python-applicatie. Deze stap configureert geen Cloudflare,
services, router of firewall.

SQLite is de persistente transportqueue. GitHub is niet langer het gekozen
transportmechanisme voor Sherlock-fiches. Git blijft voor code, weekbranches,
worktrees, auditbare redactionele output en krantartefacten. Een weekworktree is
geen queue. Bestaande branches blijven behouden zolang de huidige runtime ze nodig heeft.

**Nu geïmplementeerd:** uitsluitend de producer-API en queueopslag.
**Volgende PR:** Ariadne consumeert rechtstreeks lokaal via de queue/database-interface.
Sherlock is nog niet omgezet en `daily` leest nog de bestaande Git-fiches en
manifesten. API-items blijven nu `pending`; POST betekent ontvangst, geen verwerking.
De API valideert alleen JSON-objecten, geen inhoudelijk fiche- of dagafsluitschema.
Het contract voor dagafsluiting en lege oogst wordt bij de consumentenstap uitgewerkt.

## Starten op bibib

Python 3.9.2 op Bullseye/armv7l volstaat; de ingressmodules hebben uitsluitend
standaardbibliotheekdependencies en hoeven geen tokenizer te importeren.
Zorg dat de bestaande map `/home/weekendkrant` beschrijfbaar is. De database is
`/home/weekendkrant/weekendkrant.sqlite3`, buiten Git. Bestaande audittabellen blijven intact.

Met `WEEKENDKRANT_INGRESS_TOKEN` reeds veilig geëxporteerd in de environment:

```bash
cd /home/weekendkrant/app
/home/weekendkrant/app/.venv/bin/python /home/weekendkrant/app/ingress_api.py
```

Een ontbrekend of leeg token stopt vóór het openen van SQLite. Er is geen
CLI-tokenoptie; neem geen token op in code, repository of commandlineargumenten.
Optionele argumenten zijn `--host`, `--port` en `--db`; standaard host is loopback,
poort 8000. Tests gebruiken altijd een tijdelijke database en loopback met poort 0.
De API heeft een eigen levensduur en gebruikt niet Ariadnes Git-`flock`;
SQLite beheert de korte databasetransacties.

## HTTP-contract

| Request | Resultaat |
| --- | --- |
| `GET /health` | Zonder authenticatie: `200`, JSON `status: ok` en aantal `pending` items; geen payloads of geheimen. |
| `POST /ingress` met `Authorization: Bearer <token>` | Geldig JSON-object: `201`, JSON met toegewezen `id`, na persistente commit. |
| Ontbrekende of verkeerde bearer-authenticatie | `401`, geen INSERT. Vergelijking via `hmac.compare_digest`. |
| Malformed JSON of top-level array/string/getal/boolean/null | `400`, geen INSERT. Ook NaN/Infinity worden geweigerd. |
| Ongeldige/ontbrekende/dubbele Content-Length of Transfer-Encoding | `400`; geen chunked requests. |
| Body groter dan 1 MiB | `413`. |
| SQLite niet beschikbaar tijdens een request | `503`, zonder interne foutdetails. |
| `GET /queue` of onbekend pad | `404`; er bestaat geen publieke queue-leesinterface. |

Stuur UTF-8 JSON met Content-Length, bij voorkeur `Content-Type: application/json`.
Requests krijgen een sockettimeout van 10 seconden. Deze kleine standaardbibliotheek-
server verwerkt requests sequentieel. Iedere herhaalde POST maakt een nieuw item;
er is geen deduplicatie, lease, retry of dead-lettermechanisme. Er is geen queue-
opruiming; bestaande Ariadne-auditretentie verwijdert geen pending items.

## Modulegrenzen en tests

- `ingress_queue.IngressQueue(db_path)`: schema aanmaken, `add(payload)` en `pending_count()`;
  elke operatie opent en sluit een eigen SQLite-connectie.
- `ingress_api.Config`: environmenttoken en configureerbare host/poort/database.
- `ingress_api.create_server(config)`: testbare HTTPServer; het CLI-entrypoint draait `serve_forever()`.

Vanuit de repositoryroot, met een venv:

```bash
.venv/bin/python -m unittest discover -s tests -p 'test_ingress*.py' -v
```

Geen test opent de echte runtime-database of een publieke netwerkverbinding.
