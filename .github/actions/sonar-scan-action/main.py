import os
import subprocess
import requests
import urllib
import yaml
import re
import base64
from time import sleep
from urllib.parse import unquote
from kpghalogger import KpghaLogger
import json
logger = KpghaLogger()

COLOR_RED = "\u001b[31m"
workspace = os.getenv('GITHUB_WORKSPACE')
sonar_user = os.getenv('SONARQUBE_TOKEN')
git_branch = os.getenv('GITHUB_REF_NAME')
repo_name = os.getenv('PROJECT_GIT_REPO')
org_name = os.getenv('PROJECT_GIT_ORG')
base_branch = os.getenv('GITHUB_HEAD_REF')
target_branch = os.getenv('GITHUB_BASE_REF')
sonar_url = yaml.safe_load(os.getenv('SONARQUBE_URL')).get('production')
quality_gate = yaml.safe_load(os.getenv('SONARQUBE_QUALITY_GATE'))
sonar_quality_profiles = os.getenv('SONAR_QUALITY_PROFILE')
token = base64.b64encode(f"{sonar_user}:".encode()).decode()
header = {'Authorization': f"Basic {token}"}

def main(build_var_map):
    """
    Main function to execute the SonarQube scan process.
    This function performs the following steps:
    1. Parses the configuration map to extract build variables and paths.
    2. Sets up default and custom SonarQube exclusions and inclusions.
    3. Constructs the SonarQube scanner command with appropriate parameters.
    4. Executes the SonarQube scan and logs the results.
    5. Extracts the analysis report URL and outputs it for GitHub Actions.
    6. Handles errors and logs appropriate messages.
    Args:
        config_map (str): YAML string containing the configuration map with build variables.
    Raises:
        Exception: If an error occurs during the SonarQube scan process.
    Notes:
        - The function uses environment variables such as `GHA_ORG` and `GITHUB_STEP_SUMMARY`.
        - It supports multiple report formats including Cobertura, Jacoco, JUnit, Python coverage, and more.
        - The function checks if the project exists in SonarQube and creates it if necessary.
        - Pull request-specific parameters are included if the branch name indicates a PR.
    """
    try:
        # vars from build map
        global quality_gate
        build_group = build_var_map.get('build_group')
        sonar_clean_build = build_group.get('sonarCoverageCheck') if build_group.get('sonarCoverageCheck') else False
        logger.info(f"Sonar coverage check during declar: {sonar_clean_build}")
        app_type = build_var_map.get('app_type')
        project_version = build_var_map.get('module_values_project').get('artifact_version')
        project_src_dir = build_group.get('source-directory')
        cobertura_report_path = build_group.get('cobertura-report-path') if build_group.get('cobertura-report-path') else '**/target/site/cobertura/coverage.xml, **/cobertura.xml'
        js_lcov_report_path = build_group.get('js-lcov-report-path') or ''
        jacoco_report_path = build_group.get('jacoco-report-path') or build_group.get('jacocoReportPath') or 'core/target/site/jacoco/jacoco.xml'
        junit_report_path = build_group.get('junitReportPath') or ''
        gen_report_path = build_group.get('test-report-path') if build_group.get('test-report-path') else ''
        pycov_report_path = build_group.get('pycovReportPath') or ''
        pyunit_report_path = build_group.get('pyunitReportPath') if build_group.get('pyunitReportPath') else '**/test-reports/*.xml'
        dncov_report_path = build_group.get('cov-report-path') or ''
        sonar_inclusions = build_group.get('sonar-inclusions') or ''
        sonar_coverage_inclusions = build_group.get('sonar-coverage-inclusions') or ''
        # default sonar vars
        default_sonar_exclusions = default_sonar_excl()
        default_sonar_coverage_exclusions = default_sonar_coverage_excl(app_type)
        sonar_coverage_exclusions = build_group.get('sonar-coverage-exclusions') if build_group.get('sonar-coverage-exclusions') else build_group.get('sonarCoverageExclusions')
        sonar_exclusions = build_group.get('sonar-exclusions') if build_group.get('sonar-exclusions') else build_group.get('sonarExclusions')
        exclusions = default_sonar_exclusions + \
            sonar_exclusions if sonar_exclusions else default_sonar_exclusions
        default_sonar_coverage_exclusions = default_sonar_coverage_exclusions + \
            sonar_coverage_exclusions if sonar_coverage_exclusions else default_sonar_coverage_exclusions
        project_src_dir = f"{workspace}/{project_src_dir}" if project_src_dir else workspace
        pr_sonar_params = ''
        # create project if none exists
        if sonar_clean_build:
            quality_gate = yaml.safe_load(os.getenv('CLEANBUILD_SONARQUBE_QUALITY_GATE'))
        check_if_project_exists(sonar_url, quality_gate, org_name, repo_name)
        # run sonar scan
        if os.getenv('GHA_ORG') == 'ENTERPRISE':
           sonar_project_key = f"-Dsonar.projectKey={repo_name}"
        else:
           sonar_project_key = f"-Dsonar.projectKey={org_name}:{repo_name}"
        if 'PR-' in git_branch:
            pr_id = git_branch
            pr_sonar_params = f" -Dsonar.pullrequest.key={pr_id} -Dsonar.pullrequest.branch={target_branch} -Dsonar.pullrequest.base={base_branch} -Dsonar.pullrequest.github.repository={org_name}/{repo_name} -Dsonar.pullrequest.github.endpoint=https://github.kp.org/api/v3"
        sonar_shell_cmd = f"""cd {project_src_dir} && sonar-scanner -e \\
        {sonar_project_key}\\
        -Dsonar.host.url={sonar_url} \\
        -Dsonar.projectName={repo_name} \\
        -Dsonar.projectVersion={project_version} \\
        -Dsonar.exclusions='{",".join(exclusions)}' \\
        -Dsonar.coverage.exclusions='{",".join(default_sonar_coverage_exclusions)}' \\
        -Dsonar.coverage.jacoco.xmlReportPaths='{jacoco_report_path}' \\
        -Dsonar.junit.reportPaths='{junit_report_path}' \\
        -Dsonar.javascript.lcov.reportPaths='{js_lcov_report_path}' \\
        -Dsonar.testExecutionReportPaths='{gen_report_path}' \\
        -Dsonar.python.coverage.reportPaths='{pycov_report_path}' \\
        -Dsonar.python.xunit.reportPath='{pyunit_report_path}' \\
        -Dsonar.cs.opencover.reportsPaths='{dncov_report_path}' \\
        -Dsonar.cs.xunit.reportsPaths='{dncov_report_path}' \\
        -Dsonar.cobertura.reportPath='{cobertura_report_path}' \\
        -Dsonar.sourceEncoding=UTF-8 \\
        -Dsonar.java.binaries=. \\
        -Dsonar.java.libraries=. \\
        -Dsonar.c.file.suffixes=- \\
        -Dsonar.cpp.file.suffixes=- \\
        -Dsonar.objc.file.suffixes=- \\
        -Dsonar.qualitygate.wait=true \\
        -Dsonar.qualitygate.timeout=600 \\
        -Dsonar.inclusions='{sonar_inclusions}' \\
        -Dsonar.coverage.inclusions='{sonar_coverage_inclusions}' 
        {pr_sonar_params}"""
        logger.info(f'Sonar execution command: \n{sonar_shell_cmd}') 
        ### adding sonar result link for pr build
        sonar_result = subprocess.run([sonar_shell_cmd], stdin=subprocess.PIPE, capture_output=True, shell=True, text=True)
        logger.info(f"Sonar command output: {sonar_result.stdout}")
        if sonar_result.returncode == 0:
            stdout = sonar_result.stdout
        # Search for a specific pattern using regex
            stdout = sonar_result.stdout if sonar_result.stdout else ""
            pattern = r"QUALITY GATE STATUS: PASSED - View details on (https?://\S+)|QUALITY GATE STATUS: FAILED - View details on (https?://\S+)"
            match = re.search(pattern, stdout)
            if match:
                logger.info("Sonar report Pattern found in the output")
                sonar_summary_report = match.group(1) or match.group(2)
                subprocess.run([f"""echo "#### :chart_with_upwards_trend: [Sonar report]({sonar_summary_report})" >> $GITHUB_STEP_SUMMARY"""], shell=True)
    # You can perform additional operations here
            else:
                logger.info("Sonar report url pattern not found in the output")        
        else:
            stderr = sonar_result.stderr
            logger.warning(logger.format_msg('GHA_TRO_SONAR_SYS_4_2002', 'Sonar Command failed', {'detailMessage': f'Sonar command execution failed: {stderr}', 'metrics': {'status': 'failure'}}))
    
        # get report and set output analysis id
        report_path_cmd = f"cat {project_src_dir}/.scannerwork/report-task.txt | grep 'ceTaskUrl' | cut -d= -f2,3"
        report_analysis_id = subprocess.check_output(
            [report_path_cmd], shell=True, text=True).strip()
        os.system(f"echo 'scan-report-analysis-id={report_analysis_id}' >> $GITHUB_OUTPUT")
        #os.system(f"echo 'scan-report-url={sonar_summary_report}' >> $GITHUB_OUTPUT")
        logger.info(logger.format_msg('GHA_TRO_SONAR_BIZ_2_0002', 'Sonar scan completed', {'detailMessage': f'Sonar scan completed on analysis report id: {report_analysis_id}', 'metrics': {'status': 'success'}}))
    except Exception as e:
        logger.error(logger.format_msg('GHA_TRO_SONAR_SYS_4_2001', 'Error in Sonar scan', {'detailMessage': f'Error in Sonar scan: {e}', 'metrics': {'status': 'failure'}}))
        raise Exception(f'{COLOR_RED}Error in Sonar scan:{e}.')
    

def check_if_project_exists(sonar_url, quality_gate, org_name, repo_name):
    sonar_project_key = f"{repo_name}" if os.getenv('GHA_ORG') == 'ENTERPRISE' else f"{org_name}:{repo_name}"
    request = requests.get(f"{sonar_url}api/project_analyses/search?project={sonar_project_key}", headers=header)
    logger.info(f"checking if the project exists in sonar : {request.status_code}")
    # create new project
    if request.status_code == 404:
        logger.info(f"[INFO] Repo {repo_name} in organization {org_name} not found in Sonar. Creating new project.")
        request_project = requests.post(f"{sonar_url}api/projects/create?name={repo_name}&project={sonar_project_key}", headers=header)
        logger.info(f'create new project response: {request_project.content.strip()}')
        assign_quality_gate(sonar_project_key, quality_gate)
    else:
        # Check the quality gate with the provided API
        quality_gate_check_url = f"{sonar_url}api/qualitygates/get_by_project?project={sonar_project_key}"
        logger.info(f"Checking quality gate with URL: {quality_gate_check_url}")
        try:
            if org_name == 'CDO-KP-ORG':
                sleep(15) # Wait for a few seconds to ensure the project is fully created
                response = requests.get(quality_gate_check_url, headers=header)
                response.raise_for_status()
                quality_gate_data = response.json()
                current_quality_gate = quality_gate_data.get('qualityGate', {}).get('name', '')
                logger.info(f"Current quality gate for project {sonar_project_key}: {current_quality_gate}")
                # If the quality gate is "DOET Standard" or "KPDDEVSECOPS" for CDO-KP-ORG then return True
                if current_quality_gate in ["DOET Standard", "KPDDEVSECOPS"]:
                    logger.info("Quality gate is '%s'. Proceeding with the process.", current_quality_gate)
                    return True
            else:
                assign_quality_gate(sonar_project_key, quality_gate)
        except requests.HTTPError as e:
            logger.error(logger.format_msg('GHA_TRO_SONAR_SYS_4_2005', 'HTTP error occurred while checking quality gate', {'detailMessage': f'HTTP error: {e}', 'metrics': {'status': 'failure'}}))
        except Exception as e:
            logger.error(logger.format_msg('GHA_TRO_SONAR_BIZ_4_2006', 'An error occurred while checking quality gate', {'detailMessage': f'Error occurred: {e}', 'metrics': {'status': 'failure'}}))
        

# assign quality gate
def assign_quality_gate(sonar_project_key, quality_gate):
    request_quality_url = f"{sonar_url}api/qualitygates/select?gateName={quality_gate}&projectKey={sonar_project_key}"
    logger.info(f"Sending request to: {request_quality_url}")
    max_retries = 3
    backoff = 2
    for attempt in range(max_retries):
        try:
            response = requests.post(request_quality_url, headers=header)
            logger.info(f"Response Status Code: {response.status_code}")
            logger.info(f"Response Content: {response.content}")
            response.raise_for_status()
            response_content = response.content.strip()
            logger.info(logger.format_msg('GHA_TRO_SONAR_BIZ_2_0001', 'Request was successful', {'detailMessage': f'Successful request, received: {response_content}', 'metrics': {'status': 'success'}}))
            return True
        except requests.HTTPError as e:
            logger.error(logger.format_msg('GHA_TRO_SONAR_SYS_4_2003', 'HTTP error occurred', {'detailMessage': f'HTTP error: {e}', 'metrics': {'status': 'failure'}}))
            logger.error(f"Response Content: {response.content}")
        except Exception as e:
            logger.error(logger.format_msg('GHA_TRO_SONAR_BIZ_4_2004', 'An error occurred', {'detailMessage': f'Error occurred: {e}', 'metrics': {'status': 'failure'}}))
        if attempt < max_retries - 1:
            sleep(backoff * (2 ** attempt))

# default sonar exclsuions
def default_sonar_excl():
    default_sonar_exclusions = [
        "**/target/**,**/target/*",
        "**/node_modules/**",
        "**/bower_components/**",
        "**/*.jpg,**/*.svg,**/vendor.bundle.js",
        "**/app-info.yaml",
        "**/app-info.yml",
        "kpaudit_config.js",
        "**/actions/**/*.py",
        "*.py",
        "**/bin/**/*.py",
        "**/DodConfig.yaml",
        "test-suite/index.html",
        "**/htmlcov/**",
        "tmp/**",
        "**/VirtualServer.yaml",
        "**/Service.yaml",
        "**/Policy.yaml",
        "**/Deployment.yaml",
        "**/HorizontalPodAutoscaler.yaml",
        "**/Ingress.yaml",
        "**/ConfigMap.yaml",
        "**/build_var_map.yml",
        "**/pipeline.yml",
        "**/*.zip",
        "**/catalog-info.yaml",
        "**/cicd/*",
        "**/ReleaseReadinessConfig.yaml",
        "**/*.sh"
    ]
    return default_sonar_exclusions

def default_sonar_coverage_excl(app_type):
    if app_type == 'aem':
        default_sonar_coverage_exclusions = [
            '**/src/test/**/*.java,**/it.tests/**/*.java,**/it/tests/**/*.java,**/jcr_root/**/*.js']
    else:
        default_sonar_coverage_exclusions = [
            "**/it.tests/**",
            "**/test/**/*",
            "**/tests/**",
            "**/test-reports/**",
            "test-suite/index.html",
            "tmp/**",
            
        ]
    return default_sonar_coverage_exclusions

if __name__ == '__main__':
    logger.info(logger.format_msg('GHA_EVENT_ACTION_AUD_2_9000', 'action entry/exit point', {"detailMessage": "action metric", "metrics": {"state": "start"}}))
    build_map = yaml.safe_load(os.getenv('CONFIG_MAP'))
    main(build_map)
    logger.info(logger.format_msg('GHA_EVENT_ACTION_AUD_2_9000', 'action entry/exit point', {"detailMessage": "action metric", "metrics": {"state": "end"}}))