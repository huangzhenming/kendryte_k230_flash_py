"""Media-type coverage, without needing one board per storage type.

Only two things in the host depend on the media type, and both are lookups:

  1. which loader binary gets pushed over BootROM   (K230BROMBurner.get_loader)
  2. which media byte goes into DEV_PROBE           (K230UBOOTBurner.__init__)

`part_flags` is hardcoded to 0 -- the host never sends media-specific write
flags, not even SPI NAND's OOB flag -- so everything else that differs per medium
happens inside the loader, on the device. That means a board per medium buys
almost nothing for host-side changes; these tests cover the difference instead.

What a real board is still needed for is validating a *rebuilt loader binary*.
See tests/README.md.
"""

import pytest
from helpers.fake_usb import FakeKburnDevice

from k230_flash import burners
from k230_flash.burners import K230BROMBurner, K230UBOOTBurner

# The loader is chosen by medium; eMMC and SD share one because both are MMC.
EXPECTED_LOADER = {
    "EMMC": "loader_mmc.bin",
    "SDCARD": "loader_mmc.bin",
    "SPI_NAND": "loader_spi_nand.bin",
    "SPI_NOR": "loader_spi_nor.bin",
}

EXPECTED_PROBE_BYTE = {
    "EMMC": burners.KBURN_MEDIUM_EMMC,
    "SDCARD": burners.KBURN_MEDIUM_SDCARD,
    "SPI_NAND": burners.KBURN_MEDIUM_SPI_NAND,
    "SPI_NOR": burners.KBURN_MEDIUM_SPI_NOR,
    "OTP": burners.KBURN_MEDIUM_OTP,
}


@pytest.mark.parametrize("media,expected", sorted(EXPECTED_LOADER.items()))
def test_media_selects_the_right_loader(media, expected):
    """Pushing the wrong loader is silently wrong: it boots and answers EP0, then
    fails to find the medium. Cheaper to catch here than on a bench."""
    burner = K230BROMBurner.__new__(K230BROMBurner)  # no USB needed for the lookup

    assert burner.get_loader_path(expected).endswith(expected)
    path = burner.get_loader_path(EXPECTED_LOADER[media])
    assert path.endswith(expected)


@pytest.mark.parametrize("media,expected", sorted(EXPECTED_LOADER.items()))
def test_each_loader_ships_and_looks_like_a_binary(media, expected):
    """Guards the packaging: package-data covers loaders/*.bin, and a wheel that
    dropped one would only fail at flash time on a user's bench."""
    from pathlib import Path

    burner = K230BROMBurner.__new__(K230BROMBurner)
    path = Path(burner.get_loader_path(expected))

    assert path.is_file(), f"{expected} is missing from the package"
    assert path.stat().st_size > 100_000, f"{expected} is implausibly small"


@pytest.mark.parametrize("media,expected", sorted(EXPECTED_PROBE_BYTE.items()))
def test_media_maps_to_the_right_probe_byte(media, expected):
    """DEV_PROBE carries this byte; the wrong value makes the loader probe the
    wrong controller and report 'no suitable device'."""
    burner = K230UBOOTBurner(FakeKburnDevice(), media)

    assert burner.media_type == expected


def test_unknown_media_is_rejected():
    with pytest.raises(ValueError):
        K230UBOOTBurner(FakeKburnDevice(), "FLOPPY")


def test_otp_is_accepted_for_probing_but_has_no_loader():
    """OTP is a real probe target but cannot be reached from BootROM.

    The CLI and README advertise OTP and the loader stage can write it, but no
    loader_otp.bin ships, so there is nothing to *boot* into. That used to
    surface as a bare "Unsupported media_type: OTP", indistinguishable from a
    typo'd media name. It now names the actual constraint and the way out.
    """
    assert K230UBOOTBurner(FakeKburnDevice(), "OTP").media_type == burners.KBURN_MEDIUM_OTP

    burner = K230BROMBurner.__new__(K230BROMBurner)
    with pytest.raises(burners.LoaderError) as exc:
        burner.get_loader("OTP")

    message = str(exc.value)
    assert "OTP" in message
    assert "--loader-file" in message, "should point at the one way OTP can be reached"


def test_genuinely_unknown_media_is_rejected_differently_from_otp():
    """A typo must not be reported as 'no built-in loader for this medium'."""
    burner = K230BROMBurner.__new__(K230BROMBurner)

    with pytest.raises(ValueError) as exc:
        burner.get_loader("FLOPPY")

    assert not isinstance(exc.value, burners.LoaderError)


@pytest.mark.parametrize("media", sorted(EXPECTED_LOADER))
def test_loader_is_read_back_intact(media):
    """get_loader() returns the bytes that get pushed over EP0; a truncated read
    would boot a corrupt loader."""
    from pathlib import Path

    burner = K230BROMBurner.__new__(K230BROMBurner)
    data = burner.get_loader(media)
    on_disk = Path(burner.get_loader_path(EXPECTED_LOADER[media])).read_bytes()

    assert data == on_disk


@pytest.mark.parametrize("media", sorted(EXPECTED_LOADER))
def test_shipped_loaders_carry_the_expected_provenance(media):
    """The shipped loaders come from a known u-boot commit and must include the
    PUF-UID serial-number patch. Without it Windows reuses the BootROM device
    node and serves a stale descriptor, which is invisible until someone flashes
    from Windows -- so pin it here instead.
    """
    from pathlib import Path

    burner = K230BROMBurner.__new__(K230BROMBurner)
    blob = Path(burner.get_loader_path(EXPECTED_LOADER[media])).read_bytes()

    assert b"U-Boot 2022.10-00049-gc4c3f349" in blob, (
        "loader was rebuilt from a different commit; update this test and " "docs/internal/notes.md together"
    )
    assert b"K230-" in blob, "loader appears to lack the PUF-UID serial number patch"


# --- the GUI feeds these same names in over the CLI ---------------------------


def _gui_media_values(source_path):
    """Pull the media strings out of a GUI file's `get_media_type` map.

    Read from source rather than imported: the GUI needs PySide6, which is not a
    test dependency and is excluded from the pip package.
    """
    import ast

    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "get_media_type":
            for sub in ast.walk(node):
                if isinstance(sub, ast.Dict):
                    return {v.value for v in sub.values if isinstance(v, ast.Constant)}
    raise AssertionError(f"no get_media_type media map found in {source_path}")


@pytest.mark.parametrize("gui_file", ["single_flash.py", "batch_flash.py"])
def test_gui_media_names_match_the_library(gui_file):
    """The GUI builds a command line and hands it to k230_flash.main, so its
    media strings must be ones the library accepts.

    They were "SPINAND"/"SPINOR" -- no underscore -- which no burner has ever
    accepted, so the Nand Flash and NOR Flash radio buttons could not flash at
    all. Nothing connected the two lists, so nothing caught it.
    """
    from pathlib import Path

    from k230_flash.constants import MEDIA_TYPES

    gui_source = Path(__file__).resolve().parents[2] / "src" / "gui" / gui_file
    values = _gui_media_values(gui_source)

    assert values, "expected to find media names in the GUI"
    assert values <= set(MEDIA_TYPES), f"GUI offers media the library rejects: {sorted(values - set(MEDIA_TYPES))}"
