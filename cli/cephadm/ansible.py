from cli import Cli
from cli.utilities.utils import config_dict_to_string

CEPHADM_ANSIBLE_PATH = "/usr/share/cephadm-ansible"
CEPHADM_INVENTORY_PATH = f"{CEPHADM_ANSIBLE_PATH}/hosts"


class CephAdmAnsibleError(Exception):
    pass


class Ansible(Cli):
    """module to provide CLI interface for cephadm-ansible."""

    def __init__(self, nodes):
        super(Ansible, self).__init__(nodes)

        self.base_cmd = f"cd {CEPHADM_ANSIBLE_PATH}; ansible-playbook -vvvv"

    def run_playbook(
        self,
        playbook,
        inventory_path=CEPHADM_INVENTORY_PATH,
        extra_vars=None,
        extra_args=None,
    ):
        """module to execute cephadm-ansible playbooks.

        Args:
            playbook (str): cephadm-ansible playbook file name
            inventory_path (str): inventory file path to be used in playbook execution
            extra_vars (str): extra ansible CLI variables (ex., -e 'key=value')
            extra_args (str): extra ansible CLI arguments (ex., --limit osds)
        """
        cmd = f"{self.base_cmd} -i {inventory_path} {playbook}"
        if extra_vars:
            for k, v in extra_vars.items():
                cmd += f" -e '{k}={v}'"
        if extra_args:
            cmd += config_dict_to_string(extra_args)

        if self.execute(long_running=True, cmd=cmd):
            raise CephAdmAnsibleError(
                f"Failed to execute cephadm ansible playbook '{playbook}'"
            )
