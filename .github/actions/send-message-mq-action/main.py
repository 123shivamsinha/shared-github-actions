# Program to send msg to RabbitMQ
# Sys args from commandline
# 1. rabbitmq host
# 2. User
# 3. password
import pika
import json
import time
import os
import yaml
import pytz
from datetime import datetime
from kpghalogger import KpghaLogger
logger = KpghaLogger()

workspace = os.getenv('GITHUB_WORKSPACE')
user_name = os.getenv('INSIGHTS_USERNAME')
user_pass = os.getenv('INSIGHTS_PASSWORD')
mq_host = os.getenv('RABBITMQ_HOST')
artifact_data_obj = os.getenv('MESSAGE_DATA')
queue = os.getenv('MESSAGE_QUEUE')
artifact_properties = os.getenv('ARTIFACT_PROPERTIES')
artifact_url = os.getenv('ARTIFACT_URL')
log_level = os.getenv('LOG_LEVEL') if os.getenv('LOG_LEVEL') else '20'
last_deployed_ver = os.getenv('LAST_DEPLOYED_VER')
operation = os.getenv('OPERATION')
deploy_env = os.getenv('DEPLOY_ENVIRONMENT')
us_pacific = 'US/Pacific'


def main():
    try:
        message_data_obj = yaml.safe_load(artifact_data_obj) if artifact_data_obj else None
        if not message_data_obj and operation == 'deploy-data':
            try:
                with open(f'{workspace}/deploy_map_{deploy_env}.yml', 'r') as f:
                    message_data_obj = yaml.safe_load(f).get('deployment_data')
            except Exception as e:
                logger.info(f'No AKS deploy data found: {e}')
        artifact_props = yaml.safe_load(artifact_properties) if artifact_properties else None
        exchange = 'iSight'
        if operation == 'deploy-data':
            message_deploy_data = {}
            last_deployed_version = yaml.safe_load(last_deployed_ver) if last_deployed_ver and last_deployed_ver != 'NOT_FOUND' else None

            message_deploy_data['name'] =  message_data_obj.get('artifact_id') or message_data_obj.get('name')
            message_deploy_data['version'] = message_data_obj.get('version') or message_data_obj.get('artifact_version')
            message_deploy_data['appType'] = message_data_obj.get('app_type')
            message_deploy_data['env'] = message_data_obj.get('deploy_env')
            message_deploy_data['rollback'] = message_data_obj.get('rollback', False)
            message_deploy_data['rollbackVersion'] = last_deployed_version.get('version') if last_deployed_version else (message_data_obj.get('rollback_version') or message_data_obj.get('rollbackVersion'))
            os.system(f"echo 'artifact-version={message_deploy_data['version']}' >> $GITHUB_OUTPUT")
            message_data_obj = construct_deploy_data(message_deploy_data)
        artifact_labels = message_data_obj['metadata']['labels'] if message_data_obj else None
        logger.info(f"Artifact labels: {artifact_labels}")

        if artifact_labels is not None:
            if 'DEPLOYMENT_DATA' in artifact_labels:
                queue = 'PIPELINE_DEPLOYMENT_DATA'
            elif 'APPSECJIRA_PIPELINE'in artifact_labels:
                queue = 'APPSEC_JIRA_DATA'
            elif 'DODCHECK'in artifact_labels:
                queue = 'DODCHECK_DOD_DATA'
            elif 'TEST' in artifact_labels:
                queue = 'ARTIFACTMANAGEMENT_ARTIFACTORY_DATA'
            else:
                # Send test data to Dashboard
                queue = 'CI_JENKINS_DATA'
        elif artifact_props is not None:
            message_data_obj = construct_build_data(artifact_props)
            queue = 'CI_JENKINS_DATA'
        else: queue = 'CI_JENKINS_DATA'
        routing_key = queue.replace('_','.')
        send_msg(mq_host, user_name, user_pass, exchange, queue, routing_key, message_data_obj)

    except Exception as e:
        logger.error(f"[ERROR] In send message to mq: {e}")
        notification_map = {}
        notification_map['message'] = f"Error sending message to message queue: {e}"
        os.system(f"echo 'notification-map={json.dumps(notification_map)}' >> $GITHUB_OUTPUT")
        raise Exception(f"In send message to mq: {e}")


def construct_build_data(artifact_props):
    build_time_stamp = ""
    time_stamp = artifact_props.get('BUILD_DATE') or artifact_props.get('build_date')
    build_url = artifact_props.get('BUILD_URL')
    if time_stamp:
        if isinstance(time_stamp, list):
            time_stamp = str(time_stamp[0])
        else:
            time_stamp = str(time_stamp)
        logger.info(f"time stamp: {time_stamp}")
        build_time = pytz.timezone(us_pacific).localize(datetime.strptime(time_stamp, '%Y%d%m%H%M%S'))
        build_time_stamp = build_time.strftime("%Y-%m-%d %H:%M:%S")
        logger.info(f"build time stamp : {build_time_stamp}")
    try:
        for k,v in artifact_props.items():
            if type(v) is list:
                artifact_props[k] = v[0]
        artifact_name = artifact_props.get('ARTIFACT_NAME') or artifact_props.get('artifactName')
        artifact_version = artifact_props.get('APP_VERSION') or artifact_props.get('artifactVersion')
        if isinstance(artifact_name, str) and isinstance(artifact_version, str):
            artifact_name_ver = f'{artifact_name}-{artifact_version}'
        elif isinstance(artifact_name, list) and isinstance(artifact_version, list):
            artifact_name_ver = f'{artifact_name[0]}-{artifact_version[0]}'
        artifact_props.update({"artifactNameVerFull": artifact_name_ver})
        artifact_props.update({"uri": artifact_url})
        artifact_props.update({"categoryName": "ARTIFACTMANAGEMENT"})
        artifact_props.update({"toolName": "ARTIFACTORY"})
        artifact_props.update({"inSightsTime": time.time()})
        artifact_props.update({"BUILD_DATE": build_time_stamp})

        message_data_object = {'data': [artifact_props], 'metadata': ({'labels': ['ARTIFACTORYPUSH']})}
        return message_data_object
    except AttributeError as e:
        raise Exception(f'Error constructing build data: {e}')

def construct_deploy_data(message_data):
    decommissioned = True if message_data.get('purge') else False
    deploy_data = {
        "data": [{
            "artifactName": message_data.get('name'),
            "version": message_data.get('version'),
            "rollback": message_data.get('rollback'),
            "rollbackVersion": message_data.get('rollbackVersion'),
            "decommissioned": decommissioned,
            "environment": message_data.get('env'),
            "appType": message_data.get('appType'),
            "deployedAt": pytz.timezone(us_pacific).localize(datetime.now()).strftime("%Y-%m-%d %H:%M:%S"),
            "deployedAtEpoch": pytz.timezone(us_pacific).localize(datetime.now()).strftime('%s')
        }],
        "metadata": {"labels": ["DEPLOYMENT_DATA"]}}
    return deploy_data


def send_msg(mq_host, user_name, user_pass, exchange, queue, routing_key, message_data_obj):
    message_data_obj.get('data')[0].update({'buildURL': os.getenv('BUILD_URL')})
    artifact_labels = message_data_obj['metadata']['labels'][0] if message_data_obj else None
    os.system(f"echo 'artifact-labels={artifact_labels}' >> $GITHUB_OUTPUT")
    logger.info(f"Host -> {mq_host}")
    logger.info(f"User -> {user_name}")
    logger.info(f"Exchange -> {exchange}")
    logger.info(f"Queue -> {queue}")
    logger.info(f"Routing_key -> {routing_key}")

    message_data_str = json.dumps(message_data_obj)

    try:
        # Set the connection parameters to connect to rabbit-server1 on port 5672
        # on the / virtual host using the username "guest" and password "guest"
        credentials = pika.PlainCredentials(user_name, user_pass)
        parameters = pika.ConnectionParameters(mq_host,5672,'/',credentials)
        connection = pika.BlockingConnection(parameters)
        channel = connection.channel()

        channel.exchange_declare(exchange=exchange, exchange_type='topic', durable=True)
        channel.queue_declare(queue=queue, passive=False, durable=True, exclusive=False, auto_delete=False, arguments=None)
        channel.queue_bind(queue=queue, exchange=exchange, routing_key=routing_key, arguments=None)
        channel.basic_publish(exchange=exchange, routing_key=routing_key, body=message_data_str, properties=pika.BasicProperties(delivery_mode=2))

        logger.info(f"[RabbitMQ] Sent from python3 -> {message_data_obj}")

    except Exception as e:
        logger.error(f"[ERROR] FAILURE: Could not publish to RabbitMQ: {e}")
        raise Exception(f"[ERROR] FAILURE: Could not publish to RabbitMQ: {e}")
    finally:
        if(connection):
            connection.close()

if __name__ == "__main__":
    logger.info(logger.format_msg('GHA_EVENT_ACTION_AUD_2_9000', 'action entry/exit point', {"detailMessage": "action metric", "metrics": {"state": "start"}}))
    try:
        main()
    except Exception as e:
        logger.error(f"[ERROR] FAILURE: Send message to mq action failed: {e}.")
        logger.info(logger.format_msg('GHA_EVENT_ACTION_AUD_2_9000', 'action entry/exit point', {"detailMessage": "action metric", "metrics": {"state": "end"}}))
        raise Exception(f"ERROR] FAILURE: Send message to mq action failed: {e}.")
    logger.info(logger.format_msg('GHA_EVENT_ACTION_AUD_2_9000', 'action entry/exit point', {"detailMessage": "action metric", "metrics": {"state": "end"}}))