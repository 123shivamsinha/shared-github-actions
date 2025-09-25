import os
import yaml
import json
from datetime import datetime
from kpghalogger import KpghaLogger
logger = KpghaLogger()

workspace = os.getenv('GITHUB_WORKSPACE')
artifactory_prop = os.getenv('ARTIFACTORY_PROP')
COLOR_RED = "\u001b[31m"

def main():
    exclusion_status = True
    try:
        artifactory_props = yaml.safe_load(artifactory_prop) if artifactory_prop else None
        repo_name = (
            artifactory_props.get('REPO_NAME')[0].lower()
            if artifactory_props and 'REPO_NAME' in artifactory_props
            else os.environ.get('PROJECT_GIT_REPO', '').lower()
        )
        repo_prefix = repo_name.split('-')[0] if repo_name else None
        with open(f"{os.getenv('CONSTANTS_PATH')}/qualitygate_exclusion_list_v2.yml", "r") as stream: 
        # with open(f"{workspace}/shared-github-actions-config-cdo-kp-org/qualitygate_exclusion_list_v2.yml", "r") as stream: # enable for testing
           current_exclusion_list = yaml.safe_load(stream) # enable after testing
        stream.close()
        gate_map = {}
        gating_type = os.getenv('GATE_TYPE')
        gating_type_list = gating_type.split(",")
        for gating_type in gating_type_list:
            gating_type = gating_type.strip()
            if(gating_type == "sonar"):
                gate_title = 'SonarQuality Gate'
                gate_name = 'sonarQualityGate'
            elif(gating_type == "auto_rollback"):
                gate_title = 'Auto Rollback on Smoke Test Failure'
                gate_name = 'auto-rollback'
            elif(gating_type == "regression_quality_gate"):
                gate_title = 'RegressionQuality Gate'
                gate_name = 'regressionQualityGate'
            elif(gating_type == "deployment_workflow"):
                gate_title = "Deployment Ticket Workflow"
                gate_name = 'deploymentWorkflow'
            elif(gating_type == "dod_workflow"):
                gate_title = "Definition of Done Workflow"
                gate_name = 'dodWorkflow'
            elif(gating_type == "replica_count_exception"):
                gate_title = "Replica Count Exception"
                gate_name = 'replicaCountException'
            elif(gating_type == "tidelift_workflow"):
                gate_title = "TideLift Workflow"
                gate_name = 'tideLiftWorkflow'
            elif(gating_type == "nexusWorkflow"):
                gate_title = "Nexus Workflow"
                gate_name = 'nexusWorkflow'
            elif(gating_type == "aem_guardrails"):
                gate_title = 'AEM Guardrails'
                gate_name = 'aemGuardrails'
            elif(gating_type == "round_robin_exception"):
                gate_title = 'Round Robin Exception'
                gate_name = 'roundRobinException'
            elif(gating_type == "p1_quality_gate"):
                gate_title = 'P1 Quality Gate Exception'
                gate_name = 'p1QualityGate'
            elif(gating_type == "target_quality_gate"):
                gate_title = 'target Quality Gate Exception'
                gate_name = 'targetQualityGate' 
            else:
                raise Exception('[ERROR] Could Not determine gating type')
            gate_map[gating_type] = [gate_title, gate_name]
        #commenting below switchCase option as python3 version is below 3.10
        # match gating_type:
        #     case "sonar":
        #         gate_title = 'SonarQuality Gate'
        #         gate_name = 'sonarQualityGate'
            
        #     case "autoRollback":
        #         gate_title = 'Auto Rollback on Smoke Test Failure'
        #         gate_name = 'auto-rollback'
                
        #     case "regressionQualityGate":
        #         gate_title = 'RegressionQuality Gate'
        #         gate_name = 'regressionQualityGate'
                
        #     case "deploymentWorkflow":
        #         gate_title = "Deployment Ticket Workflow"
        #         gate_name = 'deploymentWorkflow'
                
        #     case "dodWorkflow":
        #         gate_title = "Definition of Done Workflow"
        #         gate_name = 'dodWorkflow'
                
        #     case "replicaCountException":
        #         gate_title = "Replica Count Exception"
        #         gate_name = 'replicaCountException'
                
        #     case "tideLiftWorkflow":
        #         gate_title = "TideLift Workflow"
        #         gate_name = 'tideLiftWorkflow'
                
        #     case "nexusWorkflow":
        #         gate_title = "Nexus Workflow"
        #         gate_name = 'nexusWorkflow'
                
        #     case "aemGuardrails":
        #         gate_title = 'AEM Guardrails'
        #         gate_name = 'aemGuardrails'
        
        #     case "divergentBranch":
        #         gate_title = 'Divergent Branch Check'
        #         gate_name = 'divergentBranch'
                
        #     case _:
        #         error("[ERROR] Could Not determine gating type")
        
        #check for repo in gate (specific condition for deploymentWorkflow as orgs can also be excluded)
        exception_status_map = {}
        exception_expiration_date_map = {}
        for gating_type in gate_map:
            exclusion_status = True
            gate_title = gate_map[gating_type][0]
            gate_name = gate_map[gating_type][1]
            gate_name_exclusions = current_exclusion_list[gate_name]
            #logger.info(gate_name_exclusions)
            if (not gate_name_exclusions):
                logger.info("no gate exclusions")
                exclusion_status = True
            else:
                for excluded_repo in gate_name_exclusions:
                    if(excluded_repo['repo'] == repo_name or (gating_type == "deploymentWorkflow" and excluded_repo['repo'] ==  repo_prefix)):
                        logger.info(f"[INFO] Repo {repo_name} found in exclusion list for {gating_type}. Checking expiration date.")
                        is_valid = check_exclusion_expiration(excluded_repo['date'])
                        if(is_valid == True):
                            logger.info(f"[INFO] {gate_name} has been disabled for {repo_name} in {gating_type}")
                            exclusion_status = False
                            exception_expiration_date_map[gating_type] = excluded_repo['date']
                            logger.info(f'{gate_title} is EXEMPTED for {repo_name}')
                            break
                        else:
                            logger.info(f'{gate_name} exclusion expired for {repo_name} in {gating_type}')
                            exclusion_status = True
                            logger.info(f'{gate_title} is NOT EXEMPTED for {repo_name}')
                            break
                    else:
                        exclusion_status = True
                        logger.debug(f'{gate_title} is NOT EXEMPTED for {repo_name}')
            exception_status_map[gating_type] = exclusion_status
    except Exception as e:
        logger.error(f"Error encountered while determining the quality gate : {e}")
        raise Exception(f"{COLOR_RED} Error encountered while determining the quality gate : {e}")
    logger.info(f"exception status map: {exception_status_map}")
    logger.info(f"exception expiration date map: {exception_expiration_date_map}")
    os.system(f"echo 'exception-status-map={json.dumps(exception_status_map)}' >> $GITHUB_OUTPUT")
    os.system(f"echo 'exception-expiration-date-map={json.dumps(exception_expiration_date_map)}' >> $GITHUB_OUTPUT")

        
def check_exclusion_expiration(expiration_date):
    current_date = datetime.now().strftime("%Y-%m-%d")
    if(datetime.strptime(expiration_date, '%Y-%m-%d %H:%M:%S') < datetime.strptime(current_date, '%Y-%m-%d')):    
        logger.info("[INFO] Gate exclusion has expired.")
        return False
    else:
        return True
 

if __name__ == "__main__":
    logger.info(logger.format_msg('GHA_EVENT_ACTION_AUD_2_9000', 'action entry/exit point', {"detailMessage": "action metric", "metrics": {"state": "start"}}))
    main()
    logger.info(logger.format_msg('GHA_EVENT_ACTION_AUD_2_9000', 'action entry/exit point', {"detailMessage": "action metric", "metrics": {"state": "end"}}))