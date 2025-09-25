import os
import sys
import json
import yaml
import time
import subprocess
from kpghalogger import KpghaLogger
logger = KpghaLogger()

workspace = os.getenv('GITHUB_WORKSPACE')
repo_name = os.getenv('PROJECT_GIT_REPO')
org_name = os.getenv('PROJECT_GIT_ORG')
branch_name = os.getenv('GITHUB_REF_NAME')
bot_deploy = os.getenv('BOT_DEPLOY')
bot_rule_map = os.getenv('BOT_RULES_MAP') or {}
is_pr_branch = True if os.getenv('GITHUB_EVENT_NAME').lower() == 'pull_request' else False
tidelift_exception_result = json.loads(os.getenv('TIDELIFT_EXCEPTION_STATUS')).get('tidelift_workflow') if (org_name == 'CDO-KP-ORG' or org_name == 'SDS') and os.getenv('TIDELIFT_EXCEPTION_STATUS') else False
os.environ['TIDELIFT_API_KEY'] = os.getenv('TIDELIFT_TOKEN')
os.environ['TIDELIFT_TIMEOUT'] = '150'
os.environ['TIDELIFT_SKIP_UPDATE_CHECK'] = '1'

def get_tidelift_version():
    """
    Get the version of Tidelift
    """
    try:
        tidelift_version = subprocess.check_output('/usr/bin/tidelift version', stdin=subprocess.PIPE, shell=True, text=True)
        logger.info(f"Tidelift version is: {tidelift_version}")
    except Exception as e:
        logger.error(f"Exception from get tidelift version() -> {e}")

def create_group(tidelift_group, tidelift_organization, tidelift_debug_string):
    """
    Create a new group in Tidelift
    """
    try:
        tidelift_groups = tidelift_group.split(',')
        tidelift_groups_str = ','.join(tidelift_groups)
        logger.info(f"Tidelift group {tidelift_groups_str} ")
        for new_group in tidelift_groups:
            logger.info(f"************************** TIDELIFT GROUP CREATION FOR {new_group} **************************")
            create_group_cmd = f"/usr/bin/tidelift groups new {new_group} --organization {tidelift_organization} --json {tidelift_debug_string}"
            logger.info(f"Command that's getting executed: {create_group_cmd}")
            create_group_resp = subprocess.run(create_group_cmd, capture_output=True, shell=True)
            
            if create_group_resp.returncode != 0:
                create_group_json = create_group_resp.stderr.decode()
            else:
                create_group_json = create_group_resp.stdout.decode()
            #HIPPO: Error Handling
            if 'that group already exists' in create_group_json:
                logger.info(f"Tidelift group {tidelift_group} already exists")
            elif 'error' in create_group_json:
                logger.error("Error in Tidelift group creation")    
            else:
                logger.info('Tidelift group creation successful')
    except Exception as e:
        logger.warning(logger.format_msg('GHA_TRO_TIDELIFT_BIZ_3_2001', 'Exception from TL group creation', {'detailMessage': f'Exception from Tidelift group creation: {e}', 'metrics': {'status': 'failure'}}))

def create_project(tidelift_project_name, tidelift_catalog, tidelift_organization, tidelift_group, tidelift_debug_string):
    """
    Create a new project in Tidelift
    """
    try:
        tidelift_groups = tidelift_group.split(',')
        for new_group in tidelift_groups:
            logger.info(f"************************** TIDELIFT PROJECT CREATION WITH GROUP {new_group} **************************")
            create_proj_cmd = f"/usr/bin/tidelift projects new {tidelift_project_name} --catalog {tidelift_catalog} --organization {tidelift_organization} --group {new_group} --json {tidelift_debug_string}"
            logger.info(f"Command that's getting executed: {create_proj_cmd}")
            create_proj_resp = subprocess.run(create_proj_cmd, capture_output=True, shell=True)
            if create_proj_resp.returncode != 0:
                create_proj_json = create_proj_resp.stderr.decode()
                logger.info(f"Printing response stderr {create_proj_json} ")     
            else:
                create_proj_json = create_proj_resp.stdout.decode()
                logger.info(f"Printing response stdout {create_proj_json} ")

            if repo_name in create_proj_json:
                logger.info(f"found repo name : {repo_name} in json response")
                create_proj_json = create_proj_json.replace(repo_name, "")
                logger.info(f"removed repo name : {repo_name} from json response...")    

            if 'existing_project' in create_proj_json or '.tidelift file already exists' in create_proj_json:
                logger.info("Tidelift project already exists")

            elif 'invalid groups' in create_proj_json:
                logger.error(f"Tidelift project creation failure -- group with {tidelift_group} not found; please raise <a href='https://jira-aes.kp.org/servicedesk/customer/portal/9/create/664'>service-desk ticket </a>here.")
                tidelift_check_comment = f"Tidelift alignment skipped, group with {tidelift_group} not found; please raise <a href='https://jira-aes.kp.org/servicedesk/customer/portal/9/create/664'>service-desk ticket </a>here."
                tidelift_check_result = False
                result_map = check_pr_branch_and_create_result_map(tidelift_check_result, tidelift_check_comment)
                return result_map
                
            elif 'error' in create_proj_json:
                logger.error(f"Tidelift project creation failure -- {create_proj_json}")
                tidelift_check_comment = f"Tidelift alignment skipped, onboarding project failed; please raise <a href='https://jira-aes.kp.org/servicedesk/customer/portal/9/create/664'>service-desk ticket </a>here."
                tidelift_check_result = False
                result_map = check_pr_branch_and_create_result_map(tidelift_check_result, tidelift_check_comment)
                return result_map               
            else:
                logger.info(logger.format_msg('GHA_TRO_TIDELIFT_BIZ_2_0002','Successful project creation', {'detailMessage': 'Tidelift project creation successful', 'metrics': {'status': 'success'}}))
                return None
    except Exception as e:
        logger.warning(logger.format_msg('GHA_TRO_TIDELIFT_BIZ_3_2002', 'Exception from project creation', {'detailMessage': f'Exception from Tidelift project creation: {e}', 'metrics': {'status': 'failure'}}))

def update_project(tidelift_project_name, tidelift_organization, tidelift_catalog, tidelift_group, tidelift_default_string, tidelift_debug_string):
    """
    Update a project in Tidelift
    """
    try:
        tidelift_groups = tidelift_group.split(',')
        tidelift_groups_str = ','.join(tidelift_groups)
        logger.info(f"Tidelift group {tidelift_groups_str} ")
        logger.info(f"************************** TIDELIFT UPDATE PROJECT **************************")
        update_proj_cmd = f"/usr/bin/tidelift projects update --project {tidelift_project_name}  --organization {tidelift_organization} --catalog {tidelift_catalog} --group {tidelift_groups_str} {tidelift_default_string} {tidelift_debug_string} --json"
        logger.info(f"[INFO]update project cmd : {update_proj_cmd}")
        update_proj_resp = subprocess.check_output(update_proj_cmd, shell=True, text=True)
        update_proj_json = json.loads(update_proj_resp)
        logger.info(logger.format_msg('GHA_TRO_TIDELIFT_BIZ_2_0003', 'Tidelift project update response', {'detailMessage': update_proj_json, 'metrics': {'status': 'success'}}))
    except Exception as e:
        logger.warning(logger.format_msg('GHA_TRO_TIDELIFT_BIZ_3_2003', 'Tidelift project update exception', {'detailMessage': f'Exception from Tidelift update project: {e}', 'metrics': {'status': 'failure'}}))

def run_alignment(tidelift_project_name, tidelift_organization, tidelift_debug_string, tidelift_cache_string, tidelift_branch):
    """
    Run alignment in Tidelift
    """
    #exclude_dir = get_tl_exclude_dir(build_var_map) TODO: commented as its not being used in current shared libs
    alignment_map ={}
    alignment_msg = ''
    try:        
        # subprocess.check_output('chmod u+w /home/runner/.m2/repository', shell=True, text=True)
        logger.info(f'************************** TIDELIFT RUN ALIGNMENT **************************')
        response_json = '1>response.json'
        os.environ['TIDELIFT_TIMEOUT'] = '150'
        logger.info(f"tidelift timeout : {os.environ['TIDELIFT_TIMEOUT']}")
        run_align_cmd = f"tidelift alignment save --wait --project {tidelift_project_name} --organization {tidelift_organization} -R --json {response_json} {tidelift_debug_string} {tidelift_cache_string} --branch {tidelift_branch}"
        logger.info(f"Run align command: {run_align_cmd}")
        run_align_resp = subprocess.check_output(run_align_cmd, shell=True, text=True)
        logger.info(logger.format_msg('GHA_TRO_TIDELIFT_AUD_2_0001', 'Tidelift Run Alignment Response', {'detailMessage': run_align_resp, 'metrics': {'status': 'success'}})) 
    except Exception as e:
        alignment_map['status'] = 'error'
        logger.error(logger.format_msg("GHA_TRO_TIDELIFT_AUD_4_1001","Tidelift Run Alignment Error", {'detailMessage': f'Exception from Tidelift run_alignment: {e}', 'metrics': {'status': 'failure'}}))       
    try:
        time.sleep(3)
        with open(f"{workspace}/response.json", "r") as f:
            run_align_json = json.loads(f.read())
            # logger.info(f"Alignment run_align_json :{run_align_json}")
            alignment_map['alignment_pct'] = round(run_align_json.get('alignment_pct'), 1)
            alignment_map['status'] = run_align_json.get('status')
            alignment_map['statistics'] = run_align_json.get('statistics')
            alignment_map['production_statistics'] = run_align_json.get('production_statistics')
            alignment_map['details_url'] = run_align_json.get('details_url')
            alignment_msg = "Total: {}<br>Approved: {}<br> <a href='{}'>Alignment Results</a>".format(run_align_json.get('statistics').get('total_count'), run_align_json.get('statistics').get('approved_count'), run_align_json.get('details_url'))
            map_sts = alignment_map['statistics']
            logger.info(logger.format_msg("GHA_TRO_TIDELIFT_AUD_2_0004","Tidelift Alignment", {'detailMessage': alignment_map, 'metrics': map_sts}))
            # set output to pass to artifactory action
            scan_results = {'TIDELIFT_ALIGNMENT': f"{alignment_map['alignment_pct']}"}

            os.system(f"echo 'scan-alignment={json.dumps(scan_results)}' >> $GITHUB_OUTPUT")
    except Exception as e:
        logger.warning(logger.format_msg('GHA_TRO_TIDELIFT_BIZ_4_1003', 'Tidelift response.json cannot be read', {'detailMessage': f'Error reading response.json: {e}', 'metrics': {'status': 'failure'}}))
    return alignment_msg, alignment_map    
          
def check_pr_branch_and_create_result_map(tidelift_check_result, tidelift_check_comment):
    """
    Check if the current branch is a pull request branch and create result_map if necessary
    """
    if os.getenv('GHA_ORG') != 'ENTERPRISE':
       is_pr_branch = os.getenv('GITHUB_EVENT_NAME').lower() == 'pull_request'
       if is_pr_branch:
          pr_builder = yaml.safe_load(os.getenv('PR_BUILDER'))
          tidelift_check_title = pr_builder.get('tidelift-check').get('title')
          tidelift_check_squad = pr_builder.get('tidelift-check').get('squads')
          result_map = {}
          result_map['result_map'] = []
          result_map['result_map'].append({'title':tidelift_check_title, 'squads': tidelift_check_squad,  'result': tidelift_check_result, 'comments': f'{tidelift_check_comment}' })
          return result_map
       return None

def main():
    build_var_map = yaml.safe_load(sys.argv[1])
    #PRCheck variables
    alignment_map = {}
    if os.getenv('GHA_ORG') == 'ENTERPRISE':
        tidelift_failure_threshold = 70
        tidelift_threshold = build_var_map.get('build_group').get('tideliftThresholdPercentage')
        logger.info(f"tidelift threshold: {tidelift_threshold}")
        if tidelift_threshold:
            tidelift_failure_threshold = int(tidelift_threshold)
    else:
        tidelift_failure_threshold = 85
    logger.info(f"tidelift failure threshold: {tidelift_failure_threshold}")   
    scan_branch = branch_name
    #Tidelift variables
    tidelift_project_name = repo_name
    tidelift_organization = 'team/Kaiser-Permanente'
    tidelift_catalog = 'default'
    atlas_id = build_var_map.get('app_props').get('atlas_id')
    tidelift_group = f"{atlas_id},{org_name}"
    tidelift_cache_time = ''
    tidelift_debug = False
    tidelift_check_result = ''
    tidelift_branch = branch_name if is_pr_branch and os.getenv('GHA_ORG') != 'ENTERPRISE' else scan_branch
    logger.info(f"Starting Tidelift check of branch: {tidelift_branch}")
    tidelift_default_string = '' if is_pr_branch else '--default-branch ' + tidelift_branch

    if tidelift_cache_time == '': tidelift_cache_string = ''
    else: tidelift_cache_string = '--skip-if-cached=' + tidelift_cache_time

    if tidelift_debug == True: tidelift_debug_string = '--debug'
    else: tidelift_debug_string = ''

    #check pipeline.json atlas-id org
    if atlas_id != None:
        if tidelift_group.startswith('APP-') or tidelift_group.startswith('app-'):
            tidelift_group = tidelift_group.upper()
            logger.info(f"tidelift group: {tidelift_group}")
        else:
            logger.warning(f"[WARN] Tidelift execution failed: pipeline.json 'atlas-id' does not follow 'APP-####' format.")
            tidelift_check_comment = f" Tidelift alignment failed: pipeline.json 'atlas-id' does not follow 'APP-####' format."
            tidelift_check_result = False
            result_map = check_pr_branch_and_create_result_map(tidelift_check_result, tidelift_check_comment)
            if result_map is not None:
                return result_map
    else:
        logger.warning(f"[WARN] Tidelift execution failed: pipeline.json 'atlas-id' was not defined")
        tidelift_check_comment = f" Tidelift alignment failed: pipeline.json 'atlas-id' was not defined."
        tidelift_check_result= False
        result_map = check_pr_branch_and_create_result_map(tidelift_check_result, tidelift_check_comment)
        if result_map is not None:
            return result_map

    # Tidelift version
    get_tidelift_version()

    # Create Group; Should not error if group exist
    create_group(tidelift_group, tidelift_organization, tidelift_debug_string)

    # Create new project; should not error even if project exists
    result_map = create_project(tidelift_project_name, tidelift_catalog, tidelift_organization, tidelift_group, tidelift_debug_string)
    if result_map is not None:
        return result_map

    # Update catalog, group and default branch to match current config
    update_project(tidelift_project_name, tidelift_organization, tidelift_catalog, tidelift_group, tidelift_default_string, tidelift_debug_string)

    # Run alignment
    alignment_msg,alignment_map = run_alignment(tidelift_project_name, tidelift_organization, tidelift_debug_string, tidelift_cache_string, tidelift_branch)
    logger.info(f"alignment msg: {alignment_msg}, alignment map: {alignment_map}")
    # PRCheck logic
    if alignment_map['status'] == 'failure':
        if alignment_map['alignment_pct'] > tidelift_failure_threshold:
            tidelift_check_comment = "Tidelift Alignment {0}% meets the required threshold of {1}%.<br> {2}".format(alignment_map['alignment_pct'], tidelift_failure_threshold, alignment_msg)
            tidelift_check_result = True
        else:
            tidelift_check_comment = " Tidelift Alignment {0}% does not meet required threshold of {1}%.<br> {2}".format(alignment_map['alignment_pct'], tidelift_failure_threshold, alignment_msg)
            tidelift_check_result = False
    elif alignment_map['status'] == 'error':
        tidelift_check_comment = " Tidelift Alignment resulted in internal error."
        tidelift_check_result = False
    else :
        tidelift_check_comment = " Tidelift Alignment resulted in success: {0}%.<br> {1}".format(alignment_map['alignment_pct'], alignment_msg)
        tidelift_check_result = True
    logger.info(f"tidelift check result: {tidelift_check_result}")
    logger.info(f"tidelift exception result: {tidelift_exception_result}")
    if tidelift_exception_result == False:
       logger.info("Tidelift has been exempted for this project")
    if tidelift_check_result == False and tidelift_exception_result == False:
       logger.info("Tidelift has been exempted for this project")
       tidelift_check_result = True
       logger.info(f"tidelift check result: {tidelift_check_result}")
    
    align_pct = alignment_map.get('alignment_pct', 'Alignment failed to run')
    if bot_deploy == 'true':
        bot_json_map = json.loads(bot_rule_map)
        if bot_json_map.get("TideliftisRequired"):
            tidelift_threshold = bot_json_map.get("QualityChecks").get("Tidelift")
            logger.error(f"bot tidelift threshold {tidelift_threshold}")

            if align_pct != "Alignment failed to run":
                if float(align_pct) < tidelift_threshold:
                    logger.error("Tidelift BOT Threshold failed the criteria")
                    tidelift_check_result = False
        else:
            tidelift_check_result = True
            logger.error("BOT Tidelift check is marked as SKIP!")
    os.system(f"echo 'tidelift-pct={str(align_pct)}' >> $GITHUB_OUTPUT")
    os.system(f"echo 'tidelift-results-url={str(alignment_map['details_url'])}' >> $GITHUB_OUTPUT")
    os.system(f"echo 'tidelift-check-result={tidelift_check_result}' >> $GITHUB_OUTPUT")

    logger.info(logger.format_msg('GHA_TRO_TIDELIFT_AUD_2_0006', 'Tidelift result', {'detailMessage': f'TL check: {tidelift_check_comment}', 'metrics': {'alignmentscore': align_pct, 'failurethreshold': tidelift_failure_threshold, 'checkresult': tidelift_check_result, 'checkexception': tidelift_exception_result}}))
    if alignment_map:
        subprocess.run([f"""echo "#### :shield: [Tidelift report URL]({alignment_map.get('details_url')})" >> $GITHUB_STEP_SUMMARY"""], shell=True)
    result_map = check_pr_branch_and_create_result_map(tidelift_check_result, tidelift_check_comment)
    return result_map


if __name__ == '__main__':
    logger.info(logger.format_msg('GHA_EVENT_ACTION_AUD_2_9000', 'action entry/exit point', {"detailMessage": "action metric", "metrics": {"state": "start"}}))
    result_map = main()
    os.system(f"echo 'tidelift-result-check-status={json.dumps(result_map)}' >> $GITHUB_OUTPUT") 
    logger.info(logger.format_msg('GHA_TRO_TIDELIFT_BIZ_2_0005', 'Tidelift PR check Result Map', {'detailMessage': result_map, 'metrics': {'status': 'success'}}))
    logger.info(logger.format_msg('GHA_EVENT_ACTION_AUD_2_9000', 'action entry/exit point', {"detailMessage": "action metric", "metrics": {"state": "end"}}))
    