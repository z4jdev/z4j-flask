# Changelog

## 1.9.1 (2026-08-26)

* Carried with the coordinated fleet release. No adapter behaviour changed.

## 1.9.0 (2026-08-25)

* TaskIQ discovery now attaches z4j's middleware. Loop ownership remains
  deferred until the TaskIQ broker actually starts, so Flask initialization
  never guesses that an unrelated event loop owns the broker.
* Version bumped as part of the coordinated 1.9.0 fleet release, so every
  package in a deployment agrees on its peers.

## 1.8.0 (2026-07-23)

* Part of the coordinated 1.8.0 fleet release (unified fleet version, green lint/format/import-boundary gate).

## 1.7.0 (2026-07-07)

* README corrected to the real `Z4J(app)` API and env-var names (`Z4J_TOKEN`, `Z4J_BRAIN_URL`, `Z4J_PROJECT_ID`).
* Python 3.11 is now the minimum supported version (3.10 dropped).
* Part of the coordinated 1.7.0 fleet release (unified fleet version, green lint/format/import-boundary gate).

## 1.4.0 (2026-05-02)

Initial 1.4.0 release: Flask adapter. `Z4J(app)` initializer in your app factory.
