"""aem api utils"""
import os
import re
import time
import asyncio
import subprocess
import json
import yaml
from kpghalogger import KpghaLogger

logger = KpghaLogger()
workspace = os.getenv('GITHUB_WORKSPACE')


def install_package(aem_creds, upload_path, server):
    """api install package"""
    try:
        logger.info(f'Installing package on {server} at path {upload_path}')
        package_path = upload_path.replace(' ','%20')
        install_cmd = f"""curl -k -X POST -u '{aem_creds}' {server}/crx/packmgr/service/.json{package_path}?cmd=install"""
        installed_package, err = asyncio.run(curl_with_retry(install_cmd, 7))
        if installed_package:
            logger.info(f'Package installed successfully: {installed_package}\n')
        else:
            raise RuntimeError(f'AEM install package failed: {err}')
    except RuntimeError as e:
        raise RuntimeError(e) from None


def upload_package(aem_creds, path_to_package, server):
    """api upload package"""
    try:
        logger.info(f'Uploading package to {server} directory {path_to_package}')
        upload_cmd = f"""curl -k -u '{aem_creds}' -F force=true -F package=@'{workspace}/{path_to_package}' {server}/crx/packmgr/service/.json/?cmd=upload"""
        uploaded_package, err = asyncio.run(curl_with_retry(upload_cmd, 7))
        if uploaded_package:
            upload_path = uploaded_package.get('path')
            logger.info(f'Package uploaded successfully: {uploaded_package}\n')
            return upload_path
        else:
            raise RuntimeError(f'Error uploading package to {server}: {err}')
    except RuntimeError as e:
        raise RuntimeError(e) from None


def delete_package(package, aem_creds, server):
    """api delete package"""
    try:
        logger.info(f'Deleting existing package at {package} on {server}')
        package_path = package.replace(' ','%20')
        delete_cmd = f"""curl -k -X POST -u '{aem_creds}' {server}/crx/packmgr/service/.json{package_path}?cmd=delete"""
        deleted_package, err = asyncio.run(curl_with_retry(delete_cmd, 7))
        if deleted_package:
            logger.info(f'Package deleted successfully: {deleted_package}\n')
        else:
            logger.error(f'AEM delete command failed: {err}')
    except RuntimeError as e:
        raise RuntimeError(e) from None 


def confirm_package(aem_creds, server):
    """api confirm package"""
    try:
        logger.info(f'Confirming installation for package on {server}.')
        install_cmd = f"""curl -k -H 'X-Requested-With: XMLHttpRequest' -u '{aem_creds}' {server}/system/console/bundles.json"""
        installed_package, err = asyncio.run(curl_with_retry(install_cmd, 3, True))
        if installed_package:
            return installed_package
        else:
            logger.error(f'Fetching bundles failed: {err}')
    except RuntimeError as e:
        raise RuntimeError(e) from None


def confirm_status(aem_creds, server, product_core_name):
    """check package state"""
    fail_on_status = True
    product_in_manifest = False
    interval = 60 if str(product_core_name).startswith('RX Order Management') else 15
    i = 0
    while i < 10 and fail_on_status:
        server_bundles = confirm_package(aem_creds, server)
        for x in server_bundles.get('data'):
            if x.get('name').casefold() == product_core_name.casefold():
                product_in_manifest = True
                install_state = x.get('state')
                logger.info(
                    f'Found package {product_core_name}'
                    f' on server {server}: {install_state}'
                )
                if install_state == 'Active':
                    return False
                i += 1
                logger.info(f'Waiting {interval} seconds to check status of {product_core_name}...')
                time.sleep(interval)
        if not product_in_manifest:
            return False
    return fail_on_status


async def curl_with_retry(cmd, iterations, skip_check=False):
    """redundant calls to api"""
    interval = 5 # seconds between attempts
    i = 0
    err = None
    while i < iterations:
        try:
            check_status = subprocess.run(cmd, shell=True, capture_output=True, check=True, timeout=360)
            if check_status.stdout:
                status_map = json.loads(check_status.stdout.decode())
                status_true = isinstance(status_map, dict) and status_map.get('success') is True
                if status_true or skip_check:
                    return [status_map, None]
                else:
                    err = check_status.stdout.decode()
            else:
                err = check_status.stderr.decode()
            i += 1
        except (json.JSONDecodeError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
            if isinstance(e, subprocess.TimeoutExpired):
                err = 'Timed out waiting for server.'
            else:
                err = 'Command return non-zero exit code.'
            await asyncio.sleep(interval)
            i += 1
            logger.error(f'Attempt {i}: {err}')
    return [None, err]


def check_wait_time(deployment_data_map, vault_map, deployment_data, rollback_available):
    """check install status on target server - if status is not 'active' with threshold, fail deployment"""
    fail_on_status = False
    product_name = deployment_data_map['name']
    product_core_name = deployment_data_map['quality'].get('core_name')
    if need_sleep_before_cache_flush(product_name):
        logger.info('Sleeping for 5 minutes...')
        time.sleep(300) # wait 5 minutes
    elif re.search('-config$|-configs$', product_name):
        logger.info(f'Waiting 3 minutes after deploying {product_name}...')
        time.sleep(180)
    for value in vault_map.values():
        aem_creds = value.get('aem_creds')
        if product_core_name:
            for server in value.get('server'):
                fail_on_status = confirm_status(aem_creds, server, product_core_name)
        if fail_on_status:
            logger.error(f'Install failed - artifact not in active status.')
            deployment_data['deploy_status'] = 'FAILED'
            deployment_data['rollback'] = rollback_available
            break
    return deployment_data


def need_sleep_before_cache_flush(product_name):
    """sleep before cache flush"""
    repo_matched = False
    repos_needing_sleep = yaml.safe_load(os.getenv('REPOS_NEEDING_SLEEP_BEFORE_CACHE_FLUSH'))
    for each_repo in repos_needing_sleep:
        if each_repo == product_name:
            repo_matched = True
            break
    return repo_matched


def run_confirm_status(deploy_package):
    """
    Runs the confirm-status operation.
    - If PROJECT_CORE_NAME cannot be determined, logs a warning and exits successfully.
    - Otherwise, checks that the package is active on all target servers and fails if any are not.
    """
    vault_map = yaml.safe_load(os.getenv('VAULT_MAP', '{}')) or {}
    product_core_name = deploy_package.get('build_props', {}).get('PROJECT_CORE_NAME')
    
    if not product_core_name:
        logger.warning("PROJECT_CORE_NAME could not be determined; skipping confirm-status checks.")
        exit(0)
    
    failed = False
    for entry in vault_map.values():
        aem_creds = entry.get('aem_creds')
        for server in entry.get('server', []):
            if confirm_status(aem_creds, server, product_core_name):
                logger.error(f"Package {product_core_name} is not active on server {server}.")
                failed = True
            else:
                logger.info(f"Package {product_core_name} is active on server {server}.")
    
    if failed:
        logger.error("One or more servers reported inactive package; exiting with failure.")
        exit(1)
    else:
        logger.info("All servers report package active; exiting successfully.")
        exit(0)
