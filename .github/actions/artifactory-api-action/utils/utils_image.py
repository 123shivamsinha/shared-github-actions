import os
import yaml
import requests
from datetime import datetime
import pytz
from requests.auth import HTTPBasicAuth
from requests.exceptions import ConnectionError
from kpghalogger import KpghaLogger
logger = KpghaLogger()


artifactory_user = os.getenv('JFROG_USERNAME')
artifactory_pass = os.getenv('JFROG_PASSWORD')
aks_constants = os.getenv('AKS_CONSTANTS')
COLOR_RED = "\u001b[31m"

def get_image_url(deploy_var_map, artifact_props):
    """
    Retrieves the image URL for a given artifact.

    Args:
        deploy_var_map (dict): A dictionary containing deployment variables.
        artifact_props (dict): A dictionary containing properties of the artifact.

    Returns:
        None

    Raises:
        RuntimeError: If the artifact is not found in Artifactory or if the artifact does not have build properties.
        RuntimeError: If there is an error getting the image URL.

    """
    try:
        if not artifact_props or not artifact_props.get('APP_VERSION'):
            raise RuntimeError(f'{COLOR_RED}Artifact not found in Artifactory or artifact does not have build properties.')
        aks_constant_map = yaml.safe_load(aks_constants)
        artifactory_image_base_repo = aks_constant_map.get('registry-url').strip()
        build_date = artifact_props.get('BUILD_DATE')
        build_time = pytz.timezone('US/Pacific').localize(datetime.strptime(build_date[0], '%Y%d%m%H%M%S'))
        build_timestamp = build_time.strftime("%Y-%m-%d %H:%M:%S")
        release_date_str = '2024-06-10 14:11:41'
        if release_date_str > build_timestamp:
            artifact_version = artifact_props.get('APP_VERSION')[0]
        else:
            artifact_version = artifact_props.get('APP_VERSION')[0].replace('-snapshot','').replace('-release','')
        artifact_ssha = artifact_props.get('GIT_COMMIT_SSHA')[0]
        artifact_name = f"{artifact_version}.{artifact_ssha}"
        logger.info(f"Artifact name is: {artifact_name}")
        app_name = deploy_var_map.get('app_props').get('app_name')
        image_dir = deploy_var_map.get('app_props').get('image_dir')
        request_auth = HTTPBasicAuth(artifactory_user, artifactory_pass)
        image_repo = deploy_var_map.get('image').get('image_registry')
        request_url = f'https://{artifactory_image_base_repo}/artifactory/api/storage/{image_repo}/{image_dir}/{app_name}/{artifact_name.lower()}'
        response = requests.request("GET", request_url, auth=request_auth)
        image_props = yaml.safe_load(response.text)
        logger.debug(f"response text is: {image_props}")
        if image_props.get('errors'):
            if image_props.get('errors')[0].get('status') == 404:
                logger.error(f'Artifact {artifact_name.lower()} not found in {image_repo}/{image_dir}/{app_name} in {artifactory_image_base_repo}.')
                raise RuntimeError(f'{COLOR_RED}Artifact {artifact_name.lower()} not found in {image_repo}/{image_dir}/{app_name} in {artifactory_image_base_repo}.')
            else:
                logger.error(f"Error verifying artifact {artifact_name.lower()} in {image_repo}/{image_dir}/{app_name} in {artifactory_image_base_repo}: {image_props.get('errors')[0].get('message')}.")
                raise RuntimeError(f"{COLOR_RED}Error verifying artifact {artifact_name.lower()} in {image_repo}/{image_dir}/{app_name} in {artifactory_image_base_repo}: {image_props.get('errors')[0].get('message')}.")
        artifact_image_repo = image_props.get('repo')
        artifact_image_path = image_props.get('path')    
        full_artifact_path = f'{artifact_image_repo}{artifact_image_path}'
        logger.info(f'Artifact path is: {full_artifact_path}')
        os.system(f"echo 'image-path={full_artifact_path}' >> $GITHUB_OUTPUT")    
    except RuntimeError as e:
        raise RuntimeError(f'{COLOR_RED}Error getting image URL: {e}.')
        
