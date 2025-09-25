import os
import json
import re
import yaml
import copy
from artifactory import ArtifactoryPath, ArtifactoryException
from requests.auth import HTTPBasicAuth
from requests.exceptions import ConnectionError
from kpghalogger import KpghaLogger
logger = KpghaLogger()


workspace = os.getenv('GITHUB_WORKSPACE')
artifactory_user = os.getenv('ARTIFACTORY_USERNAME')
artifactory_pass = os.getenv('ARTIFACTORY_PASSWORD')
artifactory_token = os.getenv('ARTIFACTORY_TOKEN')
artifact_version_env = os.getenv('ARTIFACT_VERSION_ENV')
sonar_props = os.getenv('SONAR_PROPS')
log_level = os.getenv('LOG_LEVEL') if os.getenv('LOG_LEVEL') else '20'
download_path = os.getenv('DOWNLOAD_PATH')
COLOR_RED = "\u001b[31m"




def create_build_props(build_var_map, artifact_url):
    """
    Used to create build props according to build type.

    Args:
        build_var_map (dict): A dictionary containing build variables.
        artifact_url (str): The URL of the artifact.

    Returns:
        None
    """
    try:
        build_type = build_var_map.get('app_props').get('build_type')
        if not artifact_url:
            logger.info("Artifact not found.")
            raise RuntimeError(f"{COLOR_RED}Artifact not found. Check pom.xml/package.json configurations that all artifact-id names are the same and all lowercase")
        build_num = ''
        if build_type == 'mvn':
            build_num = artifact_url.split('-')[-1]
            build_num = f"-{build_num.split('.')[0]}" if len(build_num.split('.')) == 2 else ''

        build_var_map.get('build_props')['ARTIFACTORY_REPO'] = artifact_url
        if sonar_props != '' and sonar_props is not None:
            try:
                build_var_map.get('build_props')['SONAR_QUALITY_GATE'] = sonar_props
                build_var_map.get('build_props')['SONAR_QUALITY_GATE_NAME'] = yaml.safe_load(os.getenv('SONARQUBE_QUALITY_GATE'))
                build_var_map.get('build_props')['SONAR_PROJECT_KEY'] = f"{os.getenv('PROJECT_GIT_ORG')}:{os.getenv('PROJECT_GIT_REPO')}"
                build_var_map.get('build_props')['SONAR_VERSION'] = f"{build_var_map.get('build_props').get('APP_VERSION')}{build_num}"
                build_var_map.get('build_props')['ARTIFACT_VERSION'] = f"{build_var_map.get('build_props').get('APP_VERSION')}{build_num}"
            except RuntimeError as e:
                logger.error(f"[Error] Error tagging Sonar props {sonar_props}: {e}")
                raise RuntimeError(f"{COLOR_RED}[Error] Error tagging Sonar props {sonar_props}: {e}")
        nexus_id = os.getenv('NEXUS_ID')
        checkmarx_id = os.getenv('CHECKMARX_ID')
        if build_var_map.get('cd_deploy') and nexus_id and checkmarx_id:
            build_var_map['build_props']['NEXUS_ID'] = nexus_id
            build_var_map['build_props']['CHECKMARX_ID'] = checkmarx_id
        tag_build_props(build_var_map.get('build_props'), artifact_url)
    except RuntimeError as e:
        raise RuntimeError(f"{COLOR_RED}Error tagging build props: {e}")


def tag_build_props(build_props, artifact_url):
    """
    Tags all properties in Artifactory.

    Args:
        build_props (dict): A dictionary containing build properties.
        artifact_url (str): The URL of the artifact.

    Returns:
        None
    """
    prev_props = get_all_props(artifact_url)
    build_props.update(prev_props)
    logger.info(f"Properties to be added to artifact: {build_props}")
    artifactory_path = get_artifactory_path(artifact_url)
    artifactory_path.properties = build_props
    os.system(f"echo 'artifact-properties={json.dumps(build_props)}' >> $GITHUB_OUTPUT")


def set_artifact_property(artifact_url):
    """
    Sets individual artifact properties.

    Args:
        artifact_url (str): The URL of the artifact.

    Returns:
        None
    """
    try:
        artifact_props = os.getenv('SET_ARTIFACT_PROPS')
        new_props = yaml.safe_load(artifact_props)
        logger.info(f"Props to be added: {new_props}")
        artifactory_path = get_artifactory_path(artifact_url)
        existing_prop_map = artifactory_path.properties
        if not existing_prop_map:
            raise RuntimeError(f'{COLOR_RED}Properties not found at path {artifact_url}.')
        logger.info(f"Existing properties are: {existing_prop_map}")
        keys = list(new_props.keys())
        for key in keys:
            logger.info(f"key : {key}")
            value = new_props[key]
             # Skip updating Artifactory if key is P1 or TARGET and value is SKIPPED
            if re.match('P1|TARGET', key) and value == "SKIPPED":
                logger.info(f"Skipping update for {key}:SKIPPED")
                continue
            elif re.match('SRE_SMOKE|SMOKE|REGRESSION|DEPLOY|P1|TARGET|CRITICAL_TEST|CONTINUOUS_DEPLOY', key):
                current_props_list = get_updated_props(value, existing_prop_map.get(key))
            elif key == "DOD_CHECK_SUMMARY":
                current_props_list = get_dod_check_updated_value(key,value,existing_prop_map)
            else:
                current_props_list = value
            existing_prop_map[key] = copy.copy(current_props_list)
        artifactory_path.properties = existing_prop_map
        logger.info(f"Tagged artifact at {artifact_url} with props {existing_prop_map}.")
        os.system(f"echo 'artifact-properties={json.dumps(existing_prop_map)}' >> $GITHUB_OUTPUT")
    except RuntimeError as e:
        raise RuntimeError(f"{COLOR_RED}Error setting artifact properties: {e}")


def get_all_props(artifact_url):
    """
    Fetches all artifact properties.

    Args:
        artifact_url (str): The URL of the artifact.

    Returns:
        dict: A dictionary containing the artifact properties.
    """
    try:
        artifactory_path = get_artifactory_path(artifact_url)
        artifact_properties = artifactory_path.properties
        logger.info(f"Artifact properties: {artifact_properties}")
        os.system(f"echo 'artifact-properties={json.dumps(artifact_properties)}' >> $GITHUB_OUTPUT")
        return artifact_properties
    except RuntimeError as e:
        logger.error(f"Error fetching artifact properties: {e}")
        raise RuntimeError(f"{COLOR_RED}Error fetching artifact properties: {e}")


def get_dod_check_updated_value(key,value,existing_prop_map):
    """
    Updates the value of the DOD_CHECK_SUMMARY property.

    Args:
        key (str): The key of the property.
        value (str): The new value to be added.
        existing_prop_map (dict): A dictionary containing the existing properties.

    Returns:
        list or str: The updated value of the property.
    """
    if existing_prop_map.get(key):
        props_array = existing_prop_map[key]
        logger.info(f'Existing DoD summary results: {props_array}')
        new_env = value.split('~')[0]
        for prop in props_array:
            prop_env = prop.split('~')[0]
            if prop_env == new_env: props_array.remove(prop)
            props_array.insert(0,value)
            logger.info(f'Adding value {value}')
            break
    else: props_array = value
    return props_array


def get_updated_props(new_prop_value, new_prop_map):
    """
    Updates the value of a property.

    Args:
        new_prop_value (str): The new value to be added.
        new_prop_map (list or None): The existing value of the property.

    Returns:
        list or str: The updated value of the property.
    """
    if new_prop_map:
        prop_value = []
        for old_prop in new_prop_map:
            if len(old_prop.split('~')) > 1 and old_prop.split('~')[0] == new_prop_value.split('~')[0]:
                logger.info(f'Property exists , so updating the value {old_prop} with the current execution {new_prop_value}')
            else:
                prop_value.append(old_prop)
        prop_value.append(new_prop_value)
        prop_list = prop_value
    else:
        prop_list = new_prop_value
    return prop_list


def set_props_output():
    """
    Sets the artifact properties output.

    Returns:
        None
    """
    legacy_props = os.getenv('LEGACY_PROPS')
    artifact_props = os.getenv('ARTIFACT_PROPS')
    artifact_properties = legacy_props or artifact_props
    os.system(f"echo 'artifact-properties={artifact_properties}' >> $GITHUB_OUTPUT")


def get_artifactory_path(artifact_url):
    """
    Gets the Artifactory path.

    Args:
        artifact_url (str): The URL of the artifact.

    Returns:
        ArtifactoryPath: An instance of the ArtifactoryPath class.
    """
    try:
        if re.match('CDO-KP-ORG|SDS', os.getenv('PROJECT_GIT_ORG')):
            logger.info('using artifactory token to access artifactory')
            artifactory_path = ArtifactoryPath(artifact_url, apikey=artifactory_token)
        else:
            logger.info('using artifactory user/password to access artifactory')
            artifactory_path = ArtifactoryPath(artifact_url, auth=(artifactory_user, artifactory_pass), auth_type=HTTPBasicAuth)
        return artifactory_path
    except (ConnectionError,ArtifactoryException) as e:
        logger.error("Artifactory server is down or unreachable.")
        raise RuntimeError(f"{COLOR_RED}Artifactory server is down or unreachable: {e}")     
    except Exception as e:
        logger.error(f'Error accessing artifactory: {e}')
