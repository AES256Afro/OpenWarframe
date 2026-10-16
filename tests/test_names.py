from __future__ import annotations

from openwarframe.codex.names import NameResolver, normalize, strip_decorations, strip_store_prefix


def test_normalize_and_decorations():
    assert normalize("  Rhino   Prime ") == "rhino prime"
    assert strip_decorations("<ARCHWING> Amesha") == "Amesha"
    assert strip_store_prefix("/Lotus/StoreItems/Types/Recipes/X") == "/Lotus/Types/Recipes/X"


def test_resolver_maps_blueprints_to_recipes_and_items():
    r = NameResolver()
    r.add_item("Rhino Prime Chassis", "/Lotus/Types/Recipes/WarframeRecipes/RhinoPrimeChassisComponent")
    r.add_recipe("Rhino Prime Chassis", "/Lotus/Types/Recipes/WarframeRecipes/RhinoPrimeChassisBlueprint")
    r.add_item("Orokin Cell", "/Lotus/Types/Items/MiscItems/OrokinCell")
    r.add_item("Forma Blueprint", "/Lotus/Types/Recipes/Components/FormaBlueprint")
    r.add_relic("Lith R2", "/Lotus/Types/Game/Projections/T1R2")

    assert (
        r.resolve("Rhino Prime Chassis Blueprint")
        == "/Lotus/Types/Recipes/WarframeRecipes/RhinoPrimeChassisBlueprint"
    )
    assert (
        r.resolve("Rhino Prime Chassis") == "/Lotus/Types/Recipes/WarframeRecipes/RhinoPrimeChassisComponent"
    )
    assert r.resolve("3X Orokin Cell") == "/Lotus/Types/Items/MiscItems/OrokinCell"
    assert r.resolve("Forma Blueprint") == "/Lotus/Types/Recipes/Components/FormaBlueprint"
    assert r.resolve("Lith R2 Relic") == "/Lotus/Types/Game/Projections/T1R2"
    assert r.resolve("Lith R2 Relic (Radiant)") == "/Lotus/Types/Game/Projections/T1R2"
    assert r.resolve("Mystery Thing") is None
    assert r.unresolved["Mystery Thing"][0] == 1


def test_currency_names_map_to_pseudo_items():
    from openwarframe.codex.names import parse_currency

    assert parse_currency("80 Endo") == ("/OpenWarframe/Currency/Endo", 80)
    assert parse_currency("3,000 Credits Cache") == ("/OpenWarframe/Currency/Credits", 3000)
    assert parse_currency("2X 10,000 Credits Cache") == ("/OpenWarframe/Currency/Credits", 10000)
    assert parse_currency("Orokin Cell") is None
    r = NameResolver()
    assert r.resolve("400 Endo") == "/OpenWarframe/Currency/Endo"
    assert not r.unresolved
