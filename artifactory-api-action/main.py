import os
import sys
import yaml
import json
import re
import utils.utils_artifactory as utils
import utils.utils_image as image
import utils.utils_props as props
import subprocess
from kpghalogger import KpghaLogger
logger = KpghaLogger()

workspace = os.getenv('GITHUB_WORKSPACE')
download_url = os.getenv('DOWNLOAD_URL')
config_artifact_url = os.getenv('CONFIG_ARTIFACT_URL')
org_name = os.getenv('PROJECT_GIT_ORG').upper()
repo_name = os.getenv('PROJECT_GIT_REPO')
COLOR_RED = "\u001b[31m"


def main():
    """
    Main function that serves as the entry point of the script.
    It determines the operation to perform based on the value of the 'OPERATION' environment variable.
    """
    try:
        operation = os.getenv('OPERATION')
        build_var_map = yaml.safe_load(sys.argv[1].replace('\\n','')) if sys.argv[1] else None
        context = os.getenv('CONTEXT') if os.getenv('CONTEXT') else None
        logger.info(logger.format_msg('GHA_TOOL_ARTIFACTORY_BIZ_2_0001', 'Loading build var map and determining function', f"Using operation {operation} and context {context} to determine function"))
        logger.info(f"Operation to be perfom: {operation}")
        logger.info(f"Context is: {context}")
        logger.info(f"Organization Name: {org_name}")
        if operation == 'check-version':
            check_artifactory_version(build_var_map)
        elif operation == 'manifest':
            check_manifest_artifacts(build_var_map, operation)
        elif operation == 'upload-artifact':
            utils.upload_artifact(build_var_map)
        elif operation == 'download-artifact':            
            download_artifactory_artifact(build_var_map, context)
        elif operation == 'set-props-output':
            props.set_props_output()
        else:
            artifact_url = utils.find_latest_version(build_var_map, context)
            if operation == 'tag-build-props':
                props.create_build_props(build_var_map, artifact_url)
                if artifact_url:
                   subprocess.run([f"""echo "#### :shield: [Latest artifact URL]({artifact_url})" >> $GITHUB_STEP_SUMMARY"""], shell=True)
            elif operation == 'get-all-props':
                if artifact_url == None and not build_var_map.get('cd_deploy'):
                    raise RuntimeError(f'Artifact not found in Artifactory.')
                elif artifact_url:
                    props.get_all_props(artifact_url)
            elif operation == 'set-props':
                if os.getenv('SET_ARTIFACT_PROPS'):
                    props.set_artifact_property(artifact_url)
                else:
                    logger.error(logger.format_msg('GHA_TOOL_ARTIFACTORY_BIZ_4_2001', 'No properties found for tagging', "No properties found to tag in the artifact"))
            elif operation == 'get-image-url' and not re.search("apigee-hybrid-fotf-test|mykp-rules-personalization-apigee", repo_name): # apigee hybrid test repos does not have a docker image
                artifact_props = props.get_all_props(artifact_url)
                image.get_image_url(build_var_map, artifact_props)
    except RuntimeError as e:
        raise RuntimeError(f'{COLOR_RED}Error in Artifactory Action: {e}') from None


def check_artifactory_version(build_var_map):
    """
    Called before build to determine whether the artifact exists in Artifactory.
    It checks if the artifact version is a snapshot or a release version.
    If it's a snapshot version, it returns without performing any checks.
    If it's a release version, it checks if the version already exists in Artifactory.
    If the version already exists, it raises a RuntimeError.
    """
    module_values_project = build_var_map.get('module_values_project')
    artifact_id = module_values_project.get('artifact_id')
    artifact_version = module_values_project.get('artifact_version')
    if 'snapshot' in artifact_version.lower():
        logger.info("Check version: version is a snapshot" )
        return # snapshot versions can have multiple artifacts
    else:
        logger.info(f"Checking if version {artifact_version} of {artifact_id} exists in Artifactory.")
        if utils.find_latest_version(build_var_map, 'build'):
            logger.error(logger.format_msg('GHA_TOOL_ARTIFACTORY_BIZ_4_2002', 'This version already exists on Artifactory', "In order to do another build, please bump up the current version in the app files of the project and its modules as applicable."))
            error_message = f'{COLOR_RED}This version already exists on Artifactory. In order to do another build, you will have to bump up the version of the project in the POM or package files of the project and its modules.'
            raise RuntimeError(error_message)
        else: logger.info(f'Version does not exist in Artifactory - proceeding with build.')


def download_artifactory_artifact(build_var_map, context):
    """
    Downloads the artifact from Artifactory based on the provided build_var_map and context.
    If a download URL is provided, it directly downloads the artifact from the URL.
    If the context is 'download-image', it finds the latest version of the artifact and downloads it.
    If the context is 'aem', it supports multi-component deployments and downloads the artifacts for each component.
    For any other context, it finds the latest version of the artifact and downloads it.
    """
    try:
        if download_url and download_url is not None:
            utils.download_artifact(download_url)
        else:
            if context == 'download-image':
                latest_version = utils.find_latest_version(build_var_map)
                artifact_props = props.get_all_props(latest_version)
                download_artifact_url = image.get_image_url(build_var_map, artifact_props)
                utils.download_artifact(download_artifact_url, context)
            elif context == 'aem': # supports multi-component deployments
                download_paths = {}
                aem_artifacts = {}
                deploy_module = build_var_map.get('module_values_deploy') or build_var_map
                artifact_version = deploy_module.get('artifact_version')
                aem_artifacts[deploy_module.get('artifact_id')] = artifact_version
                if deploy_module.get('secondary_ids'):
                    logger.info(f"Secondary IDs found: {deploy_module.get('secondary_ids')}")
                    for secondary_id in deploy_module.get('secondary_ids'):
                        secondary_id_name = secondary_id.split(':')[0]
                        secondary_id_version = secondary_id.split(':')[1] if ':' in secondary_id else artifact_version
                        aem_artifacts[secondary_id_name] = secondary_id_version
                else:
                    logger.info("No secondary IDs found in the deployment module.")
                for id, version in aem_artifacts.items():
                    download_artifact_url = utils.find_latest_version(build_var_map, context, id, version)
                    download_path = utils.download_artifact(download_artifact_url, context)
                    download_paths[id] = download_path
                os.system(f"echo 'download-artifact={json.dumps(download_paths)}' >> $GITHUB_OUTPUT")
            else:
                if context == 'test':
                    deploy_module = build_var_map.get('module_values_test', {})
                else:
                    deploy_module = build_var_map.get('module_values_deploy', {})
                artifact_id = deploy_module.get('artifact_id', '<unknown>')
                artifact_version = deploy_module.get('artifact_version', '<unknown>')
                ticket = build_var_map.get('input_map', {}).get('deployment-ticket', '<none>')
                try:
                    download_artifact_url = utils.find_latest_version(build_var_map, context)
                    utils.download_artifact(download_artifact_url, context)
                except RuntimeError as e:
                    error_message = (
                        f"{COLOR_RED}[Ticket {ticket}] Artifact '{artifact_id}-{artifact_version}' not found in Artifactory "
                        f"(context: {context}). Please verify the artifact_id and artifact_version."
                    )
                    logger.error(error_message)
                    raise RuntimeError(error_message) from None
    except RuntimeError as e:
        raise RuntimeError(f'{COLOR_RED}Error downloading artifact: {e}') from None


def check_manifest_artifacts(build_var_map, operation):
    """
    Validates that the artifacts specified in the manifest exist in Artifactory.
    Iterates through `build_var_map` to check each artifact's latest version based on the specified operation.
    Raises a RuntimeError if any artifact is missing.
    """
    try:
        latest_version_deploy = ''

        # Iterate through build_var_map to validate artifacts
        for key, value in build_var_map.items():
            artifact_id = value.get('artifact_id')
            artifact_version = value.get('artifact_version')
            logger.info(f"Checking artifact: {artifact_id} (version: {artifact_version})")

            # Skip checks for entries with missing artifact details
            if not artifact_id or not artifact_version:
                logger.warning(f"Missing artifact details for {key}. Skipping...")
                continue

            latest_version = None

            # Determine the artifact operation (deploy, rollback, config)
            if key == 'module_values_deploy':
                latest_version = utils.find_latest_version(build_var_map, 'deploy')
                if latest_version:
                    latest_version_deploy = latest_version
                    artifact_props = props.get_all_props(latest_version_deploy)
            elif key != 'app_props':
                latest_version = utils.find_latest_version(value, operation)

            # Handle missing artifacts
            if not latest_version:
                error_message = (
                    f"(x) *ERROR:* No valid artifact '{artifact_id}-{artifact_version}' found in Artifactory. "
                    "The artifact is missing required properties: `REPO_NAME` or `repoName`."
                )

                # Prepare Jira comment for GitHub Actions
                jira_comment = {
                    'message': error_message,
                    'action': 'comment_transition_exit',
                    'details': {
                        'artifact_id': artifact_id,
                        'artifact_version': artifact_version
                    }
                }

                # Output Jira comment to GitHub Actions
                os.system(f"echo 'jira-comment={json.dumps(jira_comment)}' >> $GITHUB_OUTPUT")
                break  # Stop processing on error

        # Output the latest deploy artifact version to GitHub Actions
        if latest_version_deploy:
            os.system(f"echo 'artifact-url={latest_version_deploy}' >> $GITHUB_OUTPUT")
        else:
            logger.warning(f"No deploy artifact found.")

    except RuntimeError as error:
        logger.error(f"RuntimeError encountered: {error}")
        raise RuntimeError(f"{COLOR_RED}Error while checking manifest artifacts: {error}") from error


if __name__ == "__main__":
    logger.info(logger.format_msg('GHA_EVENT_ACTION_AUD_2_9000', 'action entry/exit point', {"detailMessage": "action metric", "metrics": {"state": "start"}}))
    main()
    logger.info(logger.format_msg('GHA_EVENT_ACTION_AUD_2_9000', 'action entry/exit point', {"detailMessage": "action metric", "metrics": {"state": "end"}}))