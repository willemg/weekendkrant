Verkrijg één verse, betrouwbare timezone-aware huidige tijd. Als dat niet lukt, meld kort dat geen backendcall is uitgevoerd en stop.

Normaliseer die tijd naar UTC en kies het dichtstbijzijnde hele UTC-uur. Ga alleen verder wanneer de afstand tot dat uur maximaal 15 minuten is. Vorm dan:
- `activation_id=weekendkrant:executor-1:<YYYY-MM-DDTHH:00:00Z>`
- `operation_id=start:<activation_id>`

Bewaar deze IDs onveranderd voor deze uitvoering en eventuele transportretries.

Roep `start_weekendkrant_executor({operation_id, activation_id})` aan. Bij een verloren of onzeker transportantwoord herhaal alleen exact dezelfde call met exact dezelfde argumenten.

Stop bij `claim:null`.

Valideer een ontvangen claim met `validate_weekendkrant_claim`. Stop als de claim niet geldig is.

Voer exact het ontvangen `role_contract` uit met de ontvangen `input`, `result_ref` en `output_contract`. Leid geen gedrag af uit de rolnaam en voer geen tweede job uit.

Volg voor verdere calls, side effects, finish of abandon exact de ontvangen contracten en de toolbeschrijvingen. Gebruik de ontvangen claim waar vereist. Houd argumenten bij transportretries exact gelijk. Stop na deze ene job.
