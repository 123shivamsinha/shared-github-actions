import os
import psycopg2
from datetime import datetime
import json
import sys
import ast
from pytz import timezone
import pytz


from kpghalogger import KpghaLogger
logger = KpghaLogger()

try:
    conn_params = {
        'dbname':os.getenv('PG_DB_NAME'),
        'user':os.getenv('PG_DB_USER'),
        'password':os.getenv('PG_DB_PWD'),
        'host':os.getenv('PG_DB_HOST'),
        'port':"5432"  
    }
    bot_manifest = sys.argv[1] 
    chg_nbr = os.getenv('CHG_NBR')
    step_name = sys.argv[2] 
    step_comments = sys.argv[3] 
    app_type = sys.argv[4].upper()
    deploy_env = sys.argv[5] or "dev"

    tidelift_pct = os.getenv('TIDELIFT_PCT') or ""
    tidelift_comments = os.getenv('TIDELIFT_COMMENTS') or ""
    nexus_comments = os.getenv('NEXUS_COMMENTS') or ""
    checkmarx_comments =  os.getenv('CHECKMARX_COMMENTS') or ""
    sonar_comments =  os.getenv('SONAR_COMMENTS') or ""
    run_nbr = os.getenv('GITHUB_RUN_ID')
    action = os.getenv('ACTION')
    app_name = os.getenv('APP_NAME')
    app_version = os.getenv('APP_VERSION')
    repo_name = os.getenv('PROJECT_GIT_REPO')
    org = os.getenv('PROJECT_GIT_ORG')
    branch_name = os.getenv('GITHUB_REF_NAME')
    conn = psycopg2.connect(**conn_params)
    logger.info(f'bot manifest {bot_manifest}')
    if isinstance(bot_manifest, str):
        bot_manifest = ast.literal_eval(bot_manifest)
    
    # Uncomment this if detailed view of sonar result is required
    # if step_name == 'Sonarqube':
    #     sonar_comments_json = json.loads(os.getenv('SONAR_COMMENTS'))
    #     logger.info(f'Sonar comments: {sonar_comments_json}')
    #     #if not sonar_comments_json:
    #     metrics = [(condition['metricKey'], condition['actualValue']) for condition in sonar_comments_json['conditions']]
    #     for metricKey, actualValue in metrics:
    #         sonar_comments += f"{metricKey} : {actualValue};"

    if action == 'start':
        bot_manifest_json = ''
        app_name = app_name
        app_version = app_version
        repo_name = org+'/'+repo_name
        branch_name = branch_name
        bio_name = org
        release_date = ''
        deploy_ticket = ''
        release_ticket = ''
    else:
        bot_manifest_json = json.loads(bot_manifest)
        app_name = bot_manifest_json['appname']
        app_version = bot_manifest_json['artifactversion']
        repo_name = org+'/'+repo_name
        bio_name = org
        release_date = bot_manifest_json['ScheduledDate']
        deploy_ticket = bot_manifest_json['jiraTicket']
        if "rmTicket" in bot_manifest_json:
            release_ticket = bot_manifest_json['rmTicket']
        else:
            release_ticket = ''
    try:
        cursor = conn.cursor()
        conn.autocommit = False
        utc_now = datetime.now(pytz.utc)
        pacific_tz = pytz.timezone('America/Los_Angeles')
        pacific_now = utc_now.astimezone(pacific_tz)
        formatted_now = pacific_now.strftime('%m/%d/%Y %H:%M:%S')
        logger.info(f' pacific time : {pacific_now}')
        
        result_map = {"app_Name": app_name, "app_version": app_version, "deploy_env": deploy_env, "created_at": formatted_now, "repo_name": repo_name, "app_type": app_type, "bio_name": bio_name, "release_date": release_date, "deploy_ticket": deploy_ticket, "crq_nbr": chg_nbr, "step_name": step_name, "step_comments": step_comments, "release_ticket": release_ticket, "run_nbr": run_nbr,"branch_name":branch_name,"sonar_comments":sonar_comments,"tidelift_pct":tidelift_pct,"nexus_comments":nexus_comments,"checkmarx_comments":checkmarx_comments,"tidelift_comments":tidelift_comments}
        logger.info(f'{result_map}')
        step_name_fmt = step_name.replace("BOT", "").replace(" ", "")
        logger.info(logger.format_msg(f'GHA_BOT_{step_name_fmt.upper()}_AUD_2_0001', f'{step_name} Result Map', {'detailMessage': 'BOT metrics for logger event' , 'metrics': result_map}))
        cursor.execute("INSERT INTO rrb_deployments (app_Name, app_version, deploy_env,created_at,repo_name,app_type,bio_name,release_date,deploy_ticket,crq_nbr,step_name,step_comments,release_ticket,run_nbr,branch_name,sonar_comments,tidelift_pct,nexus_comments,checkmarx_comments,tidelift_comments) VALUES (%s, %s, %s,%s, %s, %s,%s, %s, %s,%s, %s , %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                        (app_name, app_version, deploy_env,formatted_now,repo_name,app_type,bio_name,release_date,deploy_ticket,chg_nbr,step_name,step_comments,release_ticket,run_nbr,branch_name,sonar_comments,tidelift_pct,nexus_comments,checkmarx_comments,tidelift_comments))
        conn.commit()
        logger.info(f"Transaction committed successfully.")
    except Exception as e:
        logger.error(f"An error occurred: {e}")
        conn.rollback()
    finally:
        cursor.close()
        conn.close()
except Exception as e:
    logger.error(f"An error occurred: {e}. Metrics will not be send to the DB, but the pipeline will proceed.")