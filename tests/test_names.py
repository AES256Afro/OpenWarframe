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
    # The Index pays out credits as "Return: <amount>"
    assert parse_currency("Return: 105,000") == ("/OpenWarframe/Currency/Credits", 105000)
    r = NameResolver()
    assert r.resolve("400 Endo") == "/OpenWarframe/Currency/Endo"
    assert r.resolve("Return: 250,000") == "/OpenWarframe/Currency/Credits"
    assert not r.unresolved


def test_relic_names_prefer_canonical_relic_over_item_map():
    r = NameResolver()
    r.add_item("Lith C5 Relic", "/Lotus/Types/Game/Projections/T1C5Silver")  # variant seen first
    r.add_relic("Lith C5", "/Lotus/Types/Game/Projections/T1C5Bronze", prefer=True)
    assert r.resolve("Lith C5 Relic") == "/Lotus/Types/Game/Projections/T1C5Bronze"
    assert r.resolve("Lith C5 Relic (Radiant)") == "/Lotus/Types/Game/Projections/T1C5Bronze"


# --- fallback rules: each undoes one way drop tables decorate export names ---

AUGMENT = "/Lotus/Powersuits/Trinity/LinkAugmentCard"
FLARE_BP = "/Lotus/Types/Recipes/SynthicatorRecipes/FlareBlueBlueprint"
ALLOY_BP = "/Lotus/Types/Recipes/DeimosRecipes/Prospecting/DeimosCommonOreAAlloyBlueprint"
VOSFOR = "/Lotus/Types/Items/MiscItems/DistillPoints"


def _resolver() -> NameResolver:
    r = NameResolver()
    r.add_item("Abating Link", AUGMENT)
    r.add_item("Bhisaj-Bal", "/Lotus/Upgrades/Mods/Rifle/Event/ParisHealOnStatusMod")
    r.add_item("Astral Bond", "/Lotus/Types/Sentinels/SentinelPrecepts/VoidBond/VoidVinculum")
    r.add_item("Fosfor Blau", "/Lotus/Types/Restoratives/Consumable/Synthetics/FlareBlue")
    r.add_recipe("Fosfor Blau", FLARE_BP)
    r.add_item("Adramal Alloy", "/Lotus/Types/Items/Gems/Deimos/DeimosCommonOreAAlloyItem")
    r.add_recipe("Adramal Alloy", ALLOY_BP)
    r.add_item("Vosfor", VOSFOR)
    r.add_item("Omni Forma", "/Lotus/Types/Items/MiscItems/FormaAura")
    r.add_item("Universal Medallion", "/Lotus/Types/Items/SyndicateDogTags/UniversalSyndicateDogTag")
    r.add_item("Keratinos Blades", "/Lotus/Types/Recipes/Weapons/WeaponParts/InfTransformClawsWeaponBlade")
    r.add_recipe("Keratinos Blades", "/Lotus/Types/Recipes/Weapons/WeaponParts/KeratinosBladeBlueprint")
    r.add_item(
        "Hood Display Black Decoration", "/Lotus/Types/Items/ShipDecos/LisetPropOperatorHoodDisplayBlack"
    )
    r.add_item("Seeker of Truth Honoria", "/Lotus/Types/Items/Titles/ArbitersOfHexisTitle")
    r.add_item("Perrin Sequence Stencil", "/Lotus/Types/Game/QuartersWallpapers/SyndicatePSWallpaper")
    r.add_item("Voidrig", "/Lotus/Powersuits/EntratiMech/NechroTech")
    r.add_recipe("Voidrig", "/Lotus/Types/Recipes/DeimosRecipes/Mechs/NecromechBlueprint")
    r.add_item("Orokin Ducats", "/Lotus/Types/Items/MiscItems/PrimeBucks")
    return r


def test_trailing_qualifier_is_dropped():
    r = _resolver()
    assert r.resolve("Abating Link (Trinity)") == AUGMENT  # augment listed with its warframe
    assert r.resolve("Bhisaj-Bal(Paris Prime)") == "/Lotus/Upgrades/Mods/Rifle/Event/ParisHealOnStatusMod"


def test_quantity_markers_before_blueprint_and_at_the_end():
    r = _resolver()
    assert r.resolve("Fosfor Blau (x20) Blueprint") == FLARE_BP
    assert r.resolve("Adramal Alloy X20 Blueprint") == ALLOY_BP
    assert r.resolve("Adramal Alloy x20 Blueprint") == ALLOY_BP
    assert r.resolve("Vosfor (200x)") == VOSFOR


def test_cache_wrapper_resolves_to_its_content():
    r = _resolver()
    assert r.resolve("Vosfor Cache (200x)") == VOSFOR
    assert r.resolve("500 Vosfor Cache") == VOSFOR


def test_footnote_marker_is_dropped():
    assert _resolver().resolve("Omni Forma*") == "/Lotus/Types/Items/MiscItems/FormaAura"


def test_singular_and_plural_of_the_last_word():
    r = _resolver()
    assert (
        r.resolve("10X Universal Medallions")
        == "/Lotus/Types/Items/SyndicateDogTags/UniversalSyndicateDogTag"
    )
    assert (
        r.resolve("Keratinos Blade Blueprint")
        == "/Lotus/Types/Recipes/Weapons/WeaponParts/KeratinosBladeBlueprint"
    )


def test_type_words_drop_tables_leave_off():
    r = _resolver()
    assert r.resolve("Hood Display Black") == "/Lotus/Types/Items/ShipDecos/LisetPropOperatorHoodDisplayBlack"
    assert r.resolve("Seeker of Truth") == "/Lotus/Types/Items/Titles/ArbitersOfHexisTitle"


def test_leading_article_and_class_word():
    r = _resolver()
    assert (
        r.resolve("The Perrin Sequence Stencil")
        == "/Lotus/Types/Game/QuartersWallpapers/SyndicatePSWallpaper"
    )
    assert (
        r.resolve("Voidrig Necramech Blueprint")
        == "/Lotus/Types/Recipes/DeimosRecipes/Mechs/NecromechBlueprint"
    )


def test_spacing_differences_and_aliases():
    r = _resolver()
    assert (
        r.resolve("AstralBond (companion)") == "/Lotus/Types/Sentinels/SentinelPrecepts/VoidBond/VoidVinculum"
    )
    assert r.resolve("1000X Ducats") == "/Lotus/Types/Items/MiscItems/PrimeBucks"


def test_known_drop_table_misspellings():
    r = NameResolver()
    r.add_item("Kubrodon Ventkid Cuirass", "/Lotus/Upgrades/Skins/Operator/BodySuits/BodySuitO")
    r.add_recipe("Kubrodon Ventkid Cuirass", "/Lotus/Types/Recipes/Operator/BodySuitOBlueprint")
    assert (
        r.resolve("Kubrodon Ventikid Cuirass Blueprint") == "/Lotus/Types/Recipes/Operator/BodySuitOBlueprint"
    )


def test_exact_names_win_over_fallbacks_and_placeholders_stay_unresolved():
    r = _resolver()
    r.add_item("Abating Link (Trinity)", "/Exact/Match")
    r.add_item("Vosfor Cache", "/Lotus/Types/StoreItems/Packages/Calendar/CalendarVosforPack")
    assert r.resolve("Abating Link (Trinity)") == "/Exact/Match"
    assert r.resolve("Vosfor Cache (200x)") == "/Lotus/Types/StoreItems/Packages/Calendar/CalendarVosforPack"
    assert r.resolve("Region Resource") is None
    assert r.resolve("Gas Can") is None
    assert set(r.unresolved) == {"Region Resource", "Gas Can"}
