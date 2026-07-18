from silo.models.asset import AssetKind
from silo.models.field_lock import FieldKey


def test_field_key_covers_asset_kinds():
    # Asset locks key on FieldKey — a new AssetKind without its mirror member
    # would break asset locking silently.
    assert {kind.value for kind in AssetKind} <= {key.value for key in FieldKey}
