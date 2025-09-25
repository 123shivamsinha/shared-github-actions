import os
import subprocess
import re
import pytz
import time
import glob
import yaml
from artifactory import ArtifactoryPath, ArtifactoryException
from requests.auth import HTTPBasicAuth
from datetime import datetime
from requests.exceptions import ConnectionError, RequestException
from kpghalogger import KpghaLogger
logger = KpghaLogger()

workspace = os.getenv('GITHUB_WORKSPACE')
artifactory_user = os.getenv('ARTIFACTORY_USERNAME')
artifactory_pass = os.getenv('ARTIFACTORY_PASSWORD')
artifactory_url = os.getenv('ARTIFACTORY_URL')
artifact_version_env = os.getenv('ARTIFACT_VERSION_ENV')
download_path = os.getenv('DOWNLOAD_PATH', '') 
org_name = os.getenv('PROJECT_GIT_ORG').upper()
gha_org = os.getenv('GHA_ORG')
COLOR_RED = "\u001b[31m"

def find_latest_version(build_var_map, context=None, artifact_id=None, artifact_version=None):
    """
    Determine properties of deployable module and find the latest artifact version.

    Args:
        build_var_map (dict): A dictionary containing build variables.
        context (str, optional): The context of the deployment. Defaults to None.
        artifact_id (str, optional): The ID of the artifact. Defaults to None.

    Returns:
        str: The URL of the latest artifact version.
        list: A list of artifact URLs with missing properties

    Raises:
        RuntimeError: If there is an error finding the latest Artifactory version.
    """
    try:
        app_extension = None
        if context == 'test':
            deploy_module = 'module_values_test'
        elif context == 'test-config':
            deploy_module = 'module_values_test_config'
        elif context and re.match('project|build|apigee', context):
            deploy_module = 'module_values_project'
        elif context == 'config':
            deploy_module = 'module_values_config'
        else:
            deploy_module = 'module_values_deploy'
        if gha_org == 'ENTERPRISE': 
            input_map, application_name = get_input_map() 
            logger.info(f"Application name Selected: {application_name}")   
            if application_name:
                artifact_id = application_name 
            else:
                artifact_id = (build_var_map.get(deploy_module, {}).get('artifact_id') or build_var_map.get('artifact_id'))
                module_name = ( build_var_map.get('app_props', {}).get('module_name') or build_var_map.get('build_group', {}).get('module-name'))
                if module_name:
                    if module_name == artifact_id:
                        logger.info(f"Matches the module name '{module_name}' and artifact id '{artifact_id}' values")
                    elif module_name.lower() == artifact_id:
                        logger.info(f"Mismatch in case for module name '{module_name}' and artifact id '{artifact_id}'")
                    else:
                        logger.info(f"Mismatch in values: module name = '{module_name}', artifact id = '{artifact_id}'")
        else:
            artifact_id = artifact_id or (build_var_map.get(deploy_module, {}).get('artifact_id') or build_var_map.get('artifact_id'))
        artifact_version = artifact_version or build_var_map.get(deploy_module,{}).get('artifact_version') or build_var_map.get('artifact_version') or build_var_map.get('app_props').get('artifact_version')
        app_extension = get_app_extension(build_var_map, context)
        if artifact_version_env:
            artifact_version = artifact_version_env.lower()
        artifact_url = get_url_by_app_type(artifact_id, artifact_version, app_extension, context)
        if artifact_url:
            os.system(f"echo 'artifact-url={artifact_url}' >> $GITHUB_OUTPUT")
        logger.info(f'Latest artifact version: {artifact_url}')
        return artifact_url
    except RuntimeError as e:
        raise RuntimeError(f"{COLOR_RED}Error finding latest Artifactory version: {e}")


def get_app_extension(build_var_map, context=None):
    """
    Get the application extension based on the build variable map.

    Args:
        build_var_map (dict): A dictionary containing build variables.

    Returns:
        str: The application extension.
    """
    if context == 'aem' or build_var_map.get('app_props',{}).get('app_type') == 'aem':
        app_extension = 'zip'
    elif context == 'build':
        app_extension = None
    else:
        app_extension = build_var_map.get('app_props',{}).get('app_extension')
    return app_extension
 

def get_url_by_app_type(artifact_id, artifact_version, app_extension, context):
    """
    Query Artifactory for any deployable artifact matching the ID, version, and application extension.

    Args:
        artifact_id (str): The ID of the artifact.
        artifact_version (str): The version of the artifact.
        app_extension (str): The application extension.
        context (str): The context of the deployment.

    Returns:
        str: The URL of a valid artifact URL if found.

    Raises:
        RuntimeError: If there is an error querying Artifactory.
    """
    logger.info(f"artifact id in get url by app type:{artifact_id}")
    logger.info(f"artifact version in get url by app type:{artifact_version}")
    logger.info(f"app extension in get url by app type: {app_extension}")
    logger.info(f"context in get url by app type: {context}")
    
    # Artifactory repo
    if re.match('ENTERPRISE', gha_org) and re.match('CDTS', org_name[:4]):
        artifact_repo = f"""
        {{"repo":"npm-release"}},
        {{"repo":"npm-local"}},
        {{"repo":"libs-snapshot"}},
        {{"repo":"libs-release"}},
        {{"repo":"npm-snapshot-local"}},
        {{"repo":"local-release"}},
        {{"repo":"local-snapshot"}},
        {{"repo":"libs-snapshot-local"}},
        {{"repo":"libs-release-local"}},
        {{"repo":"deploy-zip-snapshots"}},
        {{"repo":"deploy-zip-releases"}},
        {{"repo":"npm-release-local"}},
        {{"repo":"pypi-local"}},
        {{"repo":"nuget-local-repo"}}
        """
    elif re.match('ENTERPRISE', gha_org) and re.match('ADEPT', org_name[:5]):
        artifact_repo = f"""
        {{"repo":"adept_release"}},
        {{"repo":"adept_snapshot"}}
        """    
    elif re.match('ENTERPRISE', gha_org):
         artifact_repo = f"""
         {{"repo":"npm-bluemix"}},
         {{"repo":"pypi"}},
         {{"repo":"mvn"}},
         {{"repo":"nuget"}},
         {{"repo":"golang"}},
         {{"repo":"local-release"}},
         {{"repo":"local-snapshot"}}
         """
    else:
        artifact_repo = f"""
        {{"repo":"remote-repos"}},
        {{"repo":"npm-virtual"}},
        {{"repo":"pypi-virtual"}}
        """

    # Version match
    if gha_org == 'CDO-KP-ORG':
        artifact_version = artifact_version.lower()
        version_search = re.sub(r'([a-zA-Z]{1,})(-[a-zA-Z]{1,})?','*', artifact_version)
    else: 
        if '-snapshot' in artifact_version or '-SNAPSHOT' in artifact_version:
           version_search = re.sub(r'([a-zA-Z]{1,})(-[a-zA-Z]{1,})?','*', artifact_version) 
        else:  
           artifact_version = artifact_version.upper()
           version_search = artifact_version
    
    if context == 'config' and not re.match('ENTERPRISE', gha_org):
        search_context = f"""
        {{"name":{{"$match":"{artifact_id}-{version_search}.zip"}}}}
        """
        if artifact_version.startswith('latest'): # support latest tag for KPD config artifacts
            artifact_repo = f"""
            {{"repo":"inhouse_{artifact_version.split('-')[1]}"}}
            """
    elif app_extension and not re.match('test|project|apigee', str(context)):
        search_context = f"""
        {{"name":{{"$match":"{artifact_id}-{version_search}.{app_extension}"}}}}
        """
    elif gha_org == 'CDO-KP-ORG' and re.match('test|apigee', str(context)):
        if context == 'test' and 'it.tests' in artifact_id:
            search_context = f"""
            {{"name":{{"$match":"{artifact_id}-{version_search}.zip"}}}},
            {{"name":{{"$match":"{artifact_id}-{version_search}.tgz"}}}},
            {{"name":{{"$match":"{artifact_id}-{version_search}.tar.gz"}}}}
        """
        else:
            search_context = f"""
            {{"name":{{"$match":"{artifact_id}-{version_search}.jar"}}}},
            {{"name":{{"$match":"{artifact_id}-{version_search}.zip"}}}},
            {{"name":{{"$match":"{artifact_id}-{version_search}.tgz"}}}},
            {{"name":{{"$match":"{artifact_id}-{version_search}.tar.gz"}}}}
        """
    elif 'parentpom' in artifact_id:
        search_context = f"""
        {{"name":{{"$match":"{artifact_id}-{version_search}.pom"}}}}
        """
    else:
         logger.info(f"Version search is: {version_search}")  
         search_context = f"""
         {{"name":{{"$match":"{artifact_id}-{version_search}.war"}}}},
         {{"name":{{"$match":"{artifact_id}-{version_search}.zip"}}}},
         {{"name":{{"$match":"{artifact_id}-{version_search}.jar"}}}},
         {{"name":{{"$match":"{artifact_id}-{version_search}.ear"}}}},
         {{"name":{{"$match":"{artifact_id}-{version_search}.tgz"}}}},
         {{"name":{{"$match":"{artifact_id}-{version_search}.tar.gz"}}}},
         {{"name":{{"$match":"{artifact_id}.{version_search}.nupkg"}}}}
         """
        
    
    if context == 'build' or app_extension == 'pom':
       search_context += f',{{"name":{{"$match":"{artifact_id}-{version_search}.pom"}}}}'   

    # Search query
    data_req = f"""items.find({{
        "$or":[
            {search_context}
        ],
        "$or":[
            {artifact_repo}
        ]}}).sort({{"$desc":["created"]}}).limit(3)
    """ 
    logger.info(f"Constructed search query for Artifactory: {data_req}")
    urls_for_missing_props = []

    try:
        logger.debug(f"Request to Artifactory: {data_req}")
        artifactory_path = ArtifactoryPath(artifactory_url, auth=(artifactory_user, artifactory_pass), auth_type=HTTPBasicAuth)
        response = artifactory_path.aql(data_req)
        logger.info(f"Response from Artifactory: {response}")

        artifact_url = None
        for i in response:
            artifact_repo = i.get('repo')
            artifact_path = i.get('path')
            artifact_name = i.get('name')
            artifact_url = f"{artifactory_url}/{artifact_repo}/{artifact_path}/{artifact_name}"
            logger.info(f"Found artifact at {artifact_url}")

            if context == 'deploy':
                artifactory_path = ArtifactoryPath(artifact_url, auth=(artifactory_user, artifactory_pass), auth_type=HTTPBasicAuth)
                props = artifactory_path.properties
                logger.info(f"[INFO] PROPERTIES FOR {artifact_name}: {props}")
                if props and (props.get('REPO_NAME') or props.get('repoName')):
                    logger.info(f'Found artifact URL: {artifact_url}')
                    return artifact_url 
                else:
                    logger.warning(f"Artifact found at {artifact_url}, but it is missing the required properties 'REPONAME' or 'repoName'.")
                    urls_for_missing_props.append(artifact_url)
            else:
                logger.info(f"Deployment context not applicable. Returning artifact URL: {artifact_url}.")
                return artifact_url

        if urls_for_missing_props:
            missing_urls_message = '\n'.join(urls_for_missing_props)
            error_message = (
                f"ERROR: No valid artifact '{artifact_id}-{artifact_version}' was found in Artifactory. "
                f"The artifact is missing the required properties: 'REPO_NAME' or 'repoName'.\n\n"
                f"The following artifact URLs lack the required properties:\n{missing_urls_message}\n"
            )
            logger.error(error_message)

        return None

    except (ConnectionError, ArtifactoryException) as e:
        logger.error(f"Artifactory connection error: {e}")
        raise RuntimeError(f"Artifactory server is unreachable: {e}")
    except Exception as e:
        logger.error(f"Error in get_url_by_app_type function: {e}")
        raise RuntimeError(f"Unexpected error: {e}")


def upload_artifact(build_var_map):
    """
    Upload an artifact to Artifactory.

    Args:
        build_var_map (dict): A dictionary containing build variables.

    Raises:
        RuntimeError: If there is an error uploading the artifact to Artifactory.
    """
    try:
        upload_packages = {}
        if os.getenv('GHA_ORG') == 'CDO-KP-ORG':
            artifactory_token = os.getenv('ARTIFACTORY_TOKEN')
        else:
            artifactory_user = os.getenv('ARTIFACTORY_USERNAME')
            artifactory_pass = os.getenv('ARTIFACTORY_PASSWORD')
        if os.getenv('ARTIFACT_PATH') is not None:
            artifact_name = os.getenv('ARTIFACT_PATH').split('/')[-1]
            artifactory_directory = os.getenv('ARTIFACTORY_DIR')
            upload_packages[artifact_name] = artifactory_directory
            logger.info(f'Uploading {artifact_name} to {artifactory_directory}')
        elif build_var_map.get('app_props').get('build_type') == 'pip':
            app_name = build_var_map.get('app_props').get('app_name')
            app_version = build_var_map.get('app_props').get('product_version')
            artifactory_directory = f'pypi-local/{app_name}/{app_version}/'
            artifact_loc = 'dist/*.tar.gz'
            artifact_name = app_name + '-' + app_version + '.' + build_var_map.get('app_props').get('app_extension')
            subprocess.run(f"mv {artifact_loc} {artifact_name}", shell=True)
            file_exists = os.path.exists(artifact_name)
            if file_exists == True:
                upload_packages[artifact_name] = artifactory_directory
            else:
                raise FileNotFoundError(f'{COLOR_RED}Artifact {artifact_name} not found.')
        elif build_var_map.get('app_props').get('build_type') == 'dotnet':
            app_name = build_var_map.get('app_props').get('app_name')
            module_name = (build_var_map.get('app_props', {}).get('module_name') or build_var_map.get('build_group', {}).get('module-name'))
            logger.info(f"Module Name is: {module_name}")
            if module_name:
               app_name = module_name
            app_platform = build_var_map.get('app_props').get('platform_project')
            app_version = build_var_map.get('module_values_project',{}).get('artifact_version')
            app_extension = build_var_map.get('build_group').get('app-extension') or 'zip'
            logger.info (f"App Extension is: {app_extension}")
            if org_name[:4].upper() == 'CDTS' and app_extension != 'nupkg':
                artifact_repo = 'deploy-zip-snapshots' if '-snapshot' in app_version.lower() else 'deploy-zip-releases'
            elif org_name[:4].upper() == 'CDTS' and app_extension == 'nupkg':
                artifact_repo = 'nuget-local-repo'
            else:
                artifact_repo = 'nuget-snapshot-local' if '-snapshot' in app_version.lower() else 'nuget-release-local'
            logger.info(f"Selected artifact repo: {artifact_repo}")
            
            if '-snapshot' in app_version.lower():
                timestamp = pytz.timezone('US/Pacific').localize(datetime.now()).strftime("%Y%m%d%H%M%S")
                artifact_name = f"{app_name}-{app_version}-{timestamp}.{app_extension}"
            else:
                artifact_name = f"{app_name}-{app_version}.{app_extension}"

            if app_extension == 'zip':
                zip_output_path = os.path.join("app", artifact_name)
                publish_folder = 'app/publish' 
                if not os.path.exists(publish_folder):
                    logger.error(f"Artifact path '{publish_folder}' does not exist.")
                    raise FileNotFoundError(f"Missing directory: {publish_folder}")
                logger.info(f"Zipping contents of '{publish_folder}' to '{zip_output_path}'")
                try:
                    subprocess.run(f"cd {publish_folder} && zip -r ../../{zip_output_path} .", shell=True, check=True)
                except subprocess.CalledProcessError as e:
                    logger.error(f"Failed to zip artifact contents: {e}")
                    raise
    
                if not os.path.exists(zip_output_path):
                    logger.error(f"Zipped artifact not found at expected location: {zip_output_path}")
                    raise FileNotFoundError(f"Missing zip file: {zip_output_path}")
    
                try:
                    subprocess.run(f"cp {zip_output_path} {artifact_name}", shell=True, check=True)
                    logger.info(f"Copied from '{zip_output_path}' to '{artifact_name}' (upload root)")
                except subprocess.CalledProcessError as e:
                    logger.error(f"Failed to copy artifact zip: {e}")
                    raise
            elif app_extension == 'nupkg':  
                 publish_folder = 'bin/release'
                 pack_command = f"dotnet pack {workspace}/{app_name}.csproj --configuration Release --output {workspace}/{publish_folder}/"
                 try:
                    subprocess.run(pack_command, shell=True, check=True)
                    logger.info(f"Packaged .nupkg artifact with command: {pack_command}")
                 except subprocess.CalledProcessError as e:
                    logger.error(f"Failed to pack .nupkg: {e}")
                    raise
                 artifact_name = f"{app_name}.{app_version}.nupkg"
                 logger.info(f"publish folder: {publish_folder}-{artifact_name}")
                 artifact_path = os.path.join(workspace, publish_folder, artifact_name)
                 if not os.path.exists(artifact_path):
                    logger.error(f"NuGet package not found at expected location: {artifact_path}")
                    raise FileNotFoundError(f"Missing NuGet package: {artifact_path}")        
            artifactory_directory = f"{artifact_repo}/{app_platform}/{app_name}/{app_version}/"
            upload_packages[artifact_name] = artifactory_directory
            logger.info(f"Final upload packages: {upload_packages}")
        elif build_var_map.get('app_props').get('build_type') == 'gradle':
             if build_var_map.get('app_props').get('artifact_type') == 'NODEJS':
                app_name = build_var_map.get('app_props').get('app_name')
                app_version = build_var_map.get('app_props').get('product_version')
                timestamp = pytz.timezone('US/Pacific').localize(datetime.now()).strftime("%Y%d%m%H%M%S")
                app_extension = build_var_map.get('build_group').get('app-extension')
                module_name = build_var_map.get('build_group').get('module-name')
                if not module_name: 
                    if '-snapshot' in app_version.lower():
                        artifactory_directory = f'npm-snapshot-local/{app_name}/'
                        artifact_name = app_name + '-' + app_version.upper() + '-' + timestamp + '.' + app_extension
                        artifact_loc = app_name + '-' + app_version.upper() + '.' + app_extension
                        subprocess.run(f"cp {artifact_loc} {artifact_name}", shell=True)
                    else:
                        artifactory_directory = f'npm-release-local/{app_name}/'
                        artifact_name = app_name + '-' + app_version + '.' + app_extension
                    upload_packages[artifact_name] = artifactory_directory
             else:    
                app_name = build_var_map.get('app_props').get('app_name')
                module_values_project = build_var_map.get('module_values_project')
                artifact_group = module_values_project.get('artifact_group')
                artifact_group = artifact_group.replace('.', '/')
                app_version = build_var_map.get('app_props').get('product_version')
                timestamp = pytz.timezone('US/Pacific').localize(datetime.now()).strftime("%Y%d%m%H%M%S")
                app_extension = build_var_map.get('build_group').get('app-extension')
                module_name = build_var_map.get('build_group').get('module-name')
                if not module_name: 
                    if '-snapshot' in app_version.lower():
                        artifactory_directory = f'local-snapshot/{artifact_group}/{app_name}/'
                        artifact_name = 'build/libs/' + app_name + '-' + app_version.upper() + '-' + timestamp + '.' + app_extension
                        artifact_loc = 'build/libs/' + app_name + '-' + app_version.upper() + '.' + app_extension
                        subprocess.run(f"cp {artifact_loc} {artifact_name}", shell=True)
                    else:
                        artifactory_directory = f'local-release/{artifact_group}/{app_name}/'
                        artifact_name = 'build/libs/' + app_name + '-' + app_version + '.' + app_extension
                    upload_packages[artifact_name] = artifactory_directory
                else:
                    process_multiple_module_and_upload_artifact(build_var_map,module_name,app_name, app_version, app_extension,artifactory_url, artifactory_user, artifactory_pass, timestamp)
        elif build_var_map.get('app_props').get('build_type') == 'go':
            app_name = build_var_map.get('app_props').get('app_name')
            app_version = build_var_map.get('app_props').get('product_version')
            timestamp = pytz.timezone('US/Pacific').localize(datetime.now()).strftime("%Y%d%m%H%M%S")
            if '-snapshot' in app_version.lower():
                artifactory_directory = f'golang-local/{app_name}/'
                artifact_name = app_name + '-' + app_version.upper() + '-' + timestamp + '.tar.gz'
                artifact_loc = app_name
                subprocess.run(f"cp {artifact_loc} {artifact_name}", shell=True)
            else:
                artifactory_directory = f'golang-local/{app_name}/'
                artifact_name = app_name + '-' + app_version + '.tar.gz'
                artifact_loc = app_name
                subprocess.run(f"cp {artifact_loc} {artifact_name}", shell=True)
            upload_packages[artifact_name] = artifactory_directory
        elif build_var_map.get('app_props').get('app_type') == 'aem':
            app_name = build_var_map.get('app_props').get('app_name')
            app_version = build_var_map.get('app_props').get('product_version')
            artifact_name = artifact_version_env
            zip_artifact_name = artifact_name.replace('-aembundles', '').replace('.tar.gz', '.zip')
        
            # Build Artifactory directories
            artifact_path = f'local-snapshot/{app_name}/{artifact_name}'
            zip_artifact_path = f'local-snapshot/{app_name}/{zip_artifact_name}'
        
            logger.info(f'Artifacts {artifact_name}, {zip_artifact_name} to be uploaded to Artifactory.')
            logger.info(f'Paths: {artifactory_url}/{artifact_path}, {artifactory_url}/{zip_artifact_path}')
        
            # Upload .tar.gz
            tar_source_path = os.path.join(workspace, artifact_name)
            if not os.path.exists(tar_source_path):
                raise FileNotFoundError(f"File not found for upload: {tar_source_path}")
            tar_artifactory_path = ArtifactoryPath(f'{artifactory_url}/{artifact_path}', auth=(artifactory_user, artifactory_pass), auth_type=HTTPBasicAuth)
            try:
                tar_artifactory_path.mkdir()
            except FileExistsError:
                logger.info(f"Path exists: {tar_artifactory_path}")
            logger.info(f"Uploading artifact from: {tar_source_path}")
            tar_artifactory_path.deploy_file(tar_source_path)
        
            # Upload .zip
            zip_source_path = os.path.join(workspace, zip_artifact_name)
            if not os.path.exists(zip_source_path):
                raise FileNotFoundError(f"File not found for upload: {zip_source_path}")
            zip_artifactory_path = ArtifactoryPath(f'{artifactory_url}/{zip_artifact_path}', auth=(artifactory_user, artifactory_pass), auth_type=HTTPBasicAuth)
            try:
                zip_artifactory_path.mkdir()
            except FileExistsError:
                logger.info(f"Path exists: {zip_artifactory_path}")
            logger.info(f"Uploading artifact from: {zip_source_path}")
            zip_artifactory_path.deploy_file(zip_source_path)
        elif build_var_map.get('app_props').get('build_type') == 'ant':
            app_name = build_var_map.get('module_values_project').get('artifact_id')
            app_version = build_var_map.get('module_values_project').get('artifact_version')
            app_extension = build_var_map.get('build_group', {}).get('app-extension', 'zip') 
            artifact_repo = build_var_map.get('app_props', {}).get('artifact_repo')
            module_values_project = build_var_map.get('module_values_project')
            artifact_group = module_values_project.get('artifact_group_id')
            artifact_group = artifact_group.replace('.', '/')  
            #os.system(f"pwd && ls -ltr {workspace}/**")
            timestamp = pytz.timezone('US/Pacific').localize(datetime.now()).strftime("%Y%d%m%H%M%S")
            if '-snapshot' in app_version.lower():
                artifactory_directory = f'local-snapshot/{artifact_group}/{app_name}/'
                artifact_name = f"{app_name}-{app_version.upper()}-{timestamp}.{app_extension}"
                artifact_loc = f"{app_name}.{app_extension}" 
                subprocess.run(f"cp {artifact_loc} {artifact_name}", shell=True)
            else:
                artifactory_directory = f'local-release/{artifact_group}/{app_name}/'
                artifact_name = f"{app_name}-{app_version}.{app_extension}"
                artifact_loc = f"{app_name}.{app_extension}" 
                subprocess.run(f"cp {artifact_loc} {artifact_name}", shell=True)
            upload_packages[artifact_name] = artifactory_directory
        for upload_package,upload_dir in upload_packages.items():
            if os.getenv('GHA_ORG') == 'CDO-KP-ORG':
                artifactory_path = ArtifactoryPath(f'{artifactory_url}/{upload_dir}', apikey=artifactory_token)
            else:
                artifactory_path = ArtifactoryPath(f'{artifactory_url}/{upload_dir}', auth=(artifactory_user, artifactory_pass), auth_type=HTTPBasicAuth)
            try:
                artifactory_path.mkdir()
                logger.info("Uploading artifact")
            except FileExistsError:
                logger.info(f"Path exists, uploading artifact: {artifactory_path}") # catches duplication error for snapshot path  
            if upload_package.endswith(".nupkg"):
                source_path = os.path.join(workspace, 'bin/release', upload_package)
                if not os.path.exists(source_path):
                    raise FileNotFoundError(f"File not found for upload for nupkg: {source_path}")
                logger.info(f"Artifact uploading from: {source_path}")    
                artifactory_path.deploy_file(source_path)
            else:
                artifactory_path.deploy_file(f"{workspace}/{upload_package}")   
    except (ConnectionError,ArtifactoryException) as e:
        logger.error("Artifactory server is down or unreachable.")
        raise RuntimeError(f"{COLOR_RED}Artifactory server is down or unreachable: {e}")          
    except RuntimeError as e:
        raise RuntimeError(f"{COLOR_RED}Error uploading artifact to Artifactory: {e}")


def download_artifact(artifact_url, context=None):
    """
    Download an artifact from Artifactory.

    Args:
        artifact_url (str): The URL of the artifact.
        context (str, optional): The context of the download. Defaults to None.

    Raises:
        RuntimeError: If there is an error downloading the artifact.
    """
    try:
        unzip_artifact = True if os.getenv('UNZIP_ARTIFACT') == 'true' else False
        max_retries = 3
        attempt = 0

        if not artifact_url:
            error_message = (
                f"Artifact lookup failed: No match found in Artifactory for context '{context}'. "
                "Please verify that the artifact_id and artifact_version exists in Artifactory."
            )
            logger.error(error_message)
            raise RuntimeError(error_message)

        while attempt < max_retries:
            try:
                path = ArtifactoryPath(artifact_url, auth=(artifactory_user, artifactory_pass), auth_type=HTTPBasicAuth)
                break
            except (RequestException, RuntimeError) as e:
                logger.error(f"Attempt {attempt + 1}: Failed to connect to Artifactory: {e}")
                attempt += 1
                if attempt < max_retries:
                    time.sleep(5)  
                else:
                    raise RuntimeError(f"{COLOR_RED}Exceeded maximum retries to connect to Artifactory.")

        subprocess.run([f"if [ ! -d {workspace}/{download_path} ]; then mkdir -p {workspace}/{download_path}; fi;"], shell=True)
        download_artifact = artifact_url.split('/')[-1]
        with path.open() as artifact_path, open(f"{workspace}/{download_path}/{download_artifact}", "wb") as artifact_file:
            artifact_file.write(artifact_path.read())
        logger.info(f"Downloaded artifact {download_artifact} into {workspace}/{download_path} directory.")
        if unzip_artifact:
            download_artifact_ext = download_artifact.split('.')[-1]
            if download_artifact_ext == 'zip':
                if context == 'test':
                    subprocess.run(f'unzip -q {workspace}/{download_path}/{download_artifact} -d {workspace}/{download_path}/tmp && cp -R {workspace}/{download_path}/tmp/*/* {workspace}/{download_path}', shell=True)
                else:
                    subprocess.run(f'unzip -q {workspace}/{download_path}/{download_artifact} -d {workspace}/{download_path}', shell=True)
            else:
                subprocess.run([f"tar -xvf {workspace}/{download_path}/{download_artifact} -C {workspace}/{download_path} --strip 1"], shell=True)
            subprocess.run(f'rm {workspace}/{download_path}/{download_artifact}', shell=True)
        subprocess.run([f"rm -rf {workspace}/{download_path}/tmp && cd {workspace}/{download_path} && ls -ltr"], shell=True)
        download_artifact_path = f'{download_path}/{download_artifact}'
        os.system(f"echo 'download-artifact={download_artifact_path}' >> $GITHUB_OUTPUT")
        return download_artifact_path
    except (ConnectionError,ArtifactoryException) as e:
        logger.error("Artifactory server is down or unreachable.")
        raise RuntimeError(f"{COLOR_RED}Artifactory server is down or unreachable: {e}")      
    except RuntimeError as e:
        raise RuntimeError(f"{COLOR_RED}Error downloading artifact from Artifactory: {e}")

def process_multiple_module_and_upload_artifact(build_var_map,module_name,app_name, app_version, app_extension,artifactory_url, artifactory_user, artifactory_pass, timestamp):
    module_values_project = build_var_map.get('module_values_project')
    artifact_group = module_values_project.get('artifact_group')
    artifact_group = artifact_group.replace('.', '/')
    module_names_string = build_var_map.get('build_group', {}).get('module-name', '')
    module_names = [name.strip() for name in module_names_string.split(',')]
    
    if '-snapshot' in app_version.lower():
        artifact_name = f'build/libs/{app_name}-{app_version.upper()}-{timestamp}.{app_extension}'
    else:
        artifact_name = f'build/libs/{app_name}-{app_version}.{app_extension}'

    # Handle multi-level module (if there are multiple modules)
    if len(module_names) > 1:
        app_extensions = build_var_map.get('build_group', {}).get('app-extension', '').split(',')
        for module in module_names:
            for ext in app_extensions:
                artifactory_directory = f'libs-release-local/{artifact_group}/{module}/{app_version}/' 
                artifact_loc = glob.glob(f"{module}/build/**/*{module}-{app_version}.{ext}", recursive=True)
                if artifact_loc:
                    artifact_name = artifact_loc[0]
                    upload_packages = {artifact_name: artifactory_directory}
                    for upload_package, upload_dir in upload_packages.items():
                        artifactory_path = ArtifactoryPath(f'{artifactory_url}/{upload_dir}', auth=(artifactory_user, artifactory_pass), auth_type=HTTPBasicAuth)
                        try:
                            artifactory_path.mkdir()
                            logger.info("Uploading artifact")
                        except FileExistsError:
                            logger.info(f"Path exists, uploading artifact: {artifactory_path}")
                        artifactory_path.deploy_file(f"{workspace}/{upload_package}")
                else:
                    continue
    else:
            artifactory_directory = f'libs-release-local/{artifact_group}/{module_name}/{app_version}/' 
            artifact_loc = glob.glob(f"{module_name}/build/libs/{app_name}-*.{app_extension}", recursive=True)
            logger.info(f"Artifactory directory: {artifactory_directory}")
            logger.info(f"Artifact location: {artifact_loc}")
            if artifact_loc:
                artifact_name = artifact_loc[0]
                artifactory_path = ArtifactoryPath(f'{artifactory_url}/{artifactory_directory}', auth=(artifactory_user, artifactory_pass), auth_type=HTTPBasicAuth)
                try:
                    artifactory_path.mkdir()
                    logger.info("Uploading artifact")
                except FileExistsError:
                       logger.info(f"Path exists, uploading artifact: {artifactory_path}")
                artifactory_path.deploy_file(f"{workspace}/{artifact_name}")
            else:
                logger.error("Artifact not found")           
def get_input_map():
    raw_input = os.getenv('INPUT_MAP')
    if not raw_input or raw_input == 'null':
        input_map = {}
    else:
        input_map = yaml.safe_load(raw_input)
    logger.info(f"Input Map is: {input_map}")
    input_map = {
        k: v.strip() if isinstance(v, str) else v
        for k, v in input_map.items()
    }
    application_name = input_map.get('application-name') or input_map.get('application_name')
    return input_map, application_name
