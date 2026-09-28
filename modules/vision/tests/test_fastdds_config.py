from pathlib import Path
import xml.etree.ElementTree as ET


def test_project_fastdds_profile_sets_shm_to_8_mib() -> None:
    root = Path(__file__).resolve().parents[1]
    xml_root = ET.parse(root / "config" / "fastdds.xml").getroot()
    namespace = "{http://www.eprosima.com/XMLSchemas/fastRTPS_Profiles}"
    descriptors = xml_root.findall(
        f".//{namespace}transport_descriptor"
    )
    by_type = {
        descriptor.findtext(f"{namespace}type"): descriptor
        for descriptor in descriptors
    }

    shm = by_type["SHM"]
    udp = by_type["UDPv4"]
    assert shm.findtext(f"{namespace}maxMessageSize") == "8388608"
    assert shm.findtext(f"{namespace}segment_size") == "33554432"
    assert udp.findtext(f"{namespace}maxMessageSize") == "65500"


def test_launch_files_load_project_fastdds_profile() -> None:
    root = Path(__file__).resolve().parents[1]
    for name in ("vision.launch.py", "vision_debug.launch.py"):
        source = (root / "launch" / name).read_text(encoding="utf-8")
        assert "FASTRTPS_DEFAULT_PROFILES_FILE" in source
        assert 'config", "fastdds.xml' in source
