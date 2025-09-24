import os
import subprocess
import yaml
import sys
import pytz
import json
import utils
import utils.standalone_docker_build as standalone_docker_build
from datetime import datetime
from kpghalogger import KpghaLogger
logger = KpghaLogger()

workspace = os.getenv('GITHUB_WORKSPACE')
aks_constants = os.getenv('AKS_CONSTANTS')


def main():
    operation = sys.argv[1]
    config_map = yaml.safe_load(os.getenv('CONFIG_MAP'))
    if operation == 'set-image-vars':
        set_image_vars(config_map)
        return
    artifact_properties = config_map.get('build_props')
    vendor_deploy = config_map.get('app_props', {}).get('is_vendor_deployment', False)
    logger.info(f"vendor deploy flag: {vendor_deploy}")
    if not vendor_deploy:
        image_repo = config_map.get('image').get('image_path')
        docker_base_image = config_map.get('image').get('docker_base_image')
        artifact_type = config_map.get('app_props').get('artifact_type')
        artifact_version = artifact_properties.get('APP_VERSION').replace('-snapshot','').replace('-release','')
        try:
            if operation == 'build':
                if os.getenv('GHA_ORG') == 'CDO-KP-ORG':
                    check_docker_path()
                build_docker_image(artifact_properties, docker_base_image, artifact_type,artifact_version)
                image_repo = config_map.get('image').get('image_path')
                subprocess.run([f"""echo "#### :shield: [Image path]({image_repo})" >> $GITHUB_STEP_SUMMARY"""], shell=True)
            elif operation == 'push':
                docker_image_name = image_repo.split('/')[-1]
                docker_image_repo = image_repo.split(f'/{docker_image_name}')[0]
                push_docker_image(docker_image_repo, docker_image_name)
        except Exception as e:
            raise Exception(f'Error in docker action: {e}')
    else: 
        image = os.getenv('IMAGE')
        logger.info(f"This is a vendor docker image build/publish: {image}")
        image_with_version = os.getenv('IMAGE_WITH_VERSION')
        image_info = config_map.get("images", {}).get(image_with_version, {})
        logger.info(f"The images to build and publish: {image_info}")
        namespace = config_map.get("deploy_platform", {}).get("deployEnvironments", {}).get("dev", {}).get("namespace", {})
        # for image_name, image_details in images.items():
        if operation == 'build':
            artifact_version = image_info.get('image_version')
            docker_base_image = image_info.get("docker_base_image", "N/A")
            logger.info(f"Image Name: {image}")
            create_dockerfile(docker_base_image, image, namespace)
            image_tag = build_docker_image(artifact_properties, docker_base_image, 'vendor',artifact_version)
            logger.info(f'image tag: {image_tag}')
            os.system(f"echo 'docker-image-name={image_tag}' >> $GITHUB_OUTPUT")
            os.remove('Dockerfile')
        elif operation == 'push':
            image_repo = image_info.get('image_path')
            logger.info(f'image repo: {image_repo}')
            docker_image_name = image_repo.split('/')[-1]
            logger.info(f'docker image name: {docker_image_name}')
            docker_image_repo = image_repo.split(f'/{docker_image_name}')[0]
            logger.info(f'docker image repo: {docker_image_repo}')
            push_docker_image(docker_image_repo, docker_image_name)


def check_docker_path():
    os.chdir(workspace)
    path_text = subprocess.run([f'grep "^COPY.*target" Dockerfile | head -n 1'], shell=True, stdout=subprocess.PIPE).stdout.decode('utf-8').strip()
    path_line = subprocess.run([f'grep -n "^COPY.*target" Dockerfile | head -n 1 | cut -d: -f1'], shell=True, stdout=subprocess.PIPE).stdout.decode('utf-8').strip()
    copy_path = path_text.split('target/')[0].split(' ')[-1].split('/')[0]
    if copy_path:
        logger.info(f"Docker Path: {path_text}")
        logger.info(f"Removing {copy_path}/ from Dockerfile line {path_line} for docker build")
        subprocess.run(["sed -i -e '" + path_line + "s/" + copy_path + "\///g' Dockerfile"], shell=True)


def build_docker_image(artifact_properties, docker_base_image, artifact_type,artifact_version):
    git_ssha = artifact_properties.get('GIT_COMMIT_SSHA')
    if artifact_type == 'vendor':
        app_name = docker_base_image.split("/")[-1].split(":")[0]
        # Below condition is to unblock fusion team temporarily. Will be removed in future
        if app_name == 'fusion-solr':
            app_name = 'solr'
    else: 
        app_name = artifact_properties.get('APP_NAME')
    
    build_date = pytz.timezone('US/Pacific').localize(datetime.now()).strftime("%Y%d%m%H%M%S")
    image_labels = f""" \
    --label 'APP={app_name}' \
    --label 'BUILD_DATE={build_date}' \
    --label 'GIT_URL={artifact_properties.get('GIT_URL')}' \
    --label 'GIT_BRANCH={artifact_properties.get('GIT_BRANCH')}' \
    --label 'GIT_COMMIT={artifact_properties.get('GIT_COMMIT')}' \
    --label 'BUILD_URL={artifact_properties.get('BUILD_URL')}' \
    --label 'APP_BUILD_VERSION={artifact_properties.get('APP_VERSION')}' \
    --label 'ARTIFACTORY_REPO={artifact_properties.get('ARTIFACTORY_REPO')}' \
    --label 'GIT_COMMIT_SSHA={git_ssha}' \
    --label 'KP_PIPELINE_TYPE={artifact_properties.get('KP_PIPELINE_TYPE')}' \
    --label 'KP_ATLAS_ID={artifact_properties.get('KP_ATLAS_ID')}' \
    --label 'KP_TECHNICAL_OWNER={artifact_properties.get('KP_TECHNICAL_OWNER')}' \
    --label 'KP_PRODUCT_LINE={artifact_properties.get('KP_PRODUCT_LINE')}' \
    --label 'KP_JIRA_PROJECT_KEY={artifact_properties.get('KP_JIRA_PROJECT_KEY')}' \
    --label 'KP_HOST_IDENTIFIER={artifact_properties.get('KP_HOST_IDENTIFIER')}' \
    --label 'TEAM_NAME={artifact_properties.get('REPO_ORG')}' \
    --label 'ARTIFACT_TYPE={artifact_type}' \
    --label 'BASE_IMAGE={docker_base_image}' \
    --label 'NAMESPACE={artifact_properties.get('AKS_NAMESPACE')}'"""
    image_tag = f"{app_name}:{artifact_version.lower()}"
    if artifact_type == "vendor":
        image_tag = f"{image_tag}"
    elif git_ssha: image_tag = f"{image_tag}.{git_ssha}"
    logger.info(f"Building docker image {image_tag}")

    build_cmd = f"docker build --no-cache --rm -t {image_tag} {image_labels} ."
    build_cmd_str = build_cmd.strip()
    image_build = subprocess.run([build_cmd_str], shell=True).returncode
    if image_build == 0:
        os.system(f"echo 'docker-image-name={image_tag}' >> $GITHUB_OUTPUT")
        return image_tag
    else: raise OSError('Docker build failed.')
    
    
def push_docker_image(docker_image_repo, docker_image_name):
    docker_image_tag_cmd = f'docker image tag {docker_image_name} {docker_image_repo}/{docker_image_name}'
    logger.info(f'docker image tag cmd: {docker_image_tag_cmd}')
    subprocess.run([docker_image_tag_cmd], shell=True)
    
    docker_push_cmd = f'docker push {docker_image_repo}/{docker_image_name}'
    logger.info(f'docker push cmd: {docker_push_cmd}')
    subprocess.run([docker_push_cmd], shell=True)


def set_image_vars(deploy_var_map):
    deploy_env = os.getenv('DEPLOY_ENV')
    aks_constant_map = yaml.safe_load(aks_constants)
    image_base_url = aks_constant_map.get('registry-url').strip()
    os.system(f"echo 'app-name={deploy_var_map.get('app_props').get('app_name')}' >> $GITHUB_OUTPUT")
    os.system(f"echo 'deploy-environment={deploy_env}' >> $GITHUB_OUTPUT")
    service_map = deploy_var_map.get('deploy_config_yml').get(deploy_env)
    image_promotion = False
    if not any(deploy_env.startswith(substring) for substring in aks_constant_map.get('image-promotion-dev-envs', [])):
        image_promotion = True
    logger.info(f"image promotion for env = {deploy_env}: {image_promotion}")
    os.system(f"echo 'image-promotion={image_promotion}' >> $GITHUB_OUTPUT")
    if 'is_vendor_deployment' not in deploy_var_map.get('app_props'):
        image_map = deploy_var_map.get('image')
        image_repo_path = image_map.get('image_path')
        os.system(f"echo 'image-ssha={image_repo_path.split('.')[-1]}' >> $GITHUB_OUTPUT")
        os.system(f"echo 'image-path={image_repo_path.split(':')[0].replace(image_repo_path.split('/')[0],'').lstrip('/')}' >> $GITHUB_OUTPUT")
        os.system(f"echo 'image-registry={service_map.get('image_registry')}.{image_base_url}' >> $GITHUB_OUTPUT")
        os.system(f"echo 'image-promotion-registry={service_map.get('image_promotion_registry')}.{image_base_url}' >> $GITHUB_OUTPUT")
        os.system(f"echo 'image-dir={deploy_var_map.get('app_props').get('image_dir')}' >> $GITHUB_OUTPUT")
        if deploy_var_map.get('app_props').get('artifact_type') == 'DOCKER':
            os.system(f"echo 'app-version={deploy_var_map.get('build_props').get('APP_VERSION').lower().replace('-snapshot','').replace('-release','')}' >> $GITHUB_OUTPUT")
        else:
            os.system(f"echo 'app-version={deploy_var_map.get('module_values_deploy').get('artifact_version').lower().replace('-snapshot','').replace('-release','')}' >> $GITHUB_OUTPUT")
    elif 'is_vendor_deployment' in deploy_var_map.get('app_props') and deploy_var_map.get('app_props').get('is_vendor_deployment') == True:
        os.system(f"echo 'image-map={json.dumps(deploy_var_map)}' >> $GITHUB_OUTPUT")

def create_dockerfile(docker_base_image, image, namespace):
    file_content = f"""FROM {docker_base_image}
    LABEL namespace={namespace}"""

    # Open the file in write mode and write the multiline content
    with open('Dockerfile', "w") as file:
        file.write(file_content)
    logger.info(f'Dockerfile for {image} created successfully')

if __name__ == '__main__':
    logger.info(logger.format_msg('GHA_EVENT_ACTION_AUD_2_9000', 'action entry/exit point', {"detailMessage": "action metric", "metrics": {"state": "start"}}))
    action = os.getenv('ACTION_TYPE')

    if action is None:
        main()
    else:
        if action == 'build-image':
            standalone_docker_build.build_docker_image()
        elif action == 'push-image':
            standalone_docker_build.push_docker_image()
        elif action == 'push-multi-image':
            standalone_docker_build.push_multiple_docker_images()
        elif action == 'scan-image':
            standalone_docker_build.scan_image()
        elif action == 'send-notification':
            standalone_docker_build.send_email()
        elif action == 'set-target-registry':
            standalone_docker_build.set_target_registry()
    logger.info(logger.format_msg('GHA_EVENT_ACTION_AUD_2_9000', 'action entry/exit point', {"detailMessage": "action metric", "metrics": {"state": "end"}}))