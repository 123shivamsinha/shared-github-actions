import os
import main
import re
import json
import yaml
import sys
import requests
from kpghalogger import KpghaLogger
logger = KpghaLogger()

COLOR_RED = "\u001b[31m"
nexus_webservice = yaml.safe_load(os.getenv('NEXUS_WEBSERVICE') or '{}')
repo_name = os.getenv('PROJECT_GIT_REPO')
org_name = os.getenv('PROJECT_GIT_ORG')
codebase_repo_url = f"{os.getenv('GITHUB_SERVER_URL')}/{os.getenv('GITHUB_REPOSITORY')}.git"
#codebase_repo_url = 'https://github.kp.org/CDO-KP-ORG/doet-productzero-java-service-aks.git' #uncomment if needed for testing purpose
build_url = os.getenv('BUILD_URL')
application_json = 'application/json'


def main():
    try:
        build_var_map = yaml.safe_load(sys.argv[1])
        branch_name = (build_var_map.get('scan_branch') or (build_var_map.get('app_props') or {}).get('branch_name') or '' )
        logger.info(f"security onboarding scan branch name: {branch_name}")
        # Define security variables
        (codebase_map_id_url, onboard_url, authenticate_url, application_name, email_list, team_name, 
        mobile_version, atlas_id, technical_sme, asm_number) = define_security_variables(build_var_map)
        # Get JWT Token
        tro_jwt_token = generate_jwt_token(authenticate_url)
        if tro_jwt_token :
            tro_codebase_id = generate_codebase_mapping_id(tro_jwt_token, atlas_id, asm_number, technical_sme, codebase_map_id_url, application_name, email_list, mobile_version)
            logger.info(f"tro codebase id --> {tro_codebase_id}")
            # Onboard application
            if tro_codebase_id :
                project_name = f"{org_name}-{repo_name}"
                nexus_iq_id = project_name
                if os.getenv('GHA_ORG') == 'ENTERPRISE':
                    var_map = build_var_map.get('build_group') if build_var_map else None
                    if var_map and 'securityScan' in var_map:
                        branch_name = var_map['securityScan'].get('scanBranch', branch_name)
                        logger.info(f"Using scanBranch from securityScan: {branch_name}")
                    else:
                        logger.info(f"Using existing branch name: {branch_name}")
                onboard_application(tro_codebase_id, onboard_url, team_name, project_name, nexus_iq_id, email_list, branch_name, build_url)
            else:
                logger.error(f"Failed to generate tro codebase id")
        else:
            logger.error(f"Failed to generate JWT token")
    except Exception as e:
        logger.error(f"Error in main: {e}")
        raise Exception(f"Error in main: {e}")

# Define security onboarding variables
def define_security_variables(build_var_map):
    try:
        if nexus_webservice:
            nexus_webservice_url = nexus_webservice.get('endpoint')
            tro_email = nexus_webservice.get('tro-email')
            codebase_map_id_url = nexus_webservice.get('codebase-map-id-url')
            onboard_url = nexus_webservice.get('onboard-url')
            logger.info(f"nexus webservice url: {nexus_webservice_url}")
            authenticate_url = nexus_webservice.get('authenticate-url')
            tro_psg = nexus_webservice.get('tro-psg')
        else:
            raise Exception(f"{COLOR_RED} Error: NEXUS_WEBSERVICE environment variable is not set or invalid")
        missing_pipeline_field = ""
        app_props = build_var_map.get('app_props')
        application_name = app_props.get('app_name') if app_props else None
        email_recipients = []
        team_name = yaml.safe_load(os.getenv('ORG_TEAM_NAME') or '')
        mobile_version = app_props.get('mobile_version') if app_props and app_props.get('mobile_version') else 'NA'
        atlas_id = app_props.get('atlas_id') if app_props else None
        if not (atlas_id and atlas_id.strip()):
            missing_pipeline_field = 'atlas_id'
        else:
            atlas_id = atlas_id.upper()  
            if not re.match('^APP-[0-9]*$',atlas_id): #Ex :"atlasId": "APP-2890",
                missing_pipeline_field = 'atlas-id(Invalid atlas-id)'
        
        technical_sme = app_props.get('technical_sme') if app_props else None  #NUID
        if not (technical_sme and technical_sme.strip()): 
            missing_pipeline_field = 'technicalSME' if not missing_pipeline_field else missing_pipeline_field + ', technicalSME'
        elif not re.match('^[a-z A-Z][0-9]{6}$',technical_sme):  #Ex: "technicalSME": "i489234"
            missing_pipeline_field = 'technicalSME(Invalid technicalSME)' if not missing_pipeline_field else missing_pipeline_field + ', technicalSME(Invalid technicalSME)'
        
        asm_number = app_props.get('asm_number') if app_props else None
        if not (asm_number and asm_number.strip()) or not re.match('^ASM[0-9]*$',asm_number):
            missing_pipeline_field = 'asmNumber(Invalid asmNumber)' if not missing_pipeline_field else missing_pipeline_field + ', asmNumber(Invalid asmNumber)'
        logger.info(f"missing pipeline field: {missing_pipeline_field}")
        logger.info(f"technical SME: {technical_sme}, atlas-id: {atlas_id}, asmNumber: {asm_number}")

        if missing_pipeline_field:
            logger.error(logger.format_msg('GHA_TRO_ONBOARDING_AUD_4_2001', 'Mandatory field missing in pipeline.json', {'detailMessage': f'Mandatory field(s) missing in pipeline.json file: {missing_pipeline_field}', 'metrics': {'status': 'failure'}}))
            raise Exception(f"{COLOR_RED}Mandatory field(s) missing in pipeline.json file : {missing_pipeline_field}-{tro_psg}")

        if app_props.get('notification_map') and app_props.get('notification_map').get('email_recipients'): 
            email_recipients = app_props.get('notification_map').get('email_recipients')
        email_list = email_recipients + [tro_email] if email_recipients else [tro_email]
        return (codebase_map_id_url, onboard_url, authenticate_url, application_name, email_list, 
                team_name, mobile_version, atlas_id, technical_sme, asm_number)
    except Exception as e:
        logger.error(logger.format_msg('GHA_TRO_ONBOARDING_BIZ_4_2001', 'Error in extracting pipeline variables', {'detailMessage': f'Error in extracting pipeline variables: {e}', 'metrics': {'status': 'failure'}}))
        raise Exception(f"{COLOR_RED}Error in extracting pipeline variables: {e}")


# Step 1 - Get JWT Token
def generate_jwt_token(authenticate_url):   
    logger.info('TRO Onboarding - Getting JWT Token')
    headers = {'Content-Type': application_json}
    jwt_token_cred_username = os.getenv('JWT_TOKEN_CRED_USERNAME')
    jwt_token_cred_password = os.getenv('JWT_TOKEN_CRED_PASSWORD')
    auth_data = json.dumps({ "username": jwt_token_cred_username, "password": jwt_token_cred_password })
    jwt_token = ''
    try:
        generate_jwt_response = requests.request("POST", authenticate_url, headers=headers, data=auth_data, verify=False)
    except Exception as err:
        logger.error(logger.format_msg('GHA_TRO_ONBOARDING_SYS_4_1002', 'Error in generate Jwt Token HTTP call', {'detailMessage': f'Error in generate Jwt Token - TRO HTTP call, skipping TRO Onboarding: {err}', 'metrics': {'status': 'failure'}}))
    try:
        if generate_jwt_response:
            generate_jwt_response_code = generate_jwt_response.status_code
            logger.info(f"TRO JWT Token generation HTTP call - Response httpCode = {generate_jwt_response_code}")
            if (generate_jwt_response_code == 200):
                tro_token_json_obj = json.loads(generate_jwt_response.text)['token']
                jwt_token = str(tro_token_json_obj)
            elif ( generate_jwt_response_code > 399):
                raise Exception(f"{COLOR_RED}Error: HTTP Response status code from the TRO JWT Token generation call: {generate_jwt_response_code}")
        else:
            logger.error(f'Error: TRO HTTP call for JWT Token generation got failed')
    except Exception as e:
        logger.error(logger.format_msg('GHA_TRO_ONBOARDING_BIZ_4_2002', 'Error in generate Jwt Token', {'detailMessage': f'Error in generate Jwt Token, skipping TRO Onboarding: {err}', 'metrics': {'status': 'failure'}}))
    return jwt_token


# Step 2 - Generate codebase ID / TRO Intake Automation
def generate_codebase_mapping_id(tro_jwt_token, atlas_id, asm_number, technical_sme, codebase_map_id_url, application_name, email_list, mobile_version):
    logger.info('TRO Onboarding - Generating Code Base Mapping Id')
    if 'NA' not in mobile_version:
        logger.info(f'Generating Code Base Mapping Id - codebase Repo URL: {codebase_repo_url}, atlas Id: {atlas_id}, asm Number: {asm_number}, technical SME: {technical_sme}, code base Map Id URL: {codebase_map_id_url}, application Name: {application_name}, mobile Version: {mobile_version}')
        payload = json.dumps({"codebaseRepoURL":f"{codebase_repo_url}","jenkinsURL":f"{build_url}","featureName":f"{application_name}", "technicalSME": f"{technical_sme}", "atlasId": f"{atlas_id}", "asmNumber": f"{asm_number}", "mobileVersion": f"{mobile_version}"})
    else:
        logger.info(f'Generating Code Base Mapping Id - codebase Repo URL: {codebase_repo_url}, atlas Id: {atlas_id}, asm Number: {asm_number}, technical SME: {technical_sme}, code base Map Id URL: {codebase_map_id_url}, application Name: {application_name}')
        payload = json.dumps({"codebaseRepoURL":f"{codebase_repo_url}","jenkinsURL":f"{build_url}","featureName":f"{application_name}", "technicalSME": f"{technical_sme}", "atlasId": f"{atlas_id}", "asmNumber": f"{asm_number}"})
           
    logger.info(f'TRO http body payload for code Base Mapping Id: {payload}')
    headers = {'Content-Type': application_json, 'Authorization': f'Bearer {tro_jwt_token}'}
    mappingid_response = None
    tro_codebase_id = {}
    try:
        mappingid_response = requests.request("POST", codebase_map_id_url, headers=headers, data=payload, verify=False)
        logger.info(f"mapping id response: {mappingid_response.text}")
    except Exception as err:
        logger.error(logger.format_msg('GHA_TRO_ONBOARDING_SYS_4_1003', 'Error in generating codebase mapping id HTTP call', {'detailMessage': f'Error in generating codebase mapping id - TRO HTTP call, skipping TRO Onboarding: {err}', 'metrics': {'status': 'failure'}}))
        notification_message = f"Error in getting response from the URL: {codebase_map_id_url}"
        create_notification_map(email_list, notification_message)
        #send_tro_email(email_list, application_name, 'Error in getting response from the URL: {codebase_map_id_url}', 'failed')
    if mappingid_response:
        mappingid_response_code = mappingid_response.status_code
        logger.info(f'TRO generate Code Base Mapping Id HTTP call - Response httpCode: {mappingid_response_code}')
        if mappingid_response_code == 200:
            codebase_response_json = mappingid_response.json()
            tro_codebase_id = codebase_response_json.get('codebaseMappingId')
        elif mappingid_response_code > 399 and mappingid_response_code < 500:
            raise Exception(f'{COLOR_RED}Error: HTTP Response status code from the TRO generateCodeBaseMappingId call: {mappingid_response.text}')
        elif mappingid_response_code > 499:
            logger.error(logger.format_msg('GHA_TRO_ONBOARDING_SYS_4_2003', 'Error HTTP response from generate Code Base Mapping Id call', {'detailMessage': f'Error: HTTP Response status code from the TRO generate Code Base Mapping Id call, skipping TRO Onboarding: {mappingid_response.text}', 'metrics': {'status': 'failure'}}))
    else:
        logger.error(logger.format_msg('GHA_TRO_ONBOARDING_SYS_2_2003', 'HTTP call for generate Code Base Mapping Id failed', {'detailMessage': f'TRO HTTP call for generate Code Bas Mapping Id failed, skipping TRO onboarding', 'metrics': {'status': 'failure'}}))
    return tro_codebase_id

# Step 3 - Onboard application / AppSec Integration
def onboard_application(tro_codebase_id, onboard_url, team_name, project_name, nexus_iq_id, email_list, branch_name, build_url):
    logger.info (f"TRO on Board Application - repoURL: {codebase_repo_url}, tag: {branch_name} ,tro Code base Id: {tro_codebase_id} , on Board URL: {onboard_url}, team Name: {team_name}, project Name: {project_name} , nexus Iq Id: {nexus_iq_id} , application Name: { project_name}")
    payload = json.dumps({"teamName": f"{team_name}", "repoUrl": f"{codebase_repo_url}", "tag": f"{branch_name}", "projectName": f"{project_name}", "nexusIqId": f"{nexus_iq_id}","applicationName": f"{project_name}", "troCodebaseId": f"{tro_codebase_id}", "jenkinsUrl": f"{build_url}"})
    logger.info(f"payload for onboard application: {payload}")
    headers = {'Content-Type': application_json}
    onboard_appln_response = None 
    try:
        onboard_appln_response = requests.request("POST", onboard_url, headers=headers, data=payload, verify=False)
        onboard_appln_response_text = json.loads(onboard_appln_response.text)
        logger.info(f"onboard_appln_response: {onboard_appln_response_text}")
    except Exception as e:
        logger.error(logger.format_msg('GHA_TRO_ONBOARDING_SYS_4_2004', 'Error in HTTP call for on BoardApplication', {'detailMessage': f'Error in on Board Application - TRO HTTP call, skipping TRO Onboarding: {e}', 'metrics': {'status': 'failure'}}))
        notification_message = f"Error in getting response from the URL: {onboard_url}"
        create_notification_map(email_list, notification_message)
    #send_tro_email(email_list, application_name, 'Error in getting response from the URL: ' + onboard_url, "failed")
    if onboard_appln_response_text:
        onboard_appln_response_code = onboard_appln_response.status_code
        logger.info(f'TRO onboarding application HTTP call - Response httpCode: {onboard_appln_response_code}')
        if onboard_appln_response_code:
            if (onboard_appln_response_code == 200 or onboard_appln_response_code == 201):
                logger.info(logger.format_msg('GHA_TRO_ONBOARDING_BIZ_2_0200', 'Application onboarded successfully', {'detailMessage': f'Onboarding successful, make a note of your applicationID: {onboard_appln_response}', 'metrics': {'status': 'success'}}))
            elif (onboard_appln_response_code == 409):
                logger.info(logger.format_msg('GHA_TRO_ONBOARDING_BIZ_2_0409', 'Application previously onboarded', f'Application has already been onboarded, applicationID: {onboard_appln_response}'))
            elif (onboard_appln_response_code > 399 and onboard_appln_response_code < 500):
                raise Exception(f'{COLOR_RED}TRO Onboarding failed with http status code {onboard_appln_response_code} and the response: {onboard_appln_response_text}')
            elif (onboard_appln_response_code > 499):
                logger.error(logger.format_msg('GHA_TRO_ONBOARDING_BIZ_4_1005', 'TRO Onboarding failed', {'detailMessage': f'TRO Onboarding failed with http status code {onboard_appln_response_code} and the response: {onboard_appln_response_text}', 'metrics': {'status': 'failure'}}))
        data = onboard_appln_response_text.get('data')
        logger.info(f"data: {data}")
        for entry in data:
            if (entry.get('type') == 'Checkmarx One'):
                checkmarx_name = entry.get('name')
                checkmarx_id = entry.get('id')
            if (entry.get('type') == 'Nexus'):
                nexus_id = entry.get('id')
        logger.info(f"Application ID (NexusID): {nexus_id}, Checkmarx Name: {checkmarx_name}, Checkmarx ID: {checkmarx_id}")
        os.system(f"echo 'nexus-id={nexus_id}' >> $GITHUB_OUTPUT")
        os.system(f"echo 'checkmarx-name={checkmarx_name}' >> $GITHUB_OUTPUT")
        os.system(f"echo 'checkmarx-id={checkmarx_id}' >> $GITHUB_OUTPUT")
        os.system(f"echo 'team-name={team_name}' >> $GITHUB_OUTPUT")
        
        # Check if required outputs are empty and fail the workflow if they are
        if not (checkmarx_name and nexus_id and checkmarx_id):
            missing_outputs = []
            if not checkmarx_name:
                missing_outputs.append("checkmarx-name")
            if not checkmarx_id:
                missing_outputs.append("checkmarx-id")
            if not nexus_id:
                missing_outputs.append("nexus-id")
            
            error_message = f"Required security outputs are missing: {', '.join(missing_outputs)}"
            logger.error(logger.format_msg('GHA_TRO_ONBOARDING_BIZ_4_3001', 'Missing required security outputs', {'detailMessage': error_message, 'metrics': {'status': 'failure'}}))
            raise Exception(f"{COLOR_RED}{error_message}")

def create_notification_map(email_list, notification_message):
    notification_map = {}
    notification_map['email_recipients'] = email_list
    notification_map['message'] = notification_message
    os.system(f"echo 'notification-map={json.dumps(notification_map)}' >> $GITHUB_OUTPUT")


if __name__ == '__main__':
    logger.info(logger.format_msg('GHA_EVENT_ACTION_AUD_2_9000', 'action entry/exit point', {"detailMessage": "action metric", "metrics": {"state": "start"}}))
    try:
        main()
    except Exception as e:
        logger.error(logger.format_msg('GHA_TRO_ONBOARDING_AUD_4_2005', 'Error in security onboarding', {'detailMessage': f'An error occurred: {e}', 'metrics': {'status': 'failure'}}))
        logger.info(logger.format_msg('GHA_EVENT_ACTION_AUD_2_9000', 'action entry/exit point', {"detailMessage": "action metric", "metrics": {"state": "end"}}))
        raise Exception (f"{COLOR_RED}Error in security onboarding : {e}")
    logger.info(logger.format_msg('GHA_EVENT_ACTION_AUD_2_9000', 'action entry/exit point', {"detailMessage": "action metric", "metrics": {"state": "end"}}))