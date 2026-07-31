# Process Flow

## Monthly refresh

```mermaid
flowchart TD
    A["Drop source files into data/raw/YYYY-MM"] --> B["Discover files from field_mappings.yml"]
    B --> C["Normalize columns into staged records"]
    C --> D["Run validation rules"]
    D --> E["Load canonical event fact"]
    E --> F["Compute KPI snapshots and forecasts"]
    F --> G["Export workbook and dashboard tables"]
    G --> H["Generate commentary draft"]
    H --> I["Human review before publication"]
```

## Failure handling

- Missing required file: stop the run before staging.
- Validation errors above threshold: mark run as `warning` or `failed` depending on severity policy.
- Workbook export failure: keep mart tables but mark the run incomplete in `etl_run`.

## Logging expectations

Every run should capture:

- started timestamp
- finished timestamp
- reporting period
- source file count
- staged row count
- validation issue count
- run status
- operator notes
