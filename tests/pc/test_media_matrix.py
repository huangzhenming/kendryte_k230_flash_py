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
    """Known inconsistency, pinned here so it is visible rather than surprising.

    The CLI and README advertise OTP, and it is accepted as a probe target, but
    no OTP loader ships -- so `-m OTP` against a board in BootROM fails with a
    bare "Unsupported media_type". It only works if the device is already running
    a loader. Worth either shipping an OTP loader, dropping OTP from the CLI, or
    giving a clearer error.
    """
    assert K230UBOOTBurner(FakeKburnDevice(), "OTP").media_type == burners.KBURN_MEDIUM_OTP

    burner = K230BROMBurner.__new__(K230BROMBurner)
    with pytest.raises(ValueError, match="OTP"):
        burner.get_loader("OTP")


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
