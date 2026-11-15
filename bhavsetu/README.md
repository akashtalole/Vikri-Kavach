# bhavsetu (vendored)

Shared market-data package used by Vikri Kavach:

- `msamb.py` reads live APMC prices from msamb.com.
- `catalog.py` has the crop codes and the master list of 309 Maharashtra APMCs.
- `patti.py` reads sale slips with Claude and checks them against the charge rules.
- `llm.py` is a small Claude client.

It is vendored here from the BhavSetu project, so this repository builds on its own. Run its tests with `pip install "./bhavsetu[dev]" && pytest bhavsetu/tests`.
