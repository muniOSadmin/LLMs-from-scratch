# Rule: Agency Code Corrections

These codes differ between PATTERNS.pdf usage and the authoritative OTI registry (agencies.yaml):

| Use this | Not this | Reason |
|---|---|---|
| `NYC_DOT` | `DOT` | Registered acronym is `NYC DOT`; `DOT` is alternate |
| `NYCEDC` | `EDC` | Registry entry is NYC Economic Development Corporation |
| NYS HCR (T3 surface) | `HCR` | NYS-level agency, not in NYC registry |
| `OATH` | `ECB` | ECB violations are *heard* by OATH; ECB is the violation body |

Always resolve agency codes against `iphone-llm/agencies.yaml` before writing patterns.
Never hardcode agency codes in Python — import from the YAML.
