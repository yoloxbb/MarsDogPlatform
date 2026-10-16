#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
VERSION=2.6.12
CACHE_DIR="${PROJECT_DIR}/build/fastdds-${VERSION}"
SOURCE_DIR="${CACHE_DIR}/Fast-DDS-${VERSION}"
SOURCE_ARCHIVE="${CACHE_DIR}/Fast-DDS-${VERSION}.tar.gz"
ASIO_ARCHIVE="${CACHE_DIR}/asio-1-18-1.tar.gz"
ASIO_ROOT="${CACHE_DIR}/asio-asio-1-18-1"
BUILD_DIR="${CACHE_DIR}/cmake-build"
PREFIX="${MARSDOG_FASTDDS_PREFIX:-${HOME}/.local/opt/marsdog-fastdds-${VERSION}}"
JOBS="${MARSDOG_FASTDDS_BUILD_JOBS:-2}"
PATCH_FILE="${PROJECT_DIR}/patches/fastdds/0001-release-partial-change-on-writer-removal.patch"
SOURCE_URL="https://codeload.github.com/eProsima/Fast-DDS/tar.gz/refs/tags/v${VERSION}"
ASIO_URL="https://codeload.github.com/chriskohlhoff/asio/tar.gz/refs/tags/asio-1-18-1"
SOURCE_SHA256=53476bcee331f28fe83e8387122fb7f84ab39209c459bd2cc227c71e4bd21c9b
ASIO_SHA256=39c721b987b7a0d2fe2aee64310bd128cd8cc10f43481604d18cb2d8b342fd40

if [[ ! "${JOBS}" =~ ^[1-9][0-9]*$ ]]; then
  echo "MARSDOG_FASTDDS_BUILD_JOBS must be a positive integer" >&2
  exit 2
fi

mkdir -p "${CACHE_DIR}"
if [[ ! -f "${SOURCE_ARCHIVE}" ]]; then
  curl --fail --location --retry 3 --output "${SOURCE_ARCHIVE}.part" "${SOURCE_URL}"
  mv "${SOURCE_ARCHIVE}.part" "${SOURCE_ARCHIVE}"
fi
printf '%s  %s\n' "${SOURCE_SHA256}" "${SOURCE_ARCHIVE}" | sha256sum --check --status || {
  echo "Fast DDS ${VERSION} source archive SHA-256 mismatch: ${SOURCE_ARCHIVE}" >&2
  exit 2
}
if [[ ! -d "${SOURCE_DIR}" ]]; then
  tar -xzf "${SOURCE_ARCHIVE}" -C "${CACHE_DIR}"
fi

if [[ ! -f "${ASIO_ARCHIVE}" ]]; then
  curl --fail --location --retry 3 --output "${ASIO_ARCHIVE}.part" "${ASIO_URL}"
  mv "${ASIO_ARCHIVE}.part" "${ASIO_ARCHIVE}"
fi
printf '%s  %s\n' "${ASIO_SHA256}" "${ASIO_ARCHIVE}" | sha256sum --check --status || {
  echo "Asio 1.18.1 source archive SHA-256 mismatch: ${ASIO_ARCHIVE}" >&2
  exit 2
}
if [[ ! -d "${ASIO_ROOT}/asio/include" ]]; then
  tar -xzf "${ASIO_ARCHIVE}" -C "${CACHE_DIR}"
fi
ASIO_INCLUDE_DIR="${ASIO_ROOT}/asio/include"
if [[ ! -f "${ASIO_INCLUDE_DIR}/asio.hpp" ]]; then
  echo "Expected Asio headers are missing under ${ASIO_INCLUDE_DIR}" >&2
  exit 2
fi

if git -C "${SOURCE_DIR}" apply --check "${PATCH_FILE}" >/dev/null 2>&1; then
  git -C "${SOURCE_DIR}" apply "${PATCH_FILE}"
elif ! git -C "${SOURCE_DIR}" apply --reverse --check "${PATCH_FILE}" >/dev/null 2>&1; then
  echo "Fast DDS source is neither clean nor patched with ${PATCH_FILE}; inspect ${SOURCE_DIR}" >&2
  exit 2
fi

ROS_PREFIX="${ROS_PREFIX:-/opt/ros/humble}"
if [[ ! -f "${ROS_PREFIX}/share/fastcdr/cmake/fastcdr-config.cmake" && ! -d "${ROS_PREFIX}/include/fastcdr" ]]; then
  echo "ROS Fast CDR headers/config are unavailable under ${ROS_PREFIX}; source/install ROS 2 Humble first" >&2
  exit 2
fi

case "$(realpath -m "${PREFIX}")" in
  /opt/ros|/opt/ros/*|/usr|/usr/*)
    echo "Refusing to install the patched runtime into system ROS path ${PREFIX}; use a separate overlay prefix" >&2
    exit 2
    ;;
esac

cmake -S "${SOURCE_DIR}" -B "${BUILD_DIR}" \
  -DCMAKE_BUILD_TYPE=Release \
  -DCMAKE_INSTALL_PREFIX="${PREFIX}" \
  -DCMAKE_PREFIX_PATH="${ROS_PREFIX}" \
  -DAsio_INCLUDE_DIR="${ASIO_INCLUDE_DIR}" \
  -DSECURITY=ON \
  -DSQLITE3_SUPPORT=ON \
  -DLOG_NO_INFO=ON \
  -DNO_TLS=OFF \
  -DCOMPILE_TOOLS=OFF \
  -DCOMPILE_EXAMPLES=OFF \
  -DBUILD_TESTING=OFF \
  -DTHIRDPARTY=OFF \
  -DTHIRDPARTY_UPDATE=OFF \
  -DAPPEND_PROJECT_NAME_TO_INCLUDEDIR=ON
cmake --build "${BUILD_DIR}" --parallel "${JOBS}"
cmake --install "${BUILD_DIR}"

printf 'Installed patched Fast DDS %s into %s\n' "${VERSION}" "${PREFIX}"
printf 'The Vision launch files and scripts/fastdds_env.sh select this overlay automatically.\n'
