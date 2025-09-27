import os
import logging
import yaml
import subprocess
import json

workspace = os.getenv('GITHUB_WORKSPACE')
COLOR_RED = "\u001b[31m"
COLOR_GREEN = "\u001b[32m"
log_level = os.getenv('LOG_LEVEL') if os.getenv('LOG_LEVEL') else '20'
logging.basicConfig(level=int(log_level), format='%(asctime)s :: %(levelname)s :: %(message)s')

def cache_flush(aem_env):
    aem_cache_flush = yaml.safe_load(os.getenv('AEM_CACHE_FLUSH'))
    try:
        logging.info(f"[INFO] Requesting Cache flush for : {aem_env}")
        endpoint = aem_cache_flush.get('endpoint')
        api_call =f'curl -X PUT {endpoint}'

        aem_env = aem_env.replace("_","-")
        logging.info(f"[INFO] Invoking cache flush for : {aem_env}")
        api_call = f"{api_call}/{aem_env}"
        status = subprocess.run(api_call, shell=True, capture_output=True)
        status = json.loads(status.stdout.decode())
        if status["result"] == "ok":
            logging.info("[INFO] AEM Cache flush was successful.")
    except Exception as e:
        logging.info(f'{COLOR_RED} AEM Cache flush failed with error - {e}')


def security_test():
    vault_map = yaml.safe_load(os.getenv('VAULT_MAP'))
    server_list = vault_map.get('aem_author').get('server')
    logging.info(f'server list: {server_list}')
    logging.info("******************************** Executing Security Health Check ***********************")
    security_health_check_passed = True

    for server in server_list:
        logging.info(f'server: {server}')
        aem_auth_creds = vault_map.get('aem_author').get('aem_creds')
        cmd = f"curl -k -u '{aem_auth_creds}' {server}/system/console/healthcheck?tags=security"
        result = subprocess.run(cmd, capture_output=True, shell=True)
        result = result.stdout.decode()
        if ("logCRITICAL" in result) or ("logHEALTH_CHECK_ERROR" in result) or ("logERROR" in result):
            security_health_check_passed = False
        file_path = f'{workspace}/aem_security_report.html'
        with open(file_path,'w+') as f:
            f.write(result)
        os.system(f"echo 'security-report={file_path}' >> $GITHUB_OUTPUT")
    if security_health_check_passed == False:
        logging.info(f"{COLOR_RED}Security Health Check Failed")
    else:
        logging.info(f"{COLOR_GREEN}Security Health Check Passed")
