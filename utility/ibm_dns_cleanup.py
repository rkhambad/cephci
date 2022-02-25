"""
    Utility to cleanup orphan DNS record from IBM environment
"""
import math
import sys
from typing import Dict

import yaml
from docopt import docopt

from compute.ibm_vpc import get_dns_service, get_dns_zone_id, get_ibm_service

instance_id = "a55534f5-678d-452d-8cc6-e780941d8e31"

doc = """
Utility to cleanup orphan DNS record from IBM cloud.
    Usage:
        ibm_dns_cleanup.py --creds <cred-file>
        ibm_dns_cleanup.py (-h | --help)
    Options:
        -h --help          Shows the command usage
        --creds <file>     API Credential file to access ibm cloud.
                           sample/example <file>:
                           globals:
                                ibm-credentials:
                                    access-key: '<user_access_key>'
                                    service-url: 'https://xxxx.iaas.cloud.ibm.com/v1'
                                    zone_name: '<dns_zone>'
                                    vpc_name: '<vpc_name>'
"""


def run(args: Dict):
    """
    Using the provided credential file, this method removes the orphan DNS entries from ibm cloud.
    Arguments:
        args: Dict - containing the key/value pairs passed by the user

    Returns:
        0 on success or 1 for failures
    """
    cred_file = args["--creds"]

    with open(cred_file, "r") as cred_stream:
        yh = yaml.safe_load(cred_stream)
        ibm_cred = yh["globals"]["ibm-credentials"]
        ibmc_client = get_ibm_service(
            access_key=ibm_cred["access-key"], service_url=ibm_cred["service-url"]
        )
        dns_client = get_dns_service(access_key=ibm_cred["access-key"])
        dns_zone = dns_client.list_dnszones(instance_id)
        if dns_zone.get_status_code() != 200:
            print(f"Failed to get dns zone for given instance id: {instance_id}")
            return 1
        dns_zone_id = get_dns_zone_id(ibm_cred["zone_name"], dns_zone.get_result())
        resource = dns_client.list_resource_records(
            instance_id=instance_id, dnszone_id=dns_zone_id
        )
        if resource.get_status_code() != 200:
            print(f"Failed to get dns records from zone: {ibm_cred['zone_name']}")
            return 1
        records = resource.get_result()
        resp = ibmc_client.list_instances(limit=10, vpc_name=ibm_cred["vpc_name"])
        if resp.get_status_code() != 200:
            print("Failed to retrieve instances")
            return 1
        response = resp.get_result()
        print(response)
        if "next" in response.keys():
            start = response["next"]["href"].split("start=")[-1]
            for i in range(1, (math.ceil(response["total_count"]/response["limit"]))):
                list_instance = ibmc_client.list_instances(start=start, limit=10, vpc_name=ibm_cred["vpc_name"])
                if list_instance.get_status_code() != 200:
                    print("Failed to retrieve instances")
                    return 1
                instances = list_instance.get_result()
                print(f"instance {instances}")
                response["instances"] += instances["instances"]
                if "next" in instances.keys():
                    start = instances["next"]["href"].split("start=")[-1]
                
        print(f"len(response['instances']) : {len(response['instances'])}")
        print(f"response['total_count'] : {response['total_count']}")
        ip_address = [
            i["primary_network_interface"]["primary_ipv4_address"]
            for i in response["instances"]
        ]
        print(ip_address)
        instance_name = [i["name"] for i in response["instances"]]
        print(instance_name)

        for record in records["resource_records"]:
            if record["type"] == "A" and not record['name'].startswith("ceph-ge"):
                print(record['linked_ptr_record']['name'])
                print(record['name'])
#                 if record.get("linked_ptr_record"):
#                     print(f"Deleting PTR record {record['linked_ptr_record']['name']}")
#                     dns_client.delete_resource_record(
#                         instance_id=instance_id,
#                         dnszone_id=dns_zone_id,
#                         record_id=record["linked_ptr_record"]["id"],
#                     )

#                 print(f"Deleting Address record {record['name']}")
#                 dns_client.delete_resource_record(
#                     instance_id=instance_id,
#                     dnszone_id=dns_zone_id,
#                     record_id=record["id"],
#                 )

        print("\nSuccessfully removed the orphan DNS record from IBM environment\n")
    return 0


if __name__ == "__main__":
    arguments = docopt(doc)
    rc = run(arguments)
