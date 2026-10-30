# SD6103_PROJECT

HDB resale and hawker-centre database project.

- [Architecture and Task 1 documentation](docs/architecture/README.md)
- [Shared database schema and CSV/ID contract](db/schema/README.md)
- [HDB data processing: setup, reproduction and validation](src/etl/hdb/README.md)
- [Frozen HDB data: download the five files or the missing 2017-onwards file](data/snapshots/README.md)
- [HDB findings, team handoff and remaining integration work](src/etl/hdb/handoff.md)
- [Hawker and geolocation processing: setup, review decisions and validation](src/etl/spatial/README.md)

The HDB and spatial modules have passed actual PostgreSQL import checks. The complete
performance benchmark series remains separate integration work; see the handoff.
