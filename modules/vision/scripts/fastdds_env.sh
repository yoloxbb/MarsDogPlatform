#!/usr/bin/env bash

# Source this file before starting external ROS2 participants such as
# RealSense or the standalone camera driver. Project launch files apply the
# same Fast DDS configuration and optional patched runtime to their child nodes.

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
  echo "source this file instead of executing it: source $0" >&2
  exit 1
fi

_marsdog_fastdds_script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
if [[ -f "${_marsdog_fastdds_script_dir}/../config/fastdds.xml" ]]; then
  _marsdog_fastdds_profile="${_marsdog_fastdds_script_dir}/../config/fastdds.xml"
else
  _marsdog_fastdds_profile="${_marsdog_fastdds_script_dir}/config/fastdds.xml"
fi
export RMW_IMPLEMENTATION=rmw_fastrtps_cpp
export FASTRTPS_DEFAULT_PROFILES_FILE="${MARSDOG_FASTDDS_PROFILE:-${_marsdog_fastdds_profile}}"
# This project uses the XML file for transport configuration only. Keep ROS2's
# default writer/reader memory policy for variable-length messages such as
# /rosout unless explicit XML entity QoS profiles are added later.
export RMW_FASTRTPS_USE_QOS_FROM_XML=0

# Prefer the project-built Fast DDS 2.6.12 overlay when present. This helper is
# installed beside this script and is also available from the source checkout.
if [[ -f "${_marsdog_fastdds_script_dir}/fastdds_overlay.py" ]]; then
  _marsdog_fastdds_overlay_helper="${_marsdog_fastdds_script_dir}/fastdds_overlay.py"
else
  _marsdog_fastdds_overlay_helper="${_marsdog_fastdds_script_dir}/../marsdog_vision_interaction/fastdds_overlay.py"
fi
if ! _marsdog_fastdds_library_path="$(python3 "${_marsdog_fastdds_overlay_helper}" --print-library-path)"; then
  unset _marsdog_fastdds_script_dir _marsdog_fastdds_profile _marsdog_fastdds_overlay_helper _marsdog_fastdds_library_path
  return 2
fi
export LD_LIBRARY_PATH="${_marsdog_fastdds_library_path}"
unset _marsdog_fastdds_script_dir _marsdog_fastdds_profile _marsdog_fastdds_overlay_helper _marsdog_fastdds_library_path
