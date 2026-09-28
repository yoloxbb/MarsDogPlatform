#!/usr/bin/env bash

# Source this file before starting external ROS2 participants such as
# RealSense or the standalone camera driver. Project launch files set the
# same variables automatically for their child nodes.

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
unset _marsdog_fastdds_script_dir _marsdog_fastdds_profile
