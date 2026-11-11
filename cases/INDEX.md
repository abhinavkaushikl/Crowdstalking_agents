# Location Intelligence - Case Registry

Each case is a separate, randomly-parameterized scenario run through the exact same
detection algorithm used by the live system (`social-media-sentiment-agent/crowd_anomaly_agent.py`),
scored against ground truth the detector never gets to see.

- [concert_panic](concert_panic/report.md) - recall 0%, false positives 0, seed `50488760`
- [mass_dispersal](mass_dispersal/report.md) - recall 0%, false positives 1, seed `540602159`
- [riot](riot/report.md) - recall 0%, false positives 1, seed `558983632`

- [aggregate_evaluation](aggregate_evaluation/report.md) - 31 incidents injected, 0 detected, 31 total flags raised