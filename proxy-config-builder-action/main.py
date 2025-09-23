import os , re
import json , yaml
from proxy_config_builder import create_proxy_config_files
from github import Github
from kpghalogger import KpghaLogger
logger = KpghaLogger()


COLOR_RED = "\u001b[31m"
org_name = os.getenv('PROJECT_GIT_ORG').upper()
repo_name = os.getenv('PROJECT_GIT_REPO')
repo_path = f"{org_name}/{repo_name}"
branch_name = os.getenv('GITHUB_REF_NAME')
workspace = os.getenv('GITHUB_WORKSPACE')
workflow_url = os.getenv('BUILD_URL')


def main():
    config_json_file_name = os.getenv('CONFIG_JSON_FILE_NAME')
    provider_config_mgmt = yaml.safe_load(os.getenv('PROVIDER_CONFIG_MGMT'))
    config_mgmt = yaml.safe_load(os.getenv('CONFIG_MGMT'))
    rtlbl_flag = False
    auto_gen = False
    files_dir = "definitions"
    if os.path.isdir(f"{workspace}/definitions") == True:
        logger.info("Found definition folder")
        if len([name for name in os.listdir(f"{workspace}/definitions") if os.path.isfile(os.path.join(f"{workspace}/definitions", name)) and re.search("^proxyConfig.*\.json$", name) ]) == 0 :
            logger.info(f"No proxyConfig*.json file found in definitions folder - starting proxy config builder automation")
            files_dir = provider_config_mgmt.get('file-gen-path')

            auto_gen_folder_exists = ""
            proxy_config_template_file_path = f"{os.getenv('CONSTANTS_PATH')}/resources/{config_mgmt.get('proxy-config-template-file-path')}"
            source_mapping_agent_file_path = f"{os.getenv('CONSTANTS_PATH')}/resources/{config_mgmt.get('source-mapping-agent-file-path')}"
            env_stack_file_path = f"{os.getenv('CONSTANTS_PATH')}/resources/{config_mgmt.get('env-stack-file-path')}"
            endpoint_type_file_path = f"{os.getenv('CONSTANTS_PATH')}/resources/{config_mgmt.get('endpoint-type-file-path')}"
            swagger_file_path = f"{workspace}/{provider_config_mgmt.get('swagger-file-path')}"
            routlbl_file_path = f"{workspace}/{provider_config_mgmt.get('routlbl-file-path')}"

            files_dir_path=f"{workspace}/{files_dir}/"
            os.system(f"ls -ltr")
            proxy_list = create_proxy_config_files(proxy_config_template_file_path, source_mapping_agent_file_path , files_dir_path , swagger_file_path , env_stack_file_path , routlbl_file_path , endpoint_type_file_path)
            os.system(f"ls -ltr {workspace}/{files_dir}")
            logger.info(f"proxy list: {proxy_list}")
            try:
                if proxy_list:
                    repo = repo_object()
                    push_to_scm(repo, proxy_list)
                else:
                    logger.info(f"[INFO]: No changes in proxy config file. File will not be pushed to autoGenProxyConfig folder")
            except Exception as e:
                logger.error(f"Error while pushing proxy config file back to Git repository : {e.output}")
        else:
            logger.info(f"proxyConfig*.json file found in definitions folder. AutoGenProxyConfig utility will not be triggered")

    else:
        logger.info(f"[INFO]: definitions folder doesn't exist. AutoGenProxyConfig utility cannot be triggered.")


def repo_object():
    try:
        auth_token = os.getenv('APP_TOKEN') or os.getenv('GHA_SVC_ACCOUNT')
        api_url = os.getenv('GITHUB_API_URL')
        github = Github(base_url=api_url, login_or_token=auth_token)
        repo = github.get_repo(repo_path)
    except Exception as e:
        raise ValueError(f'{COLOR_RED}Error creating repo object: {e}')
    return repo


def push_to_scm(repo, proxy_list):
    for proxy_type in proxy_list:
        proxy_config_file_name = f"proxyConfig-{proxy_type}.json"
        try:
            file_content = repo.get_contents(f"autoGenProxyConfig/{proxy_config_file_name}", ref=branch_name)
        except Exception:
            file_content = None

        with open(f'{workspace}/autoGenProxyConfig/{proxy_config_file_name}', 'r+') as a:
            proxy_config_file_content = yaml.safe_load(a)
        a.close()

        # Create proxy config file if it doesn't exist or update existing proxy config file
        if file_content == None or proxy_config_file_content != yaml.safe_load(file_content.decoded_content):
            logger.info(f"Proxy config file content generated is different from existing file content or does not exist yet. Proceeding to create/update proxy config file")
            if file_content:
                repo.update_file(f"autoGenProxyConfig/{proxy_config_file_name}", f'{proxy_config_file_name} updated: {workflow_url}', json.dumps(proxy_config_file_content, indent=4, sort_keys=False), sha=file_content.sha, branch=branch_name)
                logger.info(f"{proxy_config_file_name} updated in autoGenProxyConfig folder")
            else:
                repo.create_file(f"autoGenProxyConfig/{proxy_config_file_name}", f'{proxy_config_file_name } created: {workflow_url}', json.dumps(proxy_config_file_content, indent=4, sort_keys=False), branch=branch_name)
                logger.info(f"{proxy_config_file_name} created in autoGenProxyConfig folder")
        else:
            logger.info(f"[INFO]: No changes in {proxy_config_file_name}. File will not be pushed to autoGenProxyConfig folder")


if __name__ == "__main__":
    logger.info(logger.format_msg('GHA_EVENT_ACTION_AUD_2_9000', 'action entry/exit point', {"detailMessage": "action metric", "metrics": {"state": "start"}}))
    main()
    logger.info(logger.format_msg('GHA_EVENT_ACTION_AUD_2_9000', 'action entry/exit point', {"detailMessage": "action metric", "metrics": {"state": "end"}}))