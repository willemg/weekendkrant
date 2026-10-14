# Generieke jobs en attempts (schema 7)

Dit is de lokale opslaglaag van fase 3. Er is geen dispatcher, MCP/control plane,
worker of productiejob geïntegreerd. Sherlock, ingress en Ariadne blijven hun
bestaande contract gebruiken. `attempts` blijft Ariadnes foutaudit;
`job_attempts` is uitsluitend de nieuwe generieke uitvoeringsaudit.

## Identiteit, grenzen en transacties

`JobStore(connection)` gebruikt de centrale migraties en een caller-owned,
inactieve SQLite-connection. Mutaties gebruiken `BEGIN IMMEDIATE`, lezen de
backendklok na het verkrijgen van de schrijflock en committen alle betrokken
records samen. Bij fouten volgt rollback. Modelwerk, netwerkverkeer en
bestandspublicaties gebeuren nooit in die transactie. Een actieve callertransactie
wordt geweigerd, niet stilzwijgend gecommit. Connection-timeout/lockfouten blijven
zichtbaar; opnieuw proberen vereist dezelfde operatie-identiteit.

Een job heeft een stabiele oplopende `id`, immutable rol, inputreferenties,
outputcontractreferentie, vaste leaseduur en creatietijd. Status, update- en
eindtijd en geaccepteerde outputreferenties beschrijven de lifecycle. Input en
output bevatten maximaal 32 concrete artifact-/versiereferenties van maximaal
512 tekens. De outputcontractreferentie is verplicht, maximaal 512 tekens; de rol
is niet-lege tekst van maximaal 128 tekens. Het opslagschema interpreteert geen
rol of artifacttype. De producent moet bestaande, concrete immutable versies
refereren en het contract moet inhoud, context, output en toegestane acties
begrenzen. Deze laag controleert vorm en execution identity, geen artifactinhoud
of redactionele contracten die pas in latere fasen bestaan.

Iedere claim maakt een afzonderlijke attempt met oplopende `id`, unieke
backendgegenereerde willekeurige token, globale `activation_id`, jobreferentie,
starttijd, `lease_until`, status, eindtijd, outputreferenties en eventuele fout
(maximaal 2048 tekens). De oplopende attempt-ID vormt de fencing-generatie, de
token bewijst bezit van de claim. De unieke activation-ID voorkomt een tweede
job/attempt binnen dezelfde scheduled activatie, ook voor een andere rol of job.
Een toekomstige control plane moet die identiteit betrouwbaar aanleveren, bij
retry behouden en tokens niet loggen of aan andere executors blootstellen.

Alle tijden zijn UTC ISO 8601 met microseconden. Leaseduur is expliciet 1..86400
gehele seconden, standaard 600 seconden. Een lease geldt uitsluitend zolang
`now < lease_until`; op de grens vervalt hij. Geen heartbeat of leaseverlenging:
een job moet binnen zijn vooraf gekozen duur afronden. De backendklok moet
betrouwbaar en gesynchroniseerd zijn; workerklokken beslissen niet. Dit is een
autorisatiegrens, geen proceskill of bewijs dat model-/netwerkwerk gestopt is.

## Lifecycle en herstel

| Operatie/conditie | Job | Attempt | Gevolg |
| --- | --- | --- | --- |
| `create(role, input_refs, output_contract_ref, lease_seconds=600)` | `ready` | Geen | Retourneert stabiele job-ID; iedere create is een nieuwe opdracht |
| `claim(job_id, activation_id)` op ready | `running` | Nieuwe `running` | Retourneert job-ID, attempt-ID, token en lease-einde |
| Zelfde claim opnieuw, binnen lease | `running` | Dezelfde | Exact hetzelfde claimantwoord, geen nieuwe attempt |
| Andere claim op niet-ready | Ongewijzigd | Geen nieuwe | `None`; geen selectie of dispatcher |
| `finish(claim, 'succeeded', output_refs)` | `succeeded` | `succeeded` | Referenties en terminale tijden atomisch bevestigd |
| `finish(claim, 'failed', output_refs, error)` | `failed` | `failed` | Bekende terminale fout; geen automatische retry |
| `finish(claim, 'uncertain', output_refs, error)` | `blocked` | `uncertain` | Onzekere effecten eerst onderzoeken |
| Lease verlopen | `blocked` | `expired` | Oude claim kan geen resultaat meer laten accepteren |
| `reconcile(..., 'retry', evidence_ref)` | `ready` | Blijft immutable gesloten | Alleen na bewezen stop en veilige heruitvoering; volgende activatie krijgt nieuwe attempt/token |
| `reconcile(..., 'succeeded'/'failed', evidence_ref, output_refs)` | Terminal | Blijft immutable gesloten | Bekende effecten/resultaten expliciet bevestigd met aparte herstelaudit |

`recover_expired()` zet alle verlopen attempts atomisch in quarantaine en is
herhaalbaar. Ook claim/finish controleren expiry onder de schrijflock; een
aparte sweeper is geen veiligheidsvoorwaarde. Een finish op een verlopen claim
commit de quarantaine en geeft vervolgens `ValueError`. Onbekende, vervalste,
superseded of conflicterende claims worden geweigerd. Een exact herhaalde
bevestigde finish (status, outputs en fout identiek) is een no-op, ook na het
lease-einde. Het bewijs is de opgeslagen finish, niet de herinnering van de worker.
Een onbevestigde finish moet eerst dezelfde operatie herhalen of opgeslagen state
raadplegen, niet alvast opnieuw publiceren. `get(job_id)` en `attempts(job_id)`
geven inspecteerbare state; ze maken een verlopen lease niet opnieuw geldig.

Reconciliatie is een **trusted recovery-operatie**, nog zonder externe endpoint.
Een niet-lege bewijsreferentie moet naar een controle verwijzen die aantoont dat
de oude executor gestopt is en de effecten bekend zijn. Voor `retry` moet ook
vaststaan dat heruitvoering veilig is: geen onbehandelde effecten, of geverifieerde
idempotentie bij de ontvanger. De opslaglaag controleert de referentie en dat de
attempt de laatste geblokkeerde poging van deze job is; zij kan het inhoudelijke
bewijs niet zelf beoordelen. Bij onbekende effecten blijft de job blocked.
Alleen tijdsverloop of een nieuwe schedulerstart is onvoldoende bewijs.

Iedere reconciliatie krijgt één immutable `job_recoveries`-record, gekoppeld aan
de oude attempt, met beslissing, bewijs, outputs en tijd. Een oude attempt wordt
niet achteraf van expired/uncertain naar succeeded herschreven. Een herhaalde
reconciliatie wordt geweigerd; inspecteer de opgeslagen beslissing voordat je
een nieuwe actie neemt. Outputregistratie publiceert geen artifact en veroorzaakt
geen externe side effect. Dat voorkomt een verborgen exactly-once-belofte.

## Crash- en concurrency-invarianten

- Twee connections kunnen dezelfde ready job niet tegelijk claimen. Statuswijziging
  en attemptinsert zitten onder dezelfde SQLite-schrijfslot; een unieke partial
  index bewaakt bovendien maximaal één running attempt per job.
- Crash vóór commit laat geen halve claim, finish of herstelaudit achter.
  Crash na commit behoudt die state; een verloren antwoord verandert de uitvoering
  niet in een nieuwe job of nieuwe attempt.
- Expiry geeft nooit automatisch toestemming tot overlappende heruitvoering.
  Ook als de oude executor blijft werken, wordt zijn late resultaat afgewezen.
  Alleen reconciliatie met bewezen stop kan een volgende attempt toestaan.
- Lease/fencing beschermen deze opslaglaag. Externe effecten zijn niet door SQLite
  te fencen. Latere publicatieadapters moeten vóór effects claimvalidatie, eigen
  idempotentie en zo nodig ontvangerfencing implementeren. De bestaande `/ingress`
  is daarvoor nog niet aangepast en wordt niet door deze jobs aangeroepen.
- Jobidentiteit, gesloten attempts en herstelaudit mogen niet overschreven worden.
  Delete en `INSERT OR REPLACE` van bestaande auditidentiteiten worden geweigerd.
  Terminale jobs zijn immutable. Rechtstreeks SQL is geen ondersteunde lifecycle-API.

Een backendherstart start geen nieuwe uitvoering. Voor verdere voortgang roept
lokale recovery `recover_expired()` aan en onderzoekt blocked jobs. Automatisch
retryen zonder bewijs is bewust uitgesloten. Crashsafe veiligheid gaat hier boven
automatische voortgang; een dispatcher en recoverybeleid zijn latere integratie.

## Migratie en validatie

Migratie `007_jobs.sql` voegt uitsluitend `jobs`, `job_attempts`, `job_recoveries`
en hun indices/constraints/triggers toe. Geen bestaande tabel, rij, provenance,
Sherlock-run of Ariadne-attempt verandert; er is geen backfill. Lege databases en
upgrades volgen dezelfde keten. DDL en `user_version=7` committen samen, herhalen
is een no-op, een mislukte stap blijft op versie 6. De bestaande runtime kan na
upgrade verder werken zonder generieke jobs te maken.

De jobtests controleren onafhankelijke SQLite-connections, gelijktijdige claimers,
één activatie tegenover twee jobs, finish versus expiry, echte abrupte procesexits
vóór/na commit, herstart, late/forged tokens, exacte finishretry, onzekere effecten,
reconciliatie, rollback, schema-upgrade en auditimmutability. De bestaande
systeemtest blijft het HTTP-ingress → SQLite → Ariadne → part/revision-pad testen;
hij beweert geen generieke control plane te testen.

```bash
python -m unittest discover -s tests -p 'test_jobs.py' -v
python -m unittest discover -s tests
python -m unittest discover -s tests -p 'test_system_e2e.py' -v
```

Validatie van deze fase op 14 oktober 2026: 212 tests groen in de volledige
Python-suite, waaronder 20 jobtests; de afzonderlijke systeemtest is 2/2 groen.
Deze lokale uitvoering gebruikt Python 3.12; het operatorbewijs van 192 tests
op bibib betreft de voorafgaande fase-2.5-runtime.
