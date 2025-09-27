import os
import sys
import requests
import time
import yaml
import json
import re
from kpghalogger import KpghaLogger
logger = KpghaLogger()

COLOR_RED = "\u001b[31m"
sonar_user = os.getenv('SONARQUBE_TOKEN')
branch_name = os.getenv('GITHUB_REF_NAME')
is_pr = os.environ.get('GITHUB_HEAD_REF')
git_branch = os.getenv('GITHUB_REF_NAME')
org_name = os.getenv('PROJECT_GIT_ORG')
bot_deploy = os.getenv('BOT_DEPLOY')
bot_rule_map = os.getenv('BOT_RULES_MAP')
sonar_exception_result = json.loads(os.getenv('SONAR_EXCEPTION_STATUS')).get('sonar') if (org_name == 'CDO-KP-ORG' or org_name == 'SDS') and os.getenv('SONAR_EXCEPTION_STATUS') else False
header = {'Authorization': f"{sonar_user}"}
base_sonar_url = 'https://sonarqube-bluemix.kp.org/api'
config_map = yaml.safe_load(os.getenv('CONFIG_MAP'))
build_group = config_map.get('build_group')
sonar_clean_build = build_group.get('sonarCoverageCheck') if build_group.get('sonarCoverageCheck') else False

def get_quality_gate_status(analysis_id):
    url = f"{base_sonar_url}/qualitygates/project_status?analysisId={analysis_id}"
    analysis_report = requests.request("GET", url, headers=header)
    logger.info(f"Analysis report project status: {analysis_report.json().get('projectStatus')}")
    sonar_inital_scan = analysis_report.json().get('projectStatus').get('period')
    artifact_version = '' #Initialize the variable
    if sonar_inital_scan:
        try:
            # period is a dict, not a list
            artifact_version = analysis_report.json().get('projectStatus').get('period').get('parameter')
        except Exception as e:
            artifact_version = branch_name
    else:
        logger.info("Sonar Scan has run for the first time on this project")
    quality_gate_status = analysis_report.json().get('projectStatus').get('status')
    quality_gate_project_status = analysis_report.json().get('projectStatus')
    if bot_deploy == 'true':
        bot_json_map = json.loads(bot_rule_map)
        if bot_json_map.get("SonarQubeCheckisRequired"):
            sonar_threshold = bot_json_map.get("QualityChecks").get("new_coverage")
            logger.info(f"sonar threshold {sonar_threshold}")
            for condition in quality_gate_project_status['conditions']:
                if condition['status'] != "OK" and condition['metricKey'] != "coverage":
                    quality_gate_status = "Fail"
                    logger.error("Sonar failed for other metrics and no need to override with golden rule")
                    break
                if condition['metricKey'] == "new_coverage":
                    if float(condition['actualValue']) < sonar_threshold:
                        quality_gate_status = "Fail"
                        logger.error(f"Sonar coverage failed bot rule validation: Threshold is {sonar_threshold} and actual is {condition['actualValue']}")
                    else:
                        quality_gate_status = "OK"
        else:
            quality_gate_status = "SKIP"
            logger.error("BOT Sonar Check is marked as Skip in golden rule")
    logger.info(f"[INFO]: quality gate status is {quality_gate_status}")
    pr_result_map(quality_gate_status)
    logger.info(f"Sonar info --> Artifact Version: {artifact_version} -- Quality Gate Status: {quality_gate_status}")
    os.system(f"echo 'quality-gate-status={quality_gate_status}' >> $GITHUB_OUTPUT")
    logger.info(f"Sonar coverage check: {sonar_clean_build}")
    if not is_pr and sonar_clean_build and quality_gate_status != "OK":
        raise Exception(f"{COLOR_RED}Error in Sonar Quality Gate status: {quality_gate_status}")
    os.system(f"echo 'quality-gate-project-status={json.dumps(quality_gate_project_status)}' >> $GITHUB_OUTPUT")

def pr_result_map(quality_gate_status):
    #Creating resultmap to add comments in the conversation of Pull request
    logger.info(f"is_pr: {is_pr}")
    if is_pr or 'PR-' in git_branch:
        logger.info(f"Sonar gate status: {quality_gate_status}")
        try:
            pr_builder = yaml.safe_load(os.getenv("PR_BUILDER"))
            result_map ={}
            result_map['result_map'] = []
            sonar_gate_check_title = pr_builder.get('sonarqube-check').get('title')
            sonar_gate_check_squad = pr_builder.get('sonarqube-check').get('squads')
            logger.info(f"Sonar Exception gate status: {sonar_exception_result}")
            if quality_gate_status == "OK":
                sonar_gate_check_result = True
                sonar_gate_check_comment = "Quality Gate passed for pull request"
            elif quality_gate_status != "OK" and sonar_exception_result == False and not sonar_clean_build:
                logger.info("Sonar quality gate exception is enabled")
                sonar_gate_check_result = True
                sonar_gate_check_comment = "Quality Gate passed for pull request (exception applied)"
            elif quality_gate_status != "OK" and sonar_clean_build:
                sonar_gate_check_result = False
                sonar_gate_check_comment = "Quality Gate failed for pull request. Please find the report in summary "
            else:
                sonar_gate_check_result = False
                sonar_gate_check_comment = "Quality Gate failed for pull request"

            result_map['result_map'].append({'title':sonar_gate_check_title, 'squads': sonar_gate_check_squad, 'result': sonar_gate_check_result, 'comments': f'{sonar_gate_check_comment}' }) 
            logger.info(f"result map in sonar check: {result_map}")
            os.system(f"echo 'result-map={json.dumps(result_map)}' >> $GITHUB_OUTPUT")
        except Exception as e:
            logger.error(f'Error in PR Result map method :{e}.')
            raise Exception(f'{COLOR_RED}Error in PR Result map method :{e}.')
  
def get_analysis_id():
    """
    Retrieves the analysis ID and component key from a SonarQube task URL.
    This function sends repeated GET requests to the provided task URL to fetch
    the analysis ID and component key from the SonarQube task response. It retries
    every 5 seconds, up to a maximum of 30 seconds, until the analysis ID is obtained.
    """
    task_id_url = sys.argv[1]
    logger.info(f"[INFO]:task id url is: {task_id_url}")
    analysis_id = None
    seconds = 5
    while not analysis_id and seconds <= 30:
        time.sleep(seconds)
        analysis_response = requests.request("GET", task_id_url, headers=header)
        if re.match('^2', str(analysis_response.status_code)):
            analysis_task = analysis_response.json().get('task')
            analysis_id = analysis_task.get('analysisId')
            component_key = analysis_task.get('componentKey')
        logger.info(f'Analysis ID: {analysis_id}')
        seconds += 5
    if not analysis_id:
        raise Exception(f'{COLOR_RED}Sonar did not respond within 30 seconds.')
    return [analysis_id, component_key]
    

if __name__ == "__main__":
    analysis_id, component_key = get_analysis_id()
    get_quality_gate_status(analysis_id)
