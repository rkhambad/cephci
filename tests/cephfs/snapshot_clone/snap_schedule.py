import json
import os
import random
import string
import traceback
from time import sleep

from ceph.ceph import CommandFailed
from tests.cephfs.cephfs_utilsV1 import FsUtils
from utility.log import Log
from utility.retry import retry

log = Log(__name__)


def run(ceph_cluster, **kw):
    """
    Test Cases Covered :
    CEPH-83575569 - Enable snap-schedule on file system and verify if snapshots are created

    Pre-requisites :
    1. We need atleast one client node to execute this test case
    2. creats fs volume create cephfs if the volume is not there
    3. ceph fs subvolumegroup create <vol_name> <group_name> --pool_layout <data_pool_name>
        Ex : ceph fs subvolumegroup create cephfs subvolgroup_snap_schedule
    4. ceph fs subvolume create <vol_name> <subvol_name> [--size <size_in_bytes>] [--group_name <subvol_group_name>]
       [--pool_layout <data_pool_name>] [--uid <uid>] [--gid <gid>] [--mode <octal_mode>]  [--namespace-isolated]
       Ex: ceph fs subvolume create cephfs subvol_2 --size 5368706371 --group_name subvolgroup_
    5. Create Data on the subvolume
        Ex:  python3 /home/cephuser/smallfile/smallfile_cli.py --operation create --threads 10 --file-size 400 --files
            100 --files-per-dir 10 --dirs-per-dir 2 --top /mnt/cephfs_fuse1baxgbpaia_1/
    6. Enable snpa-schedule
        ceph fs snap-schedule add / 1h
        ceph fs snap-schedule retention add / h 14
        ceph fs snap-schedule activate /
        ceph fs snap-schedule status /

    Clean Up:
    1. Del all the snapshots created
    2. Del Subvolumes
    3. Del SubvolumeGroups
    4. Deactivate and remove sanp_Schedule
    5. Remove FS
    """
    try:
        fs_util = FsUtils(ceph_cluster)
        config = kw.get("config")
        clients = ceph_cluster.get_ceph_objects("client")
        build = config.get("build", config.get("rhbuild"))
        fs_util.prepare_clients(clients, build)
        fs_util.auth_list(clients)
        log.info("checking Pre-requisites")
        if len(clients) < 1:
            log.info(
                f"This test requires minimum 1 client nodes.This has only {len(clients)} clients"
            )
            return 1
        default_fs = "cephfs_snap"
        mounting_dir = "".join(
            random.choice(string.ascii_lowercase + string.digits)
            for _ in list(range(10))
        )
        client1 = clients[0]
        fs_details = fs_util.get_fs_info(client1, fs_name=default_fs)
        if not fs_details:
            fs_util.create_fs(client1, default_fs)
        subvolumegroup_list = [
            {"vol_name": default_fs, "group_name": "subvolgroup_snap_schedule"},
        ]
        for subvolumegroup in subvolumegroup_list:
            fs_util.create_subvolumegroup(client1, **subvolumegroup)

        kernel_mounting_dir_1 = f"/mnt/cephfs_kernel{mounting_dir}_1/"
        mon_node_ips = fs_util.get_mon_node_ips()
        retry_mount = retry(CommandFailed, tries=3, delay=30)(fs_util.kernel_mount)
        retry_mount(
            [client1],
            kernel_mounting_dir_1,
            ",".join(mon_node_ips),
            extra_params=f",fs={default_fs}",
        )

        client1.exec_command(
            sudo=True,
            cmd=f"python3 /home/cephuser/smallfile/smallfile_cli.py --operation create --threads 10 --file-size 400 "
            f"--files 100 --files-per-dir 10 --dirs-per-dir 2 --top "
            f"{kernel_mounting_dir_1}",
            long_running=True,
        )
        client1.exec_command(
            sudo=True, cmd=f"mkdir -p {kernel_mounting_dir_1}/dir_kernel"
        )

        log.info("Enable Snap Schedule")
        client1.exec_command(
            sudo=True, cmd=f"mkdir -p {kernel_mounting_dir_1}/snap_schedule"
        )
        fuse_mounting_dir_1 = f"/mnt/cephfs_fuse{mounting_dir}_1/"
        fs_util.fuse_mount(
            [client1],
            fuse_mounting_dir_1,
            extra_params=f"--client_fs {default_fs}",
        )
        client1.exec_command(sudo=True, cmd=f"mkdir -p {fuse_mounting_dir_1}/dir_fuse")
        sanp_schedule_list = ["/dir_kernel", "/dir_fuse"]
        commands = [
            "ceph config set mgr mgr/snap_schedule/allow_m_granularity true",
            "ceph mgr module enable snap_schedule",
            f"ceph fs snap-schedule add path 1M --fs {default_fs}",
            f"ceph fs snap-schedule activate path --fs {default_fs}",
        ]
        modified_commands = [
            cmd.replace("path", item) for item in sanp_schedule_list for cmd in commands
        ]

        for cmd in modified_commands:
            client1.exec_command(sudo=True, cmd=cmd)
        sleep(300)
        verify_snap_schedule(client1, f"{fuse_mounting_dir_1}dir_fuse/")
        verify_snap_schedule(client1, f"{kernel_mounting_dir_1}dir_kernel/")

        return 0
    except Exception as e:
        log.error(e)
        log.error(traceback.format_exc())
        return 1
    finally:
        log.info("Clean Up in progess")
        commands = [
            "ceph fs snap-schedule deactivate path --fs cephfs_snap",
            "ceph fs snap-schedule remove path --fs cephfs_snap",
            "ceph config set mgr mgr/snap_schedule/allow_m_granularity false",
        ]
        modified_commands = [
            cmd.replace("path", item) for item in sanp_schedule_list for cmd in commands
        ]
        for cmd in modified_commands:
            client1.exec_command(sudo=True, cmd=cmd)
        commands = [
            "ceph config set mon mon_allow_pool_delete true",
            f"ceph fs volume rm {default_fs} --yes-i-really-mean-it",
        ]
        for cmd in commands:
            client1.exec_command(sudo=True, cmd=cmd)


def verify_snap_schedule(client, path):
    out, rc = client.exec_command(sudo=True, cmd=f"ls -lrt {path}.snap/ | wc -l")
    log.info(out)
    log.info(int(out))
    if not (int(out) >= 4):
        raise CommandFailed("It has not created the snaps")
    schedule_path = os.path.basename(os.path.normpath(path))
    out, rc = client.exec_command(
        sudo=True,
        cmd=f"ceph fs snap-schedule list /{schedule_path} --recursive --fs cephfs_snap",
    )
    log.info("snap-schedule list")
    log.info(out)
    if "1M" not in out:
        raise CommandFailed("Snap Schedule is not getting listed")
    out, rc = client.exec_command(
        sudo=True,
        cmd=f"ceph fs snap-schedule status /{schedule_path} -f json --fs cephfs_snap",
    )
    log.info("snap-schedule Status")
    log.info(out)
    schedule_ls = json.loads(out)
    log.info(schedule_ls[0]["schedule"])
    if schedule_ls[0]["schedule"] != "1M":
        raise CommandFailed("Snap Schedule is not returning status")
