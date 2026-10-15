#!/usr/bin/env python3
"""Prepare pinned, preserved UniUbi sources and a separate RK3588 build workspace."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import tarfile
import urllib.request

ROOT = Path(os.environ.get('MARSDOG_ROOT', '/home/marsdog/MarsDogPlatform')).expanduser().resolve()
PROFILE = os.environ.get('LINGMAO_PROFILE', 'legacy')
if PROFILE not in ('legacy', 'modern'):
    raise ValueError('LINGMAO_PROFILE must be legacy or modern')
BASE = ROOT / ('out/rk3588-lingmao-communication-legacy' if PROFILE == 'legacy' else 'out/rk3588-lingmao-communication')
ROS_SOURCE = ('uniubi_ros2', 'e497ca0b06ffd20d1f0d088b935fe0bce3459050',
              '34dbf0aaf8e501fe9ac0894a0c19d98733d7fd9d295b85dafac95ae7f3487372') if PROFILE == 'legacy' else (
              'uniubi_ros2', '6e6edc057e4e232659566f0dc05e1b18393d5e1b',
              '74db5f71c90bc21aa8813994639e41fb2330a3fc74174209008f0362efc12421')
SOURCES = [ROS_SOURCE,
    ('uniubi_robot_msgs', '0716257e262c4b3f5d8424c6ddf284309fcac7fc',
     'fe7d2611350242007699bfb03811ce3e053d2c377f61fd17609ef37544a541c6'),
]
DDS_MULTICAST = '' if PROFILE == 'legacy' else '<AllowMulticast>spdp</AllowMulticast>'

def main():
    if not (ROOT / 'AGENTS.md').is_file():
        raise RuntimeError('MARSDOG_ROOT must point to the existing MarsDogPlatform repository')
    records = []
    for name, commit, digest in SOURCES:
        archive = BASE / 'archives' / f'{name}-{commit}.tar.gz'
        archive.parent.mkdir(parents=True, exist_ok=True)
        url = f'https://codeload.github.com/uniubi-ai/{name}/tar.gz/{commit}'
        if not archive.exists():
            pending = archive.with_suffix('.download')
            with urllib.request.urlopen(url, timeout=60) as response, pending.open('wb') as target:
                shutil.copyfileobj(response, target)
            if hashlib.sha256(pending.read_bytes()).hexdigest() != digest:
                raise RuntimeError('Downloaded archive SHA256 mismatch: ' + name)
            pending.replace(archive)
        if hashlib.sha256(archive.read_bytes()).hexdigest() != digest:
            raise RuntimeError('Archive SHA256 mismatch: ' + name)
        preserved = BASE / 'preserved' / name
        if not preserved.exists():
            preserved.mkdir(parents=True)
            with tarfile.open(archive) as source:
                for member in source.getmembers():
                    parts = Path(member.name).parts
                    if '..' in parts or Path(member.name).is_absolute() or member.issym() or member.islnk():
                        raise RuntimeError('Unsupported archive member: ' + member.name)
                    if len(parts) < 2:
                        continue
                    target = preserved.joinpath(*parts[1:])
                    if member.isdir():
                        target.mkdir(parents=True, exist_ok=True)
                    elif member.isfile():
                        target.parent.mkdir(parents=True, exist_ok=True)
                        with source.extractfile(member) as stream, target.open('wb') as output:
                            shutil.copyfileobj(stream, output)
                        target.chmod(member.mode & 0o777)
                    else:
                        raise RuntimeError('Unsupported archive member: ' + member.name)
        work = BASE / 'source' / name
        if not work.exists():
            shutil.copytree(preserved, work)
        records.append(dict(name=name, commit=commit, archive_sha256=digest,
                            url=url, preserved=str(preserved), source=str(work)))
    (BASE / 'source-provenance.json').write_text(json.dumps(records, indent=2) + '\n')
    (BASE / 'native-env.sh').write_text(
        '#!/usr/bin/env bash\nsource "' + str(ROOT / 'out/rk3588-navigation/native-env.sh') + '"\n')
    (BASE / 'use-lingmao-communication.sh').write_text(
        '#!/usr/bin/env bash\n'
        'source "' + str(ROOT / 'out/rk3588-navigation/use-navigation.sh') + '"\n'
        'source "' + str(BASE / 'install/local_setup.bash') + '"\n'
        'export LINGMAO_PROFILE=' + PROFILE + '\n'
        'if [[ -f "' + str(BASE / 'robot.env') + '" ]]; then source "' + str(BASE / 'robot.env') + '"; fi\n'
        'export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp\n'
        'export ROS_DOMAIN_ID=42 ROS_LOCALHOST_ONLY=0\n'
        'export CYCLONEDDS_URI=\'<CycloneDDS><Domain Id="any"><General><Interfaces><NetworkInterface name="eth0"/></Interfaces>' + DDS_MULTICAST + '<DontRoute>true</DontRoute></General></Domain></CycloneDDS>\'\n')
    print(json.dumps({'status': 'PREPARED', 'profile': PROFILE, 'base': str(BASE), 'packages': ['uniubi', 'uniubi_motion_client', 'uniubi_motion_bridge']}))

if __name__ == '__main__':
    main()
