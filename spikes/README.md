# Spikes

Throwaway proofs of concept that de-risk milestones. Standard library only, no
install needed. They write nothing outside the `--out` directory you give them.

| Script | Proves | Milestone |
| --- | --- | --- |
| `poc_public_export.py` | The Public Export index decodes (raw LZMA1 trick) and manifests parse; recipes have ingredients | M1 |
| `poc_worldstate.py` | The official world state loads and live fissures resolve to node names via `ExportRegions` | M7 |
| `poc_profile.py` | The public profile endpoint returns progression data for an account ID | M2 |

```bash
python spikes/poc_public_export.py --out ./data/pe
```

```bash
python spikes/poc_worldstate.py --pe ./data/pe
```

```bash
python spikes/poc_profile.py --account-id <24 hex chars> --platform pc --out ./data/profile
```

The first two ran successfully on 2026-10-16. `poc_profile.py` needs an account ID
to test.
