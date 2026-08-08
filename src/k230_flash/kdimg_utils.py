# kdimg_utils.py
from pathlib import Path

from loguru import logger

from .kdimage import KburnKdImage, get_kdimage_items, get_kdimage_max_offset


def write_kdimg(kdimg_path, burner, selected_partitions=None):
    """Write a single .kdimg file

    :param kdimg_path: Path to the .kdimg file
    :param burner: The burner instance
    :param selected_partitions: List of partition names to flash (if None, flash all)
    """

    # These used to `return False`/`return` on failure while the caller ignored the
    # return value, so a rejected image or an unwritten partition was reported to
    # the user as a successful flash. They raise now.
    max_offset = get_kdimage_max_offset(kdimg_path)
    logger.info(f"kdimage 最大偏移量: {max_offset // (1024*1024)} MB (0x{max_offset:08X})")
    if max_offset > burner.capacity:
        raise ValueError(
            f"kdimg 超出设备容量: 需要 {max_offset // (1024*1024)} MB, " f"设备容量 {burner.capacity // (1024*1024)} MB"
        )

    kdimg = KburnKdImage.instance(kdimg_path)

    kdimg_items = get_kdimage_items(kdimg_path)
    if not kdimg_items:
        raise ValueError(f"无法解析 kdimg 文件: {kdimg_path}")

    written = 0
    # Write in partition order
    for item in kdimg_items.data:
        # Skip partition if selected_partitions is specified and this partition is not in the list
        if selected_partitions and item.partName not in selected_partitions:
            logger.debug(f"Skipping partition {item.partName} (not in selected partitions)")
            continue

        logger.info(f"烧录分区: {item.partName} (0x{item.partOffset:08X}, {item.partSize // 1024} KB)")
        part_data = kdimg.read_part_data(item)
        if part_data is None:
            raise ValueError(f"读取分区 {item.partName} 数据失败（校验不通过或文件损坏）")
        burner.write_image(part_data, item.partOffset)
        written += 1

    if selected_partitions:
        missing = set(selected_partitions) - {i.partName for i in kdimg_items.data}
        if missing:
            raise ValueError(f"kdimg 中不存在指定的分区: {', '.join(sorted(missing))}")
    if written == 0:
        raise ValueError("没有任何分区被烧录")

    return True
