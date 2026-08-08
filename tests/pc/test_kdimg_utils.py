"""Tests for the .kdimg write loop (kdimg_utils.py).

Every path here used to `return False` while the caller ignored the return
value, so a rejected image or an unwritten partition was reported to the user as
a successful flash. These assert they raise instead.
"""

import pytest
from helpers.fake_usb import FakeKburnDevice
from helpers.kdimg_builder import Partition, write_kdimg_file

from k230_flash.burners import K230UBOOTBurner
from k230_flash.kdimage import KburnKdImage
from k230_flash.kdimg_utils import write_kdimg


@pytest.fixture(autouse=True)
def _reset_singleton():
    KburnKdImage.deleteInstance()
    yield
    KburnKdImage.deleteInstance()


@pytest.fixture
def burner():
    b = K230UBOOTBurner(FakeKburnDevice(capacity=64 * 1024 * 1024), "SDCARD")
    b.probe()
    b.get_capacity()
    return b


@pytest.fixture
def image(tmp_path):
    return write_kdimg_file(
        tmp_path / "fw.kdimg",
        [
            Partition("uboot_a", offset=0x0, data=b"\x11" * 512),
            Partition("rtt", offset=0x100000, data=b"\x22" * 1024),
        ],
    )


def test_writes_every_partition(burner, image):
    assert write_kdimg(image, burner) is True

    offsets = [offset for offset, _size, _data in burner.dev.sessions]
    assert offsets == [0x0, 0x100000]
    assert burner.dev.sessions[0][2] == b"\x11" * 512


def test_selected_partitions_limits_what_is_written(burner, image):
    write_kdimg(image, burner, selected_partitions=["rtt"])

    assert [o for o, _s, _d in burner.dev.sessions] == [0x100000]


def test_unknown_selected_partition_is_reported(burner, image):
    """Asking for a partition the image does not contain used to silently write
    nothing and exit successfully."""
    with pytest.raises(ValueError) as exc:
        write_kdimg(image, burner, selected_partitions=["does_not_exist"])

    assert "does_not_exist" in str(exc.value)


def test_image_larger_than_the_device_is_rejected(burner, tmp_path):
    """The capacity check existed but only logged and returned False."""
    too_big = write_kdimg_file(
        tmp_path / "big.kdimg",
        [Partition("huge", offset=0, data=b"\x00" * 16, size=16, max_size=128 * 1024 * 1024)],
    )

    with pytest.raises(ValueError) as exc:
        write_kdimg(too_big, burner)

    assert "容量" in str(exc.value) or "capacity" in str(exc.value).lower()


def test_unparseable_image_is_rejected(burner, tmp_path):
    broken = tmp_path / "broken.kdimg"
    broken.write_bytes(b"not a kdimg at all" * 64)

    with pytest.raises(ValueError):
        write_kdimg(broken, burner)


def test_corrupt_partition_payload_is_rejected(burner, tmp_path):
    """A SHA-256 mismatch means read_part_data returns None; writing that to a
    board would brick it, so the flash must stop."""
    from helpers.kdimg_builder import build_kdimg

    img = tmp_path / "bad_sha.kdimg"
    img.write_bytes(build_kdimg([Partition("uboot_a", offset=0, data=b"\x11" * 512)], corrupt_sha_of="uboot_a"))

    with pytest.raises(ValueError):
        write_kdimg(img, burner)

    assert burner.dev.sessions == [], "nothing should have been written"
