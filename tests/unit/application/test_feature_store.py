"""FeatureStore: definition hash registry per DETAILED_DESIGN section 5.4 -
a feature name is permanently bound to one parameterization; different
definitions cannot silently overwrite the same name."""

import pytest

from quant_agent.application.features import FeatureDefinition, FeatureStore


def definition(name="ma_close", **params):
    return FeatureDefinition(name=name, params=params)


def test_definition_hash_is_stable_and_param_sensitive():
    base = definition(window=20)
    same = definition(window=20)
    other = definition(window=60)

    assert base.definition_hash() == same.definition_hash()
    assert base.definition_hash() != other.definition_hash()


def test_registering_the_same_definition_is_idempotent():
    store = FeatureStore()

    store.register(definition(window=20))
    store.register(definition(window=20))

    assert store.definition_hash("ma_close") == definition(window=20).definition_hash()


def test_same_name_with_different_params_is_rejected():
    store = FeatureStore()
    store.register(definition(window=20))

    with pytest.raises(ValueError, match="ma_close"):
        store.register(definition(window=60))


def test_put_requires_registration_and_get_round_trips():
    from datetime import datetime, timezone

    store = FeatureStore()
    store.register(definition(window=20))
    as_of = datetime(2026, 9, 15, 15, 0, tzinfo=timezone.utc)

    with pytest.raises(ValueError, match="not registered"):
        store.put("unknown", "sh600519", as_of, 10.5)

    store.put("ma_close", "sh600519", as_of, 10.5)

    assert store.get("ma_close", "sh600519", as_of) == 10.5
    with pytest.raises(KeyError):
        store.get("ma_close", "sh600519", as_of.replace(day=16))


def test_put_records_the_computation_moment():
    from datetime import datetime, timezone

    store = FeatureStore()
    store.register(definition(window=20))
    as_of = datetime(2026, 9, 15, 15, 0, tzinfo=timezone.utc)

    store.put("ma_close", "sh600519", as_of, 10.5)

    assert store.stamp("ma_close", "sh600519", as_of) == as_of
