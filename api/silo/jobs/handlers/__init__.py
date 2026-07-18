# Import handler modules here so their register() calls run at startup.
from silo.jobs.handlers import (  # noqa: F401
    fetch_metadata,
    gog_import,
    identify_game,
    refresh_identification_dataset,
    refresh_identification_datasets,
    renormalize_metadata,
)
