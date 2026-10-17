# Outputcontract voor Kuifje

Roep na afhandeling van alle aangeleverde missies `finish_weekendkrant_job` aan
met de actuele `job_id`, `attempt_id` en `token`, `status=succeeded`,
`output_refs=[de aangeleverde result_ref]` en het afzonderlijke object:

```json
{"kuifje_result":{"mission_results":[{"mission_id":"exacte toegewezen mission_id","summary":"Concrete bevindingen of expliciet lege oogst","limitations":"Beperkingen van dit onderzoek"}]}}
```

`mission_results` bevat exact één item voor iedere missie uit `input.missions`,
in exact dezelfde volgorde. Gebruik uitsluitend de toegewezen `mission_id`'s,
zonder duplicaten of ontbrekende missies. `summary` en `limitations` zijn beide
niet-lege tekst van maximaal 8192 tekens per missie. Ook vruchteloos onderzoek
krijgt een eigen item. Succes betekent dat alle missies inhoudelijk afgehandeld
zijn; ontbrekende resultaten zijn geen gedeeltelijk succes.

Gebruik bij mislukking `status=failed`, `output_refs=[]` en `error`. Gebruik bij
onbekende effecten `uncertain` of `abandon_weekendkrant_job`. Laat `kuifje_result`
weg bij een niet-succesvolle afloop. Reeds bevestigde fiches blijven bewaard.
Geef geen `operation_id` mee. Herhaal na een onzeker transportantwoord exact
dezelfde terminale argumenten en herhaal nooit het onderzoek.
