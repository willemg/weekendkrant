# Exacte aanvulling op Sherlocks bestaande taakinstructies

Voeg onderstaande tekst toe aan de bestaande taakinstructies. Deze PR wijzigt de
actieve ChatGPT-taak niet. De bestaande inhoudelijke zoekopdracht blijft behouden.

---

## Verplichte publicatie en dagafsluiting

Bepaal bij aanvang de lokale kalenderdatum in `Europe/Brussels` en leid daaruit het
ISO-weekjaar en weeknummer af. Gebruik voor deze run uitsluitend branch
`ingress/YYYY_Www` en map `ingress/YYYY_Www/`. Controleer vóór schrijven of
`ingress/YYYY_Www/closed/YYYY-MM-DD.json` al bestaat voor die lokale datum. Als dat
bestand bestaat, is die dag afgesloten: schrijf, wijzig of verwijder niets meer
voor die datum en stop de publicatie.

Behoud voor iedere fiche het bestaande UTF-8-formaat met LF-regeleinden:

```text
WEEKENDKRANT-INGRESS-1
topic: <numeriek onderwerpnummer>
date: <lokale datum YYYY-MM-DD>

<volledige fiche met bronlinks>
```

Schrijf fiches als `ingress_0001.md`, enzovoort, met unieke vrije nummers in de
weekmap. Overschrijf nooit eerdere fiches. Gebruik de lokale verzameldatum in de
header; een publicatiedatum van een bron hoort in de fichetekst.

Publiceer pas nadat **alle** fiches van deze run succesvol op de juiste remote
branch staan één afzonderlijk gereedmeldingsbestand, als laatste publicatie:
`ingress/YYYY_Www/closed/YYYY-MM-DD.json`.

Het JSON-object heeft exact de velden `schema_version` (integer 1), `date`
(de lokale datum), `week` (bijvoorbeeld `2026_W41`) en `files` (een lijst).
Ieder element van `files` heeft exact `path` (volledig repositoryrelatief fichepad)
en `sha256` (de 64 kleine hextekens van de SHA-256 van de exacte gepubliceerde bytes).
Neem **alle** fiches met deze lokale datum op, ook reeds succesvol gepubliceerde
fiches uit een eerdere onvoltooide poging. Sorteer de lijst op pad; geen dubbele
paden. Bereken hashes met gereedschap op de werkelijk gepubliceerde bytes: verzin
ze niet en bereken ze niet op een opnieuw geformatteerde weergave.

Bij een succesvol afgeronde zoekronde zonder geselecteerde fiches publiceer je
hetzelfde manifest met `files: []`. Een mislukte of onvolledige zoek-/publicatieronde
is geen lege oogst: publiceer dan **geen** gereedmelding. Kun je bestanden of hashes
niet betrouwbaar controleren, meld het probleem en laat de dag open.

Na succesvolle publicatie van het manifest is de dag definitief afgesloten.
Voeg voor die datum niets meer toe en wijzig of verwijder noch het manifest noch
de bijbehorende fiches. Bewaar nieuwe latere vondsten voor een volgende lokale
dag. Schrijf nooit zelf Ariadne-draden of operationele SQLite-status naar GitHub.
