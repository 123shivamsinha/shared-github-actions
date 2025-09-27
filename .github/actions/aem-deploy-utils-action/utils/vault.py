"""retrieve vault details from AEM target servers"""
import subprocess
import os
import json
import time
import logging
import yaml
import csv
from pathlib import Path

operation = os.getenv('OPERATION')
workspace = os.getenv('GITHUB_WORKSPACE')
context = os.getenv('CONTEXT')
COLOR_RED = "\u001b[31m"
COLOR_GREEN = "\u001b[32m"
log_level = os.getenv('LOG_LEVEL') if os.getenv('LOG_LEVEL') else '20'
logging.basicConfig(level=int(log_level), format='%(asctime)s :: %(levelname)s :: %(message)s')


def get_vault_details(deploy_env):
    """fetch manifest from environment"""
    try:
        vault_env_details = {}
        props_path = os.getenv('PROPS_PATH')
        vault_cmd = f'''ANSIBLE_FORCE_COLOR=false && ANSIBLE_NOCOLOR=true && cd {props_path}/ansible && ansible {deploy_env} -m debug -a var=hostvars[inventory_hostname] --vault-password-file={workspace}/ansible.txt | sed -e "s/{deploy_env} | SUCCESS => //"'''
        vault_details = subprocess.run(vault_cmd, shell=True, capture_output=True, check=False)
        if vault_details.returncode != 0:
            raise RuntimeError(f'Error getting vault details: {vault_details.stderr.decode()}')
        vault_response = yaml.safe_load(vault_details.stdout.decode()).get('hostvars[inventory_hostname]')

        for aem_env in ['aem_author', 'aem_publisher']:
            env_server_list = vault_response.get(aem_env,{}).get('server_ip')
            if env_server_list is None: # kpo
                continue
            env_username = vault_response.get(f'{aem_env}_username')
            env_password = vault_response.get(f'{aem_env}_password')
            env_credentials = f'{env_username}:{env_password}'
            env_host = vault_response.get(aem_env).get('http_port')
            env_hosts = vault_response.get(aem_env).get('https_port')
            env_details = {}
            env_details['server'] = []
            env_details['aem_creds'] = env_credentials
            for server in env_server_list:
                auth_server = f'http://{server}'
                if env_host:
                    auth_server = f'http://{server}:{env_host}'
                elif env_hosts:
                    auth_server = f'https://{server}:{env_hosts}'
                env_details['server'].append(auth_server)
            vault_env_details[aem_env] = env_details

        # check server status
        vault_env_details = check_server_status(vault_env_details)
        if operation == 'generate-csv':
            package_details = get_package_details(vault_env_details)
            generate_csv_output(package_details)
            logging.info('\n%sEnv Manifest Map:\n%s', COLOR_GREEN, yaml.safe_dump(package_details))
            os.system(f"echo 'env-manifest-packages={json.dumps(package_details)}' >> $GITHUB_OUTPUT")
        masked_details = json.dumps(vault_env_details)
        os.system(f"echo '::add-mask::{masked_details}' && echo 'vault-map={masked_details}' >> $GITHUB_OUTPUT")
    except (json.JSONDecodeError, RuntimeError) as e:
        raise RuntimeError(f'Error retrieving vault details: {e}') from None


def check_server_status(vault_env_details):
    """check server status and download manifest"""
    for key, value in vault_env_details.items():
        aem_creds = value.get('aem_creds')
        for server in value.get('server'):
            server_name = server.split('//')[1].split(':')[0].replace('.','-')
            logging.info('%sChecking server status: %s', COLOR_GREEN, server)
            if operation == 'generate-csv':
                list_file_path = f"{workspace}/manifest/server-manifest-{server_name}.json"
                os.makedirs(f'{workspace}/manifest', exist_ok=True)
                check_status_cmd = f"curl -k -H 'X-Requested-With: XMLHttpRequest' -u '{aem_creds}' {server}/crx/packmgr/list.jsp"
            else:
                check_status_cmd = f"curl -k --connect-timeout 10 --max-time 30 -s -o /dev/null -w '%{{http_code}}' {server}/system/console/bundles"
            response, err = curl_with_retry(check_status_cmd, 3)
            if response:
                logging.info('%sSuccess', COLOR_GREEN)
                if operation == 'generate-csv':
                    server_manifest = json.loads(response)
                    with open(list_file_path, 'w+', encoding='utf-8') as f:
                        f.write(json.dumps(server_manifest))
                    logging.info('%sArchiving information for server %s', COLOR_GREEN, server)
            else:
                error_msg = f'{COLOR_RED}Error in checking server {server} status: {err}'
                if len(value.get('server')) > 1:
                    logging.error(error_msg)
                    vault_env_details[key]['server'].remove(server)
                else:
                    raise RuntimeError(error_msg)
    return vault_env_details


def get_package_details(vault_env_details):
    """create map of packages with same artifact name as deploy artifact"""
    package_map = {}
    for v in vault_env_details.values():
        for server in v.get('server'):
            server_name = server.split('//')[1].split(':')[0].replace('.','-')
            list_file_path = f"{workspace}/manifest/server-manifest-{server_name}.json"
            package_map[server_name] = {}
            with open(list_file_path, 'r+', encoding='utf-8') as f:
                server_manifest = json.load(f)
            with open(f"{os.getenv('CONSTANTS_PATH')}/aem_package_list.yml", 'r') as f:
                aem_package_list = yaml.load(f, Loader=yaml.BaseLoader)
            f.close()
            package_list = aem_package_list["aem_packages"]
            
            for package in package_list:
                primary_artifact = package if operation == 'generate-csv' else primary_artifact
                package_map[server_name][package] = []
            package_map['deploy_artifacts'] = package_list
            for result in server_manifest.get('results'):
                package_name = result['name']
                if package_name in package_list:
                    package_map[server_name][package_name].append(
                        {'name':package_name,'path':result['path'], 'version':result['version']})
    return package_map


def generate_csv_output(env_manifest_map):
    env = os.getenv('DEPLOY_ENV')
    file_name = f"output_{str(env)}.csv"
    current_dir = Path.cwd()
    csv_results_folder = current_dir / 'csv-results'
    csv_results_folder.mkdir(parents=True, exist_ok=True)
    csv_file_path = csv_results_folder / file_name
    with open(f"{os.getenv('CONSTANTS_PATH')}/aem_package_list.yml", 'r') as f:
        aem_package_list = yaml.load(f, Loader=yaml.BaseLoader)
    f.close()
    with open(csv_file_path, "w", newline="") as csvfile:
        writer = csv.writer(csvfile)
        writer.writerow(["Package Name", env, "Path"])
        for package_name in aem_package_list.get("aem_packages", []):
            last_package_file = None
            for packages in env_manifest_map.values():
                if not isinstance(packages, dict):
                    continue
                package_info = packages.get(package_name)
                if isinstance(package_info, list) and package_info:
                    # Get the last package dict with required keys
                    for pkg in reversed(package_info):
                        if isinstance(pkg, dict) and "path" in pkg:
                            last_package_file = pkg["path"].split("/")[-1]
                            last_package_path = pkg["path"]
                            break
            if last_package_file:
                writer.writerow([package_name, last_package_file, last_package_path])


def curl_with_retry(cmd, iterations):
    """subprocess to execute API call"""
    interval = 5 # seconds between attempts
    err = 'Unknown error'
    i = 0
    while i < iterations:
        try:
            check_status = subprocess.run(cmd, shell=True, capture_output=True, timeout=60, check=False)
            if check_status.returncode == 0:
                return [check_status.stdout.decode(), None]
            err = check_status.stderr.decode().strip().split('\n')[-1]
            logging.info('%sError: %s', COLOR_RED, err)
            i += 1
        except (json.JSONDecodeError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
            if isinstance(e, subprocess.TimeoutExpired):
                err = 'Timed out waiting for server.'
            else:
                err = 'Command return non-zero exit code.'
            time.sleep(interval)
            i += 1
            logging.info('%sAttempt %s. Error checking server: %s', COLOR_RED, i, err)
    raise RuntimeError(err)
